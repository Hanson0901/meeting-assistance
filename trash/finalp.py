from core1 import LlamaCppQwen3Extractor
import os
import datetime
import re

MODEL_PATH = "Qwen3-4B-Q8_0.gguf"
SRT_FILE = "output_38.srt"
OUTPUT_FILE = "finalp_38.md"

INTERVAL_MINUTES = 5
OVERLAP_SECONDS = 60

def clean_thought_tags(text):
    """
    【強力清洗版】徹底移除思考過程與廢話
    """
    if not text: return ""

    text = re.sub(r'<think>[\s\S]*?</think>', '', text)
    
    if '<think>' in text:
        text = text.split('<think>')[0]
        
    text = text.replace('</think>', '')
    
    patterns = [
        r"^好的，.*", 
        r"^根據.*", 
        r"^Here is.*", 
        r"^Sure,.*",
        r"^以下是.*",
        r"^Okay,.*"
    ]
    for p in patterns:
        text = re.sub(p, "", text, flags=re.MULTILINE)

    return text.strip()

def parse_time_to_seconds(time_str):
    time_str = time_str.strip()
    try:
        if ":" in time_str:
            parts = time_str.replace(',', '.').split(':')
            return float(parts[0])*3600 + float(parts[1])*60 + float(parts[2])
        else:
            return float(time_str)
    except:
        return None

def parse_srt_brute_force(file_path):
    all_subtitles = []
    encodings = ['utf-8', 'utf-8-sig', 'cp950', 'gbk']
    lines = []
    
    for enc in encodings:
        try:
            with open(file_path, 'r', encoding=enc) as f:
                lines = f.readlines()
            print(f"🔍 使用編碼 {enc} 讀取成功，共 {len(lines)} 行")
            break
        except UnicodeDecodeError:
            continue
            
    if not lines: return []

    current_start = None
    current_text = []
    
    for line in lines:
        line = line.strip()
        if "-->" in line:
            if current_start is not None and current_text:
                full_text = " ".join(current_text)
                all_subtitles.append({'start': current_start, 'text': full_text})
                current_text = []
            try:
                parts = line.split('-->')
                t = parse_time_to_seconds(parts[0])
                current_start = t if t is not None else None
            except:
                current_start = None
            continue

        if line.isdigit(): continue
        if not line: continue
            
        if current_start is not None:
            current_text.append(line)

    if current_start is not None and current_text:
        all_subtitles.append({'start': current_start, 'text': " ".join(current_text)})

    return all_subtitles

def split_subtitles_to_segments(subtitles, interval_min, overlap_sec):
    if not subtitles: return []
    subtitles.sort(key=lambda x: x['start'])
    
    interval_sec = interval_min * 60
    min_time = subtitles[0]['start']
    max_time = subtitles[-1]['start']
    
    start_chunk_idx = int(min_time // interval_sec)
    end_chunk_idx = int(max_time // interval_sec)
    
    segments = []

    print(f"⏱️ 偵測 SRT 時間範圍: {int(min_time)}秒 ~ {int(max_time)}秒")
    
    for i in range(start_chunk_idx, end_chunk_idx + 1):
        chunk_start = i * interval_sec
        chunk_end = (i + 1) * interval_sec + overlap_sec 
        
        current_text_list = []
        for sub in subtitles:
            if chunk_start <= sub['start'] < chunk_end:
                current_text_list.append(sub['text'])
        
        if current_text_list:
            label = f"{i*interval_min:02d}:00 - {(i+1)*interval_min:02d}:00"
            segments.append(f"【時間段 {label}】\n" + "\n".join(current_text_list))
            
    return segments

def extract_raw_people(extractor, text):
    """階段一：提取人物"""
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
        output = extractor.model(
            prompt, max_tokens=600, temperature=0.1, repeat_penalty=1.1,
            stop=["<|im_end|>", "###"]
        )
        raw_output = output['choices'][0]['text']
        return clean_thought_tags(raw_output) 
    except: return ""

def generate_final_people_summary(extractor, raw_list):
    """階段二：總結人物名單"""
    # 再次清洗 raw_list 確保萬無一失
    clean_list = [clean_thought_tags(r) for r in raw_list]
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
        output = extractor.model(
            prompt, max_tokens=1500, temperature=0.2, repeat_penalty=1.1, stop=["<|im_end|>"]
        )
        return clean_thought_tags(output['choices'][0]['text'])
    except: return "總結生成失敗"

def main():
    print("="*60)
    print(f"🚀 啟動任務：人物識別")
    print("="*60)
    
    if not os.path.exists(MODEL_PATH):
        print(f"❌ 找不到模型: {MODEL_PATH}")
        return

    try:
        extractor = LlamaCppQwen3Extractor(model_path=MODEL_PATH)
    except Exception as e:
        print(f"引擎啟動失敗: {e}")
        return

    subtitles = parse_srt_brute_force(SRT_FILE)
    if not subtitles:
        print("❌ 字幕讀取失敗")
        return

    segments = split_subtitles_to_segments(subtitles, INTERVAL_MINUTES, OVERLAP_SECONDS)
    
    if not segments:
        print("❌ 切割後沒有產生任何片段")
        return

    raw_people = []
    print("\n--- 階段一：逐時段掃描人物 ---")
    for i, seg in enumerate(segments, 1):
        label = seg.split('\n')[0]
        print(f"[{i}/{len(segments)}] 分析 {label}...", end="\r")
        
        result = extract_raw_people(extractor, seg)
        
        if result and len(result) > 3 and "無" not in result and "<think>" not in result:
            raw_people.append(result)
            
        if hasattr(extractor, 'aggressive_memory_cleanup'):
            extractor.aggressive_memory_cleanup()

    print(f"\n✅ 掃描完成，收集到 {len(raw_people)} 個有效片段。\n")

    if raw_people:
        print("--- 階段二：名單整併 ---")
        final_report = generate_final_people_summary(extractor, raw_people)

        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write("# 會議參與人員名單\n")
            f.write(f"時間: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(final_report)
            f.write("\n\n---\n## 原始提取紀錄 (備份)\n\n")
            f.write("\n\n".join(raw_people))
        print(f"✅ 完成！請查看 {OUTPUT_FILE}")
    else:
        print("⚠️ 未發現任何人物資料。")
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write("# 會議參與人員名單\n")
            f.write(f"時間: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write("## 尚無特定人物\n")
            f.write("系統分析本段會議記錄後，未能識別出具體的人員姓名或職稱。")
        print(f"✅ 已生成狀態檔案 {OUTPUT_FILE}")

if __name__ == "__main__":
    main()