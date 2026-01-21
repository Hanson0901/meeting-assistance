#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
會議流程控制器
按順序執行：
1) 錄音
2) ASR 轉錄 -> 產出 output_*.srt
3) 先跑 finalp/finalk/finald（People/Keypoints/Decisions 最終版報告，寫入 cache）
4) 提取行動項目 actions（逐 SRT / 逐段）
5) 生成摘要 Summary（完全使用 cache，不重跑 people/keypoints/decisions/actions）
6) 匯出 PDF（完全使用 cache）
"""

import os
import sys
import time
import signal
import subprocess
import re
import datetime
from pathlib import Path
from typing import List, Dict, Optional
from bluetooth.obex_sender import auto_push, ObexPushError



# --------------------------------------------------
# 將專案根目錄加入 Python 路徑
# --------------------------------------------------
project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


class MeetingWorkflow:
    """會議工作流程控制器"""

    def __init__(
        self,
        audio_device="hw:2,0",
        output_dir=".",
        output_prefix="output",
        model_path="/home/cgu-csie/qwen3-4b-instruct-2507-q8_0.gguf",
        interval_minutes=5,
        overlap_seconds=60,
    ):
        self.audio_device = audio_device
        self.output_dir = output_dir
        self.output_prefix = output_prefix

        self.model_path = model_path
        self.interval_minutes = interval_minutes
        self.overlap_seconds = overlap_seconds

        self.audio_file = os.path.join(output_dir, f"{output_prefix}_audio.mkv")
        self.actions_file = os.path.join(output_dir, f"{output_prefix}_actions.txt")
        self.summary_file = os.path.join(output_dir, f"{output_prefix}_summary.txt")
        self.txt_file = os.path.join(output_dir, f"{output_prefix}_meeting_summary.txt")
        self.dump_cache_in_txt = False   # 交付版：不印 cache；debug 時改 True
        self.bt_enable_push = True

        os.makedirs(output_dir, exist_ok=True)
        self.is_recording = False

        # ✅ cache：避免重跑
        self.cache: Dict[str, object] = {}

    # --------------------------------------------------
    def _print_banner(self, text: str):
        print("\n" + "=" * 60)
        print(f"  {text}")
        print("=" * 60 + "\n")

    def _list_srt_files(self) -> List[Path]:
        pattern = f"{self.output_prefix}_*.srt"
        return sorted(Path(self.output_dir).glob(pattern))

    # ------------------------
    # SRT -> 純文字（給 actions 用）
    # ------------------------
    def _srt_to_text(self, srt_path: str) -> str:
        """
        將 .srt 轉成純文字
        - 忽略序號行、時間戳行
        """
        lines_out = []
        with open(srt_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                if line.isdigit():
                    continue
                if "-->" in line:
                    continue
                lines_out.append(line)
        return "\n".join(lines_out)

    # ------------------------
    # finalp/finalk/finald：共用工具
    # ------------------------
    @staticmethod
    def _clean_thought_tags(text: str) -> str:
        if not text:
            return ""
        text = re.sub(r"<think>[\s\S]*?</think>", "", text)
        if "<think>" in text:
            text = text.split("<think>")[0]
        text = text.replace("</think>", "")

        patterns = [
            r"^好的，.*",
            r"^根據.*",
            r"^Here is.*",
            r"^Sure,.*",
            r"^以下是.*",
            r"^Okay,.*",
        ]
        for p in patterns:
            text = re.sub(p, "", text, flags=re.MULTILINE)

        return text.strip()

    @staticmethod
    def _parse_time_to_seconds(time_str: str) -> Optional[float]:
        time_str = time_str.strip()
        try:
            if ":" in time_str:
                parts = time_str.replace(",", ".").split(":")
                return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
            return float(time_str)
        except Exception:
            return None

    def _parse_srt_brute_force(self, file_path: str) -> List[Dict]:
        """
        解析 SRT：回傳 [{'start': seconds, 'text': '...'}, ...]
        多編碼嘗試（utf-8 / utf-8-sig / cp950 / gbk）
        """
        encodings = ["utf-8", "utf-8-sig", "cp950", "gbk"]
        lines = []
        for enc in encodings:
            try:
                with open(file_path, "r", encoding=enc) as f:
                    lines = f.readlines()
                print(f"🔍 使用編碼 {enc} 讀取成功，共 {len(lines)} 行")
                break
            except UnicodeDecodeError:
                continue
            except Exception:
                continue

        if not lines:
            return []

        all_subtitles = []
        current_start = None
        current_text = []

        for line in lines:
            line = line.strip()

            if "-->" in line:
                if current_start is not None and current_text:
                    all_subtitles.append({"start": current_start, "text": " ".join(current_text)})
                    current_text = []
                try:
                    parts = line.split("-->")
                    t = self._parse_time_to_seconds(parts[0])
                    current_start = t if t is not None else None
                except Exception:
                    current_start = None
                continue

            if line.isdigit():
                continue
            if not line:
                continue

            if current_start is not None:
                current_text.append(line)

        if current_start is not None and current_text:
            all_subtitles.append({"start": current_start, "text": " ".join(current_text)})

        return all_subtitles

    def _split_subtitles_to_segments(self, subtitles: List[Dict]) -> List[str]:
        """
        智慧時間切割 + overlap
        回傳 list[str]，每個元素是：
        【時間段 XX:00 - YY:00】\n內容...
        """
        if not subtitles:
            return []

        subtitles.sort(key=lambda x: x["start"])
        interval_sec = self.interval_minutes * 60

        min_time = subtitles[0]["start"]
        max_time = subtitles[-1]["start"]

        start_chunk_idx = int(min_time // interval_sec)
        end_chunk_idx = int(max_time // interval_sec)

        print(f"⏱️ 偵測 SRT 時間範圍: {int(min_time)}秒 ~ {int(max_time)}秒")
        segments = []

        for i in range(start_chunk_idx, end_chunk_idx + 1):
            chunk_start = i * interval_sec
            chunk_end = (i + 1) * interval_sec + self.overlap_seconds

            current_text_list = []
            for sub in subtitles:
                if chunk_start <= sub["start"] < chunk_end:
                    current_text_list.append(sub["text"])

            if current_text_list:
                label = f"{i*self.interval_minutes:02d}:00 - {(i+1)*self.interval_minutes:02d}:00"
                segments.append(f"【時間段 {label}】\n" + "\n".join(current_text_list))

        return segments

    # ------------------------
    # step1: 錄音
    # ------------------------
    def step1_record(self) -> bool:
        self._print_banner("步驟 1/6: 開始錄音")
        print(f"🎤 音訊設備: {self.audio_device}")
        print(f"📁 輸出檔案: {self.audio_file}")
        print("⌨️  按 Ctrl+C 結束錄音\n")

        arecord_cmd = [
            "arecord",
            "-D", self.audio_device,
            "-f", "S16_LE",
            "-c", "1",
            "-r", "16000",
        ]

        ffmpeg_cmd = [
            "ffmpeg",
            "-y",
            "-f", "s16le",
            "-ar", "16000",
            "-ac", "1",
            "-i", "pipe:0",
            "-c:a", "pcm_s16le",
            "-fflags", "+flush_packets",
            "-flush_packets", "1",
            self.audio_file,
        ]

        arecord_proc = None
        ffmpeg_proc = None
        old_handler = signal.getsignal(signal.SIGINT)
        print(">>> SIGINT handler installed", flush=True)

        def _on_sigint(sig, frame):
            if self.is_recording:
                print("\n\n🛑 正在停止錄音...")
                self.is_recording = False

        try:
            arecord_proc = subprocess.Popen(
                arecord_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )

            ffmpeg_proc = subprocess.Popen(
                ffmpeg_cmd,
                stdin=arecord_proc.stdout,
                stderr=subprocess.DEVNULL,
            )

            self.is_recording = True
            signal.signal(signal.SIGINT, _on_sigint)

            print("✅ 錄音進行中...\n")
            while self.is_recording:
                time.sleep(0.2)

        finally:
            signal.signal(signal.SIGINT, old_handler)

            for p in (arecord_proc, ffmpeg_proc):
                try:
                    if p and p.poll() is None:
                        p.terminate()
                except Exception:
                    pass

            for p in (arecord_proc, ffmpeg_proc):
                try:
                    if p and p.poll() is None:
                        p.wait(timeout=2)
                except Exception:
                    try:
                        p.kill()
                    except Exception:
                        pass

        if os.path.exists(self.audio_file):
            print("✅ 錄音已停止")
            print(f"💾 音訊檔案已儲存: {self.audio_file}\n")
            return True

        print("❌ 找不到錄音輸出檔\n")
        return False

    # ------------------------
    # step2: ASR
    # ------------------------
    def step2_transcribe(self) -> bool:
        self._print_banner("步驟 2/6: 語音轉文字 (ASR)")
        print(f"📂 讀取音訊: {self.audio_file}")
        print("⌨️  按 Ctrl+C 可提前結束轉錄\n")

        if not os.path.exists(self.audio_file):
            print("❌ 音訊檔不存在\n")
            return False

        from speech.pipeline_mkv_read import RealtimeASR

        asr = RealtimeASR(
            audio_file=self.audio_file,
            output_dir=self.output_dir,
            output_prefix=self.output_prefix,
            prototype_alpha=0.0,
            buffer_overlap=5.0,
            verbose=True,
        )

        old_handler = signal.getsignal(signal.SIGINT)

        def _stop_asr(sig, frame):
            print("\n\n🛑 收到中斷信號，正在停止 ASR...")
            asr.stop()

        try:
            signal.signal(signal.SIGINT, _stop_asr)
            asr.start()
        finally:
            signal.signal(signal.SIGINT, old_handler)

        print("✅ ASR 轉錄完成\n")
        return True

    # ------------------------
    # step3: 先跑 finalp/finalk/finald（People/Keypoints/Decisions）
    # ------------------------
    def step3_run_pkd_reports(self) -> bool:
        self._print_banner(
            "步驟 3/6: 先執行 People/Keypoints/Decisions 最終報告 (finalp/finalk/finald)"
        )

        srt_files = self._list_srt_files()
        if not srt_files:
            print("❌ 找不到任何 SRT（請先完成 ASR）\n")
            return False

        if not os.path.exists(self.model_path):
            print(f"❌ 找不到模型: {self.model_path}\n")
            return False

        # 引擎：core1.LlamaCppQwen3Extractor
        from core1 import LlamaCppQwen3Extractor

        try:
            extractor = LlamaCppQwen3Extractor(model_path=self.model_path)
        except Exception as e:
            print(f"❌ 引擎啟動失敗: {e}\n")
            return False

        people_reports = []
        keypoints_reports = []
        decisions_reports = []

        def extract_raw_people(text: str) -> str:
            prompt = f"""<|im_start|>system
你是一個精準的資料提取程式。請從會議記錄片段中識別出現的人物。

規則：
1. **嚴禁**輸出 <think> 思考過程，直接給出結果。
2. 若無人名輸出 "無"。
3. **過濾**：若只有職稱（如部長、主席）沒有名字，請忽略。
4. 格式：- [姓名]：[職位/角色]
<|im_end|>
<|im_start|>user
會議片段：
{text[:3500]}

請列出人物：
<|im_end|>
<|im_start|>assistant
"""
            try:
                out = extractor.model(
                    prompt,
                    max_tokens=600,
                    temperature=0.1,
                    repeat_penalty=1.1,
                    stop=["<|im_end|>", "###"],
                )
                return self._clean_thought_tags(out["choices"][0]["text"])
            except Exception:
                return ""

        def generate_final_people_summary(raw_list: List[str]) -> str:
            clean_list = [self._clean_thought_tags(r) for r in raw_list]
            combined_text = "\n".join(clean_list)
            prompt = f"""<|im_start|>system
你是一位專業秘書。請整理「與會人員名單」。

規則：
1. **去重合併**：整合同一人的資訊。
2. **結構化**：使用 Markdown 條列式。
3. **嚴禁**輸出 `<think>` 標籤。
4. **繁體中文**。

輸出格式：
### [姓名]
- 職位/角色：[說明]

<|im_end|>
<|im_start|>user
原始資料：
{combined_text}

請整理最終名單：
<|im_end|>
<|im_start|>assistant
"""
            try:
                out = extractor.model(
                    prompt,
                    max_tokens=1500,
                    temperature=0.2,
                    repeat_penalty=1.1,
                    stop=["<|im_end|>"],
                )
                return self._clean_thought_tags(out["choices"][0]["text"])
            except Exception:
                return "總結生成失敗"

        def extract_raw_keypoints(text: str) -> str:
            prompt = f"""<|im_start|>system
你是一個專業的會議記錄分析師。請從這段會議記錄中提取「核心要點」。

嚴格規則：
1. **禁止**輸出 <think> 標籤或思考過程。
2. **禁止**輸出任何開場白。
3. 格式：- [關鍵詞]：具體說明
<|im_end|>
<|im_start|>user
會議片段：
{text[:3500]}

請提取重點：
<|im_end|>
<|im_start|>assistant
"""
            try:
                out = extractor.model(
                    prompt,
                    max_tokens=600,
                    temperature=0.1,
                    repeat_penalty=1.1,
                    stop=["<|im_end|>", "###"],
                )
                return self._clean_thought_tags(out["choices"][0]["text"].strip())
            except Exception:
                return ""

        def generate_final_keypoints_summary(raw_list: List[str]) -> str:
            combined_text = "\n".join(raw_list)
            prompt = f"""<|im_start|>system
你是一位專業的會議秘書。以下是從會議各個時間段抓取的「原始重點列表」，包含重複內容。

任務要求：
1. **去重合併**：將重複的重點整合。
2. **結構化**：使用 Markdown 條列式。
3. **絕對禁止**輸出 `<think>` 標籤。
4. **繁體中文**。

輸出格式範例：
### 1. [分類標題]
- **[關鍵詞]**：[說明]

<|im_end|>
<|im_start|>user
原始資料：
{combined_text[:7000]}

請生成最終重點報告：
<|im_end|>
<|im_start|>assistant
"""
            try:
                out = extractor.model(
                    prompt,
                    max_tokens=2000,
                    temperature=0.2,
                    repeat_penalty=1.1,
                    stop=["<|im_end|>"],
                )
                return self._clean_thought_tags(out["choices"][0]["text"].strip())
            except Exception:
                return "總結生成失敗"

        def extract_raw_decisions(text: str) -> str:
            if len(text) < 50:
                return ""
            prompt = f"""<|im_start|>system
你是一個專業的議事紀錄員。請從會議記錄中提取「明確的決策、承諾、共識或關鍵訴求」。

【嚴格規則】：
1. **只提取實質內容**：如「教育部承諾...」、「工會建議...」、「主席裁示...」。
2. **排除廢話**：不要開場白、不要自我介紹、不要議程說明。
3. **若無決策**：請回答「無」。
4. **繁體中文**。

格式：- [主詞]：[決策/承諾內容]
<|im_end|>
<|im_start|>user
會議片段：
{text[:3500]}

請列出重點：
<|im_end|>
<|im_start|>assistant
"""
            try:
                out = extractor.model(
                    prompt,
                    max_tokens=500,
                    temperature=0.1,
                    repeat_penalty=1.1,
                    stop=["<|im_end|>"],
                )
                return self._clean_thought_tags(out["choices"][0]["text"].strip())
            except Exception:
                return ""

        def generate_final_decision_report(raw_list: List[str]) -> str:
            combined_text = "\n".join(raw_list)
            prompt = f"""<|im_start|>system
你是一位政策分析師。請將以下「原始決策列表」整理成一份精簡的決策報告。
務必**去重合併**，並將同一主題的決策歸類在一起。

【輸出格式】：
### 1. 核心決策與承諾
- [重要性高] ...

### 2. 關鍵訴求與建議
- [重要性中] ...

### 3. 後續行動 (Next Steps)
- [待辦事項] ...

(若某類別無內容可省略)
<|im_end|>
<|im_start|>user
原始資料：
{combined_text}

請生成決策報告：
<|im_end|>
<|im_start|>assistant
"""
            try:
                out = extractor.model(
                    prompt,
                    max_tokens=1500,
                    temperature=0.1,
                    stop=["<|im_end|>"],
                )
                return self._clean_thought_tags(out["choices"][0]["text"].strip())
            except Exception:
                return "報告生成失敗"

        # ✅ 逐個 SRT 做 finalp/finalk/finald
        print(f"📄 找到 {len(srt_files)} 個字幕檔案，開始產生 P/K/D 報告...\n")

        for idx, srt in enumerate(srt_files, 1):
            srt_path = str(srt)
            stem = srt.stem  # e.g. output_38
            out_p = os.path.join(self.output_dir, f"finalp_{stem}.md")
            out_k = os.path.join(self.output_dir, f"finalk_{stem}.md")
            out_d = os.path.join(self.output_dir, f"finald_{stem}.md")

            print(f"--- ({idx}/{len(srt_files)}) {srt.name} ---")

            subtitles = self._parse_srt_brute_force(srt_path)
            if not subtitles:
                print("⚠️  字幕讀取失敗，略過\n")
                continue

            segments = self._split_subtitles_to_segments(subtitles)
            if not segments:
                print("⚠️  切割後沒有片段，略過\n")
                continue

            # ---- People ----
            raw_people = []
            for seg in segments:
                r = extract_raw_people(seg)
                if r and len(r) > 3 and "無" not in r and "<think>" not in r:
                    raw_people.append(r)
                if hasattr(extractor, "aggressive_memory_cleanup"):
                    extractor.aggressive_memory_cleanup()

            if raw_people:
                people_final = generate_final_people_summary(raw_people)
            else:
                people_final = (
                    "## 尚無特定人物\n"
                    "系統分析本段會議記錄後，未能識別出具體的人員姓名或職稱。"
                )

            with open(out_p, "w", encoding="utf-8") as f:
                f.write("# 會議參與人員名單\n")
                f.write(f"時間: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                f.write(people_final.strip() + "\n")
                f.write("\n\n---\n## 原始提取紀錄 (備份)\n\n")
                f.write("\n\n".join(raw_people))

            # ---- Keypoints ----
            raw_kps = []
            for seg in segments:
                label = seg.split("\n")[0].strip()
                r = extract_raw_keypoints(seg)
                if r and len(r) > 5 and "無" not in r:
                    raw_kps.append(f"{label}\n{r}")
                if hasattr(extractor, "aggressive_memory_cleanup"):
                    extractor.aggressive_memory_cleanup()

            if raw_kps:
                k_final = generate_final_keypoints_summary(raw_kps)
            else:
                k_final = (
                    "## 尚無明確重點\n"
                    "系統分析本段會議記錄後，未發現具體的討論重點或結論。"
                )

            with open(out_k, "w", encoding="utf-8") as f:
                f.write("# 會議核心重點總結\n")
                f.write(f"分析時間: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                f.write(k_final.strip() + "\n")
                f.write("\n\n---\n## 原始提取紀錄\n\n")
                f.write("\n\n".join(raw_kps))

            # ---- Decisions ----
            raw_ds = []
            for seg in segments:
                r = extract_raw_decisions(seg)
                if r and "無" not in r and len(r) > 5:
                    raw_ds.append(r)
                if hasattr(extractor, "aggressive_memory_cleanup"):
                    extractor.aggressive_memory_cleanup()

            if raw_ds:
                d_final = generate_final_decision_report(raw_ds)
            else:
                d_final = (
                    "## 尚無明確決策\n"
                    "系統分析本段會議記錄後，未發現明確的承諾、決議或共識。"
                )

            with open(out_d, "w", encoding="utf-8") as f:
                f.write("# 會議決策重點報告\n")
                f.write(f"時間: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                f.write(d_final.strip() + "\n")
                f.write("\n\n---\n## 原始提取紀錄 (備份)\n\n")
                f.write("\n\n".join(raw_ds))

            print(f"✅ People  輸出: {out_p}")
            print(f"✅ Keypts  輸出: {out_k}")
            print(f"✅ Decisn  輸出: {out_d}\n")

            # ✅ 給 summary/pdf 用：把「最終」版本存進 cache（可跨多個 srt 合併）
            people_reports.append(people_final.strip())
            keypoints_reports.append(k_final.strip())
            decisions_reports.append(d_final.strip())

        # ✅ 寫入 cache（全會議合併）
        self.cache["people"] = "\n\n".join(people_reports).strip()
        self.cache["keypoints"] = "\n\n".join(keypoints_reports).strip()
        self.cache["decisions"] = "\n\n".join(decisions_reports).strip()

        # 如果全部都空，也要給預設值避免後面空字串
        if not self.cache["people"]:
            self.cache["people"] = "（無）"
        if not self.cache["keypoints"]:
            self.cache["keypoints"] = "（無）"
        if not self.cache["decisions"]:
            self.cache["decisions"] = "（無）"

        print("✅ step3 完成：P/K/D 已寫入 cache（後面不再重跑）")
        print(f"DEBUG cache keys = {list(self.cache.keys())}\n")
        return True

    # ------------------------
    # step4: actions（逐段提取）
    # ------------------------
    def step4_extract_actions(self) -> bool:
        self._print_banner("步驟 4/6: 提取行動項目（逐 SRT / 逐段 extract）")

        from extractors.actions_extractor import ActionsExtractor

        srt_files = self._list_srt_files()
        if not srt_files:
            print("❌ 找不到任何 SRT\n")
            return False

        print(f"📄 找到 {len(srt_files)} 個字幕檔案")

        extractor = ActionsExtractor()

        # ✅ segments（逐段），供後面 summary 使用
        segments_all = []
        all_actions = []

        for idx, srt in enumerate(srt_files, 1):
            srt_path = str(srt)
            text = self._srt_to_text(srt_path).strip()

            if not text:
                print(f"⚠️  ({idx}/{len(srt_files)}) {srt.name} 字幕為空，略過")
                continue

            segment = {"text": text}
            segments_all.append(segment)

            try:
                result = extractor.extract([segment])
            except Exception as e:
                print(f"❌  ({idx}/{len(srt_files)}) {srt.name} 提取失敗: {e}")
                continue

            if not result or result.strip() == "本段無具體行動項目":
                print(f"ℹ️  ({idx}/{len(srt_files)}) {srt.name}: 本段無具體行動項目")
                continue

            lines = [ln.strip() for ln in result.splitlines() if ln.strip()]
            if not lines:
                print(f"ℹ️  ({idx}/{len(srt_files)}) {srt.name}: 無有效輸出行")
                continue

            print(f"✅ ({idx}/{len(srt_files)}) {srt.name}: 擷取 {len(lines)} 條")
            all_actions.extend(lines)

        # 去重（保持順序）
        deduped = []
        seen = set()
        for a in all_actions:
            key = a
            if key in seen:
                continue
            seen.add(key)
            deduped.append(a)

        with open(self.actions_file, "w", encoding="utf-8") as f:
            f.write("會議行動項目清單（逐段提取）\n")
            f.write("=" * 60 + "\n\n")

            if deduped:
                for i, line in enumerate(deduped, 1):
                    f.write(f"{i}. {line}\n")
                    print(f"✅ {i}. {line}")
            else:
                f.write("本次會議無具體行動項目\n")
                print("ℹ️  本次會議無具體行動項目")

        print(f"\n💾 行動項目已輸出: {self.actions_file}\n")

        # ✅ 寫入 cache（summary/pdf 會直接用）
        self.cache["segments"] = segments_all
        self.cache["actions_lines"] = deduped
        self.cache["actions_text"] = "\n".join(deduped) if deduped else "本段無具體行動項目"

        print(f"DEBUG cache keys = {list(self.cache.keys())}")
        print(
            f"DEBUG segments={len(self.cache.get('segments', []))}, "
            f"actions_lines={len(self.cache.get('actions_lines', []))}\n"
        )
        return True

    # ------------------------
    # step4.5: 印出 cache 快照（actions 結束後、summary 開始前）
    # ------------------------
    def step4_5_print_cache(self) -> bool:
        self._print_banner("步驟 4.5/6: Cache 快照（Actions 後 / Summary 前）")

        keys = [
            "people",
            "keypoints",
            "decisions",
            "segments",
            "actions_text",
            "actions_lines",
            "summary",
        ]

        print(f"📦 cache keys = {list(self.cache.keys())}\n")

        def _preview_text(name: str, text: str, max_chars: int = 500):
            text = (text or "").strip()
            if not text:
                print(f"— {name}: （空）\n")
                return
            show = text if len(text) <= max_chars else text[:max_chars] + "\n...（截斷）"
            print(f"— {name}（len={len(text)}）:\n{show}\n")

        def _preview_list(name: str, items, max_items: int = 10):
            if not items:
                print(f"— {name}: （空）\n")
                return
            print(f"— {name}（count={len(items)}）:")
            for i, it in enumerate(items[:max_items], 1):
                s = str(it)
                if len(s) > 300:
                    s = s[:300] + "...（截斷）"
                print(f"  {i}. {s}")
            if len(items) > max_items:
                print(f"  ...（其餘 {len(items) - max_items} 筆略）")
            print("")

        for k in keys:
            if k not in self.cache:
                continue

            v = self.cache.get(k)

            if k == "segments":
                segs = v if isinstance(v, list) else []
                print(f"— segments（count={len(segs)}）:")
                for i, seg in enumerate(segs[:5], 1):
                    txt = (seg.get("text", "") if isinstance(seg, dict) else str(seg)).strip()
                    txt = txt[:300] + ("...（截斷）" if len(txt) > 300 else "")
                    print(f"  {i}. {txt}")
                if len(segs) > 5:
                    print(f"  ...（其餘 {len(segs) - 5} 段略）")
                print("")
                continue

            if k == "actions_lines":
                _preview_list("actions_lines", v, max_items=20)
                continue

            if isinstance(v, str):
                _preview_text(k, v, max_chars=800)
            else:
                print(f"— {k}: {type(v).__name__} = {v}\n")

        print("✅ Cache 快照輸出完成\n")
        return True

    # ------------------------
    # step5: summary（完全使用 cache）
    # ------------------------
    def step5_generate_summary(self) -> bool:
        self._print_banner("步驟 5/6: 生成會議整體摘要 (Summary, cached)")

        from extractors.summary_generator import SummaryGenerator

        segments = self.cache.get("segments", [])

        # ✅ P/K/D 在 step3 已經跑完寫進 cache
        people = self.cache.get("people", "（無）")
        keypoints = self.cache.get("keypoints", "（無）")
        decisions = self.cache.get("decisions", "（無）")
        actions = self.cache.get("actions_text", "（無）")

        print("📝 生成整體摘要 ...（SummaryGenerator）")
        summary = SummaryGenerator().generate(
            segments=segments,
            people=people,
            keypoints=keypoints,
            decisions=decisions,
            actions=actions,
        )

        self.cache["summary"] = (summary or "").strip()

        with open(self.summary_file, "w", encoding="utf-8") as f:
            f.write(self.cache["summary"] + "\n")

        print(f"\n💾 摘要已輸出: {self.summary_file}\n")
        return True

    # ------------------------
    # step6: PDF（完全使用 cache）
    # ------------------------
    def step6_export_txt(self) -> bool:
        """步驟 6：匯出 TXT（使用 cache；完整 dump；適合 debug / 交付純文字）"""
        self._print_banner("步驟 6/6: 匯出 TXT（使用 cache）")

        import pprint

        if not isinstance(self.cache, dict):
            print("❌ cache 不存在或格式錯誤")
            return False

        def _write_section(f, title: str, content: str):
            f.write(f"\n{title}\n")
            f.write("=" * 60 + "\n")
            content = "" if content is None else str(content)
            content = content.strip()
            f.write(content if content else "（無）")
            f.write("\n")

        def _write_list(f, title: str, items):
            f.write(f"\n{title}\n")
            f.write("=" * 60 + "\n")
            if not items:
                f.write("（空）\n")
                return
            for i, it in enumerate(items, 1):
                f.write(f"{i}. {it}\n")
        def _write_cache_full_dump(f):
            f.write("\nCache 快照（Full Dump）\n")
            f.write("=" * 60 + "\n")

            keys = list(self.cache.keys())
            f.write(f"cache keys = {keys}\n\n")

            for k in sorted(keys):
                v = self.cache.get(k)
                f.write(f"— {k} (type={type(v).__name__})\n")

                # segments: 逐段印出
                if k == "segments" and isinstance(v, list):
                    f.write(f"segments count = {len(v)}\n")
                    if len(v) == 0:
                        f.write("（空）\n\n")
                    else:
                        for idx, seg in enumerate(v, 1):
                            if isinstance(seg, dict):
                                speaker = seg.get("speaker")
                                text = seg.get("text", "")
                                header = f"[{idx}] speaker={speaker}\n" if speaker else f"[{idx}]\n"
                                f.write(header)
                                f.write((text or "").rstrip() + "\n\n")
                            else:
                                f.write(f"[{idx}] {str(seg)}\n\n")
                    continue

                # actions_lines: 逐行印出
                if k == "actions_lines" and isinstance(v, list):
                    f.write(f"actions_lines count = {len(v)}\n")
                    if len(v) == 0:
                        f.write("（空）\n\n")
                    else:
                        for i, line in enumerate(v, 1):
                            f.write(f"{i}. {line}\n")
                        f.write("\n")
                    continue

                # 字串：完整印
                if isinstance(v, str):
                    f.write((v.strip() if v.strip() else "（空）") + "\n\n")
                    continue

                # 其他型別：pprint 完整展開
                if v is None:
                    f.write("（空）\n\n")
                    continue

                f.write(pprint.pformat(v, width=120, compact=False))
                f.write("\n\n")

        try:
            with open(self.txt_file, "w", encoding="utf-8") as f:
                f.write("會議摘要報告（TXT）\n")
                f.write("=" * 60 + "\n")
                f.write(f"產生時間: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

                # 正式章節（跟你 PDF 一樣的結構）
                _write_section(f, "整體摘要（Summary）", self.cache.get("summary", ""))
                _write_section(f, "與會人員（People）", self.cache.get("people", ""))
                _write_section(f, "會議重點（Keypoints）", self.cache.get("keypoints", ""))
                _write_section(f, "決策事項（Decisions）", self.cache.get("decisions", ""))
                _write_list(f, "行動項目（Actions）", self.cache.get("actions_lines", []))

                # 你要的：完整 cache dump（就算都是空也印）
                if getattr(self, "dump_cache_in_txt", False):
                    _write_cache_full_dump(f)
                
        except Exception as e:
            print(f"❌ TXT 產生失敗: {e}")
            return False

        print(f"📄 TXT 已輸出: {self.txt_file}\n")
        # =========================
        # ★ Bluetooth 傳送結果檔案
        # =========================
        if self.bt_enable_push:
            print("🔵 BT: ready to push files...")
            try:
                files_to_send = [
                    self.txt_file,
                    self.actions_file,
                    self.summary_file,
                ]

                mac, name = auto_push(files_to_send)
                print(f"✅ Bluetooth: files pushed to {name} ({mac})")

            except ObexPushError as e:
                print(f"⚠️ Bluetooth push failed: {e}")
            except Exception as e:
                print(f"❌ Bluetooth unexpected error: {type(e).__name__}: {e}", flush=True)

        return True

    # ------------------------
    # run
    # ------------------------
    def run(self) -> bool:
        self._print_banner("🎯 會議工作流程控制器")

        if not self.step1_record():
            return False
        if not self.step2_transcribe():
            return False

        # ✅ 你要的：finald/p/k 在 actions 之前
        if not self.step3_run_pkd_reports():
            return False
        if not self.step4_extract_actions():
            return False
        if not self.step4_5_print_cache():
            return False
        if not self.step5_generate_summary():
            return False
        if not self.step6_export_txt():
            return False

        self._print_banner("✅ 工作流程完成")
        print("🎉 全流程結束\n")
        return True


def main():
    workflow = MeetingWorkflow(
        audio_device="hw:2,0",
        output_dir=".",
        output_prefix="output",
        model_path="/home/cgu-csie/qwen3-4b-instruct-2507-q8_0.gguf",
        interval_minutes=5,
        overlap_seconds=60,
    )
    sys.exit(0 if workflow.run() else 1)


if __name__ == "__main__":
    main()
