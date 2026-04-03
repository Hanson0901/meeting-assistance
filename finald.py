from core1 import LlamaCppQwen3Extractor
import os
import datetime
import re

MODEL_PATH = "Qwen3-4B-Q8_0.gguf"   
SRT_FILE = "output_38.srt"           
OUTPUT_FILE = "finald_38.md"         

INTERVAL_MINUTES = 5   # 每 5 分鐘切一段進行分析
OVERLAP_SECONDS = 60   # 重疊 60 秒避免漏掉跨段落的決策

def clean_llm_output(raw_text):

    if not raw_text: return ""
    text = re.sub(r'<think>.*?</think>', '', raw_text, flags=re.DOTALL)
    if '<think>' in text:
        text = text.split('<think>')[0]
    return text.strip()

def parse_srt_brute_force(file_path):
    all_subtitles = []
    encodings = ['utf-8', 'utf-8-sig', 'cp950']
    lines = []
    for enc in encodings:
        try:
            with open(file_path, 'r', encoding=enc) as f:
                lines = f.readlines()
            print(f"[finalld parse_srt]使用編碼 {enc} 讀取成功，共 {len(lines)} 行")
            break
        except: continue
            
    if not lines: return []

    current_start = 0 
    current_text = []
    
    for line in lines:
        line = line.strip()
        if "-->" in line:
            if current_text:
                full_text = " ".join(current_text)
                all_subtitles.append({'start': current_start, 'text': full_text})
                current_text = []
            try:
                t_str = line.split('-->')[0].strip().replace(',', '.')
                parts = t_str.split(':')
                if len(parts) == 3:
                    current_start = float(parts[0])*3600 + float(parts[1])*60 + float(parts[2])
                else:
                    current_start = float(t_str)
            except: pass 
            continue

        if line.isdigit(): continue
        if not line: continue
        current_text.append(line)
        
    if current_text:
        all_subtitles.append({'start': current_start, 'text': " ".join(current_text)})
        
    return all_subtitles

def split_subtitles_to_segments(subtitles, interval_min, overlap_sec):
    """
    【智慧時間切割】自動偵測 SRT 起始與結束時間，只處理有內容的區段
    """
    if not subtitles: return []
    subtitles.sort(key=lambda x: x['start'])
    
    interval_sec = interval_min * 60
    
    min_time = subtitles[0]['start']
    max_time = subtitles[-1]['start']
    
    start_chunk_idx = int(min_time // interval_sec)
    end_chunk_idx = int(max_time // interval_sec)
    
    segments = []

    print(f"[finald split_subtitles_to_segments] 偵測 SRT 時間範圍: {int(min_time)}秒 ~ {int(max_time)}秒")
    print(f"[finald split_subtitles_to_segments]   將從 {start_chunk_idx * interval_min} 分鐘開始切分，至 {(end_chunk_idx + 1) * interval_min} 分鐘結束")

    for i in range(start_chunk_idx, end_chunk_idx + 1):
        chunk_start = i * interval_sec
        chunk_end = (i + 1) * interval_sec + overlap_sec 
        
        current_text_list = []
        for sub in subtitles:
            if chunk_start <= sub['start'] < chunk_end:
                current_text_list.append(sub['text'])
        
        if current_text_list:
            label = f"{i*interval_min:02d}:00 - {(i+1)*interval_min:02d}:00"
            segments.append(f"【時間段 {label} (含重疊)】\n" + "\n".join(current_text_list))
            
    return segments

def extract_raw_decisions(extractor, text):
    """
    第一階段：提取原始決策
    """
    if len(text) < 50: return ""

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
        output = extractor.model(
            prompt, max_tokens=500, temperature=0.1, repeat_penalty=1.1, stop=["<|im_end|>"]
        )
        return clean_llm_output(output['choices'][0]['text'].strip())
    except: return ""

def generate_final_decision_report(extractor, raw_list):
    """
    第二階段：總整理 (去重 + 分類)
    """
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
        output = extractor.model(
            prompt, max_tokens=1500, temperature=0.1, stop=["<|im_end|>"]
        )
        return clean_llm_output(output['choices'][0]['text'].strip())
    except: return "報告生成失敗"

def main():
    print("="*60)
    print("[finald] 啟動任務：提取決策")
    print("="*60)
    
    if not os.path.exists(MODEL_PATH):
        print(f"[finald] 找不到模型: {MODEL_PATH}")
        return

    try:
        extractor = LlamaCppQwen3Extractor(model_path=MODEL_PATH)
    except Exception as e:
        print(f"[finald] 引擎啟動失敗: {e}")
        return

    print("[finald] 1️⃣  解析 SRT...")
    subtitles = parse_srt_brute_force(SRT_FILE)
    segments = split_subtitles_to_segments(subtitles, INTERVAL_MINUTES, OVERLAP_SECONDS)
    
    raw_decisions = []
    print("\n[finald] 2️⃣  逐段掃描決策點...")
    for i, seg in enumerate(segments):
        label = seg.split('\n')[0]
        print(f"[finald]   - 分析片段 {i+1}/{len(segments)}...", end="\r")
        
        res = extract_raw_decisions(extractor, seg)
        if res and "無" not in res and len(res) > 5:
            raw_decisions.append(res)
            
    print(f"\n[finald] 掃描完成，發現 {len(raw_decisions)} 個決策片段")

    if raw_decisions:
        print("\n[finald] 3️⃣  生成最終決策報告...")
        final_report = generate_final_decision_report(extractor, raw_decisions)
        
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write("# 會議決策重點報告\n")
            f.write(f"時間: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write(final_report)
            f.write("\n\n---\n## 原始提取紀錄 (備份)\n\n")
            f.write("\n".join(raw_decisions))
            
        print(f"[finald] 完成！請查看 {OUTPUT_FILE}")
    else:
        print(f"[finald] 未發現任何明確決策。")
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write("# 會議決策重點報告\n")
            f.write(f"時間: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write("## 尚無明確決策\n")
            f.write("系統分析本段會議記錄後，未發現明確的承諾、決議或共識。")
        print(f"[finald] 已生成檔案 {OUTPUT_FILE}")

if __name__ == "__main__":
    main()