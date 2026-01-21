from core1 import LlamaCppQwen3Extractor
import os
import datetime
import re

MODEL_PATH = "Qwen3-4B-Q8_0.gguf"   
SRT_FILE = "output_11.srt"          
OUTPUT_FILE = "finalk_11.md" 

INTERVAL_MINUTES = 5   
OVERLAP_SECONDS = 60  

def clean_thought_tags(text):
    
    if not text: return ""

    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    
    patterns = [
        r"^好的，.*？：", 
        r"^根據.*？如下：",
        r"^Here is the summary.*:",
        r"^Sure,.*:"
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

    print(f"⏱️ 偵測 SRT 時間範圍: {int(min_time)}秒 ~ {int(max_time)}秒")
    print(f"   將從 {start_chunk_idx * interval_min} 分鐘開始切分，至 {(end_chunk_idx + 1) * interval_min} 分鐘結束")

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

def extract_raw_keypoints(extractor, text):
    """
    第一階段：提取重點
    """
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
        output = extractor.model(
            prompt,
            max_tokens=600,
            temperature=0.1,
            repeat_penalty=1.1,
            stop=["<|im_end|>", "###"]
        )
        raw_text = output['choices'][0]['text'].strip()
        return clean_thought_tags(raw_text)
    except Exception as e:
        return ""

def generate_final_keypoints_summary(extractor, raw_list):
    """
    第二階段：總整理
    """
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
        output = extractor.model(
            prompt,
            max_tokens=2000,
            temperature=0.2,
            repeat_penalty=1.1,
            stop=["<|im_end|>"]
        )
        raw_text = output['choices'][0]['text'].strip()
        # ★ 這裡進行清洗
        return clean_thought_tags(raw_text)
    except Exception as e:
        return "總結生成失敗"

def main():
    print("="*60)
    print("🚀 啟動任務：提取會議重點")
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
    
    raw_keypoints = []
    print("\n--- 階段一：逐時段掃描重點 ---")
    for i, seg in enumerate(segments, 1):
        label = seg.split('\n')[0]
        print(f"[{i}/{len(segments)}] 分析 {label}...", end="\r")
        
        result = extract_raw_keypoints(extractor, seg)
        if result and len(result) > 5 and "無" not in result:
            raw_keypoints.append(f"{label}\n{result}")
        
        if hasattr(extractor, 'aggressive_memory_cleanup'):
            extractor.aggressive_memory_cleanup()

    print(f"\n✅ 掃描完成，收集到 {len(raw_keypoints)} 個有效片段。\n")

    if raw_keypoints:
        print("--- 階段二：AI 總整理 ---")
        final_report = generate_final_keypoints_summary(extractor, raw_keypoints)

        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write("# 會議核心重點總結\n")
            f.write(f"分析時間: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(final_report)
            f.write("\n\n---\n## 原始提取紀錄\n\n")
            f.write("\n\n".join(raw_keypoints))
        print(f"✅ 完成！請查看 {OUTPUT_FILE}")
    else:
        print("⚠️ 未發現任何重點。")
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write("# 會議核心重點總結\n")
            f.write(f"分析時間: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write("## 尚無明確重點\n")
            f.write("系統分析本段會議記錄後，未發現具體的討論重點或結論。")
        print(f"✅ 已生成狀態檔案 {OUTPUT_FILE}")
    
if __name__ == "__main__":
    main()