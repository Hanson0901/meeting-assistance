#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
會議流程控制器
按順序執行：錄音 → ASR 轉錄 → 提取行動項目（逐 SRT / 逐段）→ 生成摘要（使用 cache，不重跑 actions）
"""

import os
import sys
import time
import signal
import subprocess
from pathlib import Path


# 將專案根目錄加入 Python 路徑
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
    ):
        self.audio_device = audio_device
        self.output_dir = output_dir
        self.output_prefix = output_prefix

        self.audio_file = os.path.join(output_dir, f"{output_prefix}_audio.mkv")
        self.actions_file = os.path.join(output_dir, f"{output_prefix}_actions.txt")
        self.summary_file = os.path.join(output_dir, f"{output_prefix}_summary.txt")

        os.makedirs(output_dir, exist_ok=True)
        self.is_recording = False

        # ✅ cache：避免 summary 重跑 extractor
        self.cache = {}

    # --------------------------------------------------
    def _print_banner(self, text: str):
        print("\n" + "=" * 60)
        print(f"  {text}")
        print("=" * 60 + "\n")
        
    def _srt_to_text(self, srt_path: str) -> str:
        """
        將 .srt 轉成純文字（不依賴 ActionsExtractor）
        - 會忽略序號行、時間戳行
        - 保留字幕文字內容
        """
        lines_out = []
        with open(srt_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                # 序號行（純數字）
                if line.isdigit():
                    continue
                # 時間戳行（包含 -->）
                if "-->" in line:
                    continue
                lines_out.append(line)
        return "\n".join(lines_out)

    # --------------------------------------------------
    def step1_record(self) -> bool:
        """步驟 1：錄音（Ctrl+C 可正常停止）"""
        self._print_banner("步驟 1/4: 開始錄音")
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

    # --------------------------------------------------
    def step2_transcribe(self) -> bool:
        """步驟 2：ASR 轉錄"""
        self._print_banner("步驟 2/4: 語音轉文字 (ASR)")
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

    # --------------------------------------------------
    def step3_extract_actions(self) -> bool:
        """步驟 3：逐 SRT / 逐段提取行動項目（每個 output_*.srt 各跑一次 extract）"""
        self._print_banner("步驟 3/4: 提取行動項目（逐 SRT / 逐段 extract）")

        from extractors.actions_extractor import ActionsExtractor

        pattern = f"{self.output_prefix}_*.srt"
        srt_files = sorted(Path(self.output_dir).glob(pattern))

        if not srt_files:
            print("❌ 找不到任何 SRT\n")
            return False

        print(f"📄 找到 {len(srt_files)} 個字幕檔案")

        extractor = ActionsExtractor()

        # ✅ 同時準備 segments（逐段），供後面 summary 使用
        segments_all = []

        # 收集所有段落提取結果（先不去重）
        all_actions = []

        for idx, srt in enumerate(srt_files, 1):
            srt_path = str(srt)
            text = self._srt_to_text(srt_path).strip()


            if not text:
                print(f"⚠️  ({idx}/{len(srt_files)}) {srt.name} 字幕為空，略過")
                continue

            # 逐段：一個 srt 當作一個 segment
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

        # ---- 去重（保持順序）----
        deduped = []
        seen = set()
        for a in all_actions:
            key = a  # 需要更強去重可改：key = " ".join(a.split()).lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(a)

        # ---- 輸出 actions 檔案 ----
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

        # ✅ 寫入 cache（summary 會直接用，不再重跑 actions）
        self.cache["segments"] = segments_all
        self.cache["actions_lines"] = deduped
        self.cache["actions_text"] = "\n".join(deduped) if deduped else "本段無具體行動項目"

        print(f"DEBUG cache keys = {list(self.cache.keys())}")
        print(f"DEBUG segments={len(self.cache.get('segments', []))}, actions_lines={len(self.cache.get('actions_lines', []))}")

        return True

    # --------------------------------------------------
    def step4_generate_summary(self) -> bool:
        """步驟 4：生成整體摘要（使用 cache，不重跑 actions；people/keypoints/decisions 只跑一次後也 cache）"""
        self._print_banner("步驟 4/4: 生成會議整體摘要 (Summary, cached)")

        from extractors.people_extractor import PeopleExtractor
        from extractors.keypoints_extractor import KeypointsExtractor
        from extractors.decisions_extractor import DecisionsExtractor
        from extractors.summary_generator import SummaryGenerator

        segments = self.cache.get("segments", [])
        actions = self.cache.get("actions_text", "")

        if not segments:
            print("❌ cache 中沒有 segments（請先執行 step3_extract_actions）\n")
            return False

        # ✅ people/keypoints/decisions：如果 cache 沒有才跑一次
        if "people" not in self.cache:
            print("👤 提取 People ...（一次性，寫入 cache）")
            self.cache["people"] = PeopleExtractor().extract(segments)

        if "keypoints" not in self.cache:
            print("🧩 提取 Keypoints ...（一次性，寫入 cache）")
            self.cache["keypoints"] = KeypointsExtractor().extract(segments)

        if "decisions" not in self.cache:
            print("📌 提取 Decisions ...（一次性，寫入 cache）")
            self.cache["decisions"] = DecisionsExtractor().extract(segments)

        people = self.cache.get("people", "")
        keypoints = self.cache.get("keypoints", "")
        decisions = self.cache.get("decisions", "")

        print("📝 生成整體摘要 ...（SummaryGenerator）")
        summary = SummaryGenerator().generate(
            segments=segments,
            people=people,
            keypoints=keypoints,
            decisions=decisions,
            actions=actions,
        )

        with open(self.summary_file, "w", encoding="utf-8") as f:
            f.write(summary.strip() + "\n")

        print(f"\n💾 摘要已輸出: {self.summary_file}\n")
        return True
        # --------------------------------------------------
    def step5_export_pdf(self) -> bool:
        """步驟 5：將 cache 內容輸出為 PDF（不重跑任何 extractor）"""
        self._print_banner("步驟 5/5: 匯出 PDF（使用 cache）")

        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem
        from reportlab.lib.units import cm

        pdf_path = os.path.join(self.output_dir, f"{self.output_prefix}_meeting_summary.pdf")

        # ---- 檢查 cache ----
        required_keys = ["people", "keypoints", "decisions", "actions_lines"]
        for k in required_keys:
            if k not in self.cache:
                print(f"❌ cache 中缺少 {k}，請先完成 step4")
                return False

        # ---- 建立 PDF ----
        doc = SimpleDocTemplate(
            pdf_path,
            pagesize=A4,
            rightMargin=2 * cm,
            leftMargin=2 * cm,
            topMargin=2 * cm,
            bottomMargin=2 * cm,
        )

        styles = getSampleStyleSheet()
        story = []

        def add_title(text):
            story.append(Paragraph(f"<b>{text}</b>", styles["Title"]))
            story.append(Spacer(1, 12))

        def add_section(title, content):
            story.append(Paragraph(f"<b>{title}</b>", styles["Heading2"]))
            story.append(Spacer(1, 8))

            if not content or not content.strip():
                story.append(Paragraph("（無）", styles["Normal"]))
            else:
                for line in content.splitlines():
                    story.append(Paragraph(line, styles["Normal"]))

            story.append(Spacer(1, 14))

        def add_list_section(title, items):
            story.append(Paragraph(f"<b>{title}</b>", styles["Heading2"]))
            story.append(Spacer(1, 8))

            if not items:
                story.append(Paragraph("（無）", styles["Normal"]))
            else:
                lf = ListFlowable(
                    [
                        ListItem(Paragraph(item, styles["Normal"]))
                        for item in items
                    ],
                    bulletType="1",
                )
                story.append(lf)

            story.append(Spacer(1, 14))

        # ---- 寫入內容 ----
        add_title("會議摘要報告")

        add_section("👤 與會人員（People）", self.cache.get("people", ""))
        add_section("🧩 會議重點（Keypoints）", self.cache.get("keypoints", ""))
        add_section("📌 決策事項（Decisions）", self.cache.get("decisions", ""))
        add_list_section("✅ 行動項目（Actions）", self.cache.get("actions_lines", []))

        # （可選）如果你之後想把逐段原文也輸出
        # add_section(
        #     "📄 逐段逐字稿",
        #     "\n\n".join(seg["text"] for seg in self.cache.get("segments", []))
        # )

        # ---- 產生 PDF ----
        doc.build(story)

        print(f"📄 PDF 已輸出: {pdf_path}\n")
        return True

    # --------------------------------------------------
    def run(self) -> bool:
        self._print_banner("🎯 會議工作流程控制器")

        if not self.step1_record():
            return False
        if not self.step2_transcribe():
            return False
        if not self.step3_extract_actions():
            return False
        if not self.step4_generate_summary():
            return False
        if not self.step5_export_pdf():
            return False

        self._print_banner("✅ 工作流程完成")
        print("🎉 全流程結束\n")
        return True


def main():
    workflow = MeetingWorkflow(
        audio_device="hw:2,0",
        output_dir=".",
        output_prefix="output",
    )
    sys.exit(0 if workflow.run() else 1)


if __name__ == "__main__":
    main()
