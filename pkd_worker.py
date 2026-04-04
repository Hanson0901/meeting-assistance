#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import time
import datetime
from pathlib import Path
from typing import List, Dict, Optional

# 乾淨版的工具函數（從 MeetingWorkflow 複製必要的）
def clean_thought_tags(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<think>[\s\S]*?</think>", "", text)
    if "<think>" in text:
        text = text.split("<think>")[0]
    text = text.replace("</think>", "")

    patterns = [
        r"^好的.*",
        r"^根據.*",
        r"^Here is.*",
        r"^Sure,.*",
        r"^以下是.*",
        r"^Okay,.*",
    ]
    for p in patterns:
        text = re.sub(p, "", text, flags=re.MULTILINE)

    return text.strip()

def parse_time_to_seconds(time_str: str) -> Optional[float]:
    time_str = time_str.strip()
    try:
        if ":" in time_str:
            parts = time_str.replace(",", ".").split(":")
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        return float(time_str)
    except Exception:
        return None

def parse_srt_brute_force(file_path: str) -> List[Dict]:
    encodings = ["utf-8", "utf-8-sig", "cp950", "gbk"]
    lines = []
    for enc in encodings:
        try:
            with open(file_path, "r", encoding=enc) as f:
                lines = f.readlines()
            break
        except:
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
                t = parse_time_to_seconds(parts[0])
                current_start = t if t is not None else None
            except:
                current_start = None
            continue

        if line.isdigit() or not line:
            continue

        if current_start is not None:
            current_text.append(line)

    if current_start is not None and current_text:
        all_subtitles.append({"start": current_start, "text": " ".join(current_text)})

    return all_subtitles

def split_subtitles_to_segments(subtitles: List[Dict], interval_minutes: int, overlap_seconds: int) -> List[str]:
    if not subtitles:
        return []

    subtitles.sort(key=lambda x: x["start"])
    interval_sec = interval_minutes * 60

    min_time = subtitles[0]["start"]
    max_time = subtitles[-1]["start"]

    start_chunk_idx = int(min_time // interval_sec)
    end_chunk_idx = int(max_time // interval_sec)

    segments = []
    for i in range(start_chunk_idx, end_chunk_idx + 1):
        chunk_start = i * interval_sec
        chunk_end = (i + 1) * interval_sec + overlap_seconds

        current_text_list = []
        for sub in subtitles:
            if chunk_start <= sub["start"] < chunk_end:
                current_text_list.append(sub["text"])

        if current_text_list:
            label = f"{i*interval_minutes:02d}:00 - {(i+1)*interval_minutes:02d}:00"
            segments.append(f"【時間段 {label}】\n" + "\n".join(current_text_list))

    return segments


# ===== 你的 LLM extract 函數（原樣搬過來，只把 MeetingWorkflow._clean_thought_tags 換成 clean_thought_tags） =====
def extract_raw_people(extractor, text: str) -> str:
    prompt = f"""<|im_start|>system
你是一個精準的資料提取程式。請從會議記錄片段中識別出現的人物。
要則:
1. **嚴禁**輸出 <think> 思考過程,直接給出結果。
2. 若無人名輸出 "無"。
3. **過濾**:若只有職稱(如部長、主席)沒有名字,請忽略。
4. 格式:- [姓名]:[職位/角色]
<|im_end|>
<|im_start|>user
會議片段:
{text[:3500]}

請列出人物:
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
        return clean_thought_tags(out["choices"][0]["text"])
    except Exception:
        return ""

def generate_final_people_summary(extractor, raw_list: List[str]) -> str:
    clean_list = [clean_thought_tags(r) for r in raw_list]
    combined_text = "\n".join(clean_list)
    prompt = f"""<|im_start|>system
你是一位專業秘書。請整理「與會人員名單」。
要則:
1. **去重合併**:整合同一人的資訊。
2. **結構化**:使用 Markdown 條列式。
3. **嚴禁**輸出 `<think>` 標籤。
4. **繁體中文**。
輸出格式:
### [姓名]
- 職位/角色:[說明]
<|im_end|>
<|im_start|>user
原始資料:
{combined_text}

請整理最終名單:
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
        return clean_thought_tags(out["choices"][0]["text"])
    except Exception:
        return "總結生成失敗"

def extract_raw_keypoints(extractor, text: str) -> str:
    prompt = f"""<|im_start|>system
你是一個專業的會議記錄分析師。請從這段會議記錄中提取「核心要點」。
嚴格要則:
1. **禁止**輸出 <think> 標籤或思考過程。
2. **禁止**輸出任何開場白。
3. 格式:- [關鍵詞]:具體說明
<|im_end|>
<|im_start|>user
會議片段:
{text[:3500]}

請提取重點:
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
        return clean_thought_tags(out["choices"][0]["text"].strip())
    except Exception:
        return ""

def generate_final_keypoints_summary(extractor, raw_list: List[str]) -> str:
    combined_text = "\n".join(raw_list)
    prompt = f"""<|im_start|>system
你是一位專業的會議秘書。以下是從會議各個時間段抓取的「原始重點列表」,包含重複內容。
任務要求:
1. **去重合併**:將重複的重點整合。
2. **結構化**:使用 Markdown 條列式。
3. **絕對禁止**輸出 `<think>` 標籤。
4. **繁體中文**。
輸出格式範例:
### 1. [分類標題]
- **[關鍵詞]**:[說明]
<|im_end|>
<|im_start|>user
原始資料:
{combined_text[:7000]}

請生成最終重點報告:
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
        return clean_thought_tags(out["choices"][0]["text"].strip())
    except Exception:
        return "總結生成失敗"

def extract_raw_decisions(extractor, text: str) -> str:
    if len(text) < 50:
        return ""
    prompt = f"""<|im_start|>system
你是一個專業的議事紀錄員。請從會議記錄中提取「明確的決策、承諾、共識或關鍵訴求」。
【嚴格要則】:
1. **只提取實質內容**:如「教育部承諾...」、「工會建議...」、「主席裁示...」。
2. **排除廢話**:不要開場白、不要自我介紹、不要議程說明。
3. **若無決策**:請回答「無」。
4. **繁體中文**。
格式:- [主詞]:[決策/承諾內容]
<|im_end|>
<|im_start|>user
會議片段:
{text[:3500]}

請列出重點:
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
        return clean_thought_tags(out["choices"][0]["text"].strip())
    except Exception:
        return ""

def generate_final_decision_report(extractor, raw_list: List[str]) -> str:
    combined_text = "\n".join(raw_list)
    prompt = f"""<|im_start|>system
你是一位政策分析師。請將以下「原始決策列表」整理成一份精簡的決策報告。
務必**去重合併**,並將同一主題的決策歸類在一起。
【輸出格式】:
### 1. 核心決策與承諾
- [重要性高] ...
### 2. 關鍵訴求與建議
- [重要性中] ...
### 3. 後續行動 (Next Steps)
- [待辦事項] ...
(若某類別無內容可省略)
<|im_end|>
<|im_start|>user
原始資料:
{combined_text}

請生成決策報告:
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
        return clean_thought_tags(out["choices"][0]["text"].strip())
    except Exception:
        return "報告生成失敗"


def list_srt_files(output_dir: str, output_prefix: str) -> List[Path]:
    pattern = f"{output_prefix}_*.srt"
    return sorted(Path(output_dir).glob(pattern))


def run_pkd(output_dir: str, output_prefix: str, model_path: str, interval_minutes: int, overlap_seconds: int) -> Dict[str, str]:
    total_start = time.time()
    
    srt_files = list_srt_files(output_dir, output_prefix)
    if not srt_files:
        raise RuntimeError("找不到任何 SRT")

    if not os.path.exists(model_path):
        raise RuntimeError(f"找不到模型: {model_path}")

    print("[PKD] 正在導入模型...")
    model_load_start = time.time()
    from core1 import LlamaCppQwen3Extractor
    extractor = LlamaCppQwen3Extractor(model_path=model_path)
    model_load_time = time.time() - model_load_start
    print(f"[PKD] 模型導入完成 (耗時: {model_load_time:.2f} 秒)\n")

    # 初始化統計變數
    people_time = 0.0
    keypoints_time = 0.0
    decisions_time = 0.0
    
    people_reports = []
    keypoints_reports = []
    decisions_reports = []

    for srt in srt_files:
        srt_path = str(srt)
        stem = srt.stem
        
        subtitles = parse_srt_brute_force(srt_path)
        if not subtitles: continue
        segments = split_subtitles_to_segments(subtitles, interval_minutes, overlap_seconds)
        if not segments: continue

        # --- PEOPLE 任務 ---
        t_start = time.time()
        raw_people = []
        for seg in segments:
            r = extract_raw_people(extractor, seg)
            if r and len(r) > 3 and "無" not in r:
                raw_people.append(r)
        
        people_final = generate_final_people_summary(extractor, raw_people) if raw_people else "## 尚無特定人物"
        people_time += (time.time() - t_start)
        
        # 寫入檔案 (略過寫入代碼以保持簡潔，邏輯同原版)
        with open(os.path.join(output_dir, f"finalp_{stem}.md"), "w", encoding="utf-8") as f:
            f.write(f"# 會議參與人員名單\n{people_final}")

        # --- KEYPOINTS 任務 ---
        t_start = time.time()
        raw_kps = []
        for seg in segments:
            label = seg.split("\n")[0].strip()
            r = extract_raw_keypoints(extractor, seg)
            if r and len(r) > 5 and "無" not in r:
                raw_kps.append(f"{label}\n{r}")
        
        k_final = generate_final_keypoints_summary(extractor, raw_kps) if raw_kps else "## 尚無明確重點"
        keypoints_time += (time.time() - t_start)
        
        with open(os.path.join(output_dir, f"finalk_{stem}.md"), "w", encoding="utf-8") as f:
            f.write(f"# 會議核心重點總結\n{k_final}")

        # --- DECISIONS 任務 ---
        t_start = time.time()
        raw_ds = []
        for seg in segments:
            r = extract_raw_decisions(extractor, seg)
            if r and "無" not in r and len(r) > 5:
                raw_ds.append(r)
        
        d_final = generate_final_decision_report(extractor, raw_ds) if raw_ds else "## 尚無明確決策"
        decisions_time += (time.time() - t_start)
        
        with open(os.path.join(output_dir, f"finald_{stem}.md"), "w", encoding="utf-8") as f:
            f.write(f"# 會議決策重點報告\n{d_final}")

        # 每處理完一個檔案清理一次記憶體，兼顧效能與穩定
        if hasattr(extractor, "aggressive_memory_cleanup"):
            extractor.aggressive_memory_cleanup()

        people_reports.append(people_final.strip())
        keypoints_reports.append(k_final.strip())
        decisions_reports.append(d_final.strip())

    total_time = time.time() - total_start

    print("\n⏱️  PKD 任務詳細統計")
    print("=" * 60)
    print(f" 1. 模型導入時間 : {model_load_time:>8.2f} 秒")
    print(f" 2. People 任務  : {people_time:>8.2f} 秒")
    print(f" 3. Keypoints 任務: {keypoints_time:>8.2f} 秒")
    print(f" 4. Decisions 任務: {decisions_time:>8.2f} 秒")
    print("-" * 60)
    print(f" 總執行耗時      : {total_time:>8.2f} 秒")
    print("=" * 60 + "\n")

    return {
        "people": "\n\n".join(people_reports),
        "keypoints": "\n\n".join(keypoints_reports),
        "decisions": "\n\n".join(decisions_reports),
    }