#!/usr/bin/env python3
# run_people.py
import pandas as pd
from datetime import datetime
from core1 import SRTParser, SRTSegmentizer, LlamaCppQwen3Extractor

SRT_FILE = "sample_meeting.srt"      
MODEL_PATH = "Qwen2.5-7B-Instruct-Q8_0.gguf"
OUTPUT_CSV = f"人物報告_{datetime.now().strftime('%H%M')}.csv"

def main():
    print("🚀 啟動任務：人物識別")
    extractor = LlamaCppQwen3Extractor(model_path=MODEL_PATH)
    subtitles = SRTParser.parse_srt_file(SRT_FILE)
    segments = SRTSegmentizer(max_duration=120).segment_subtitles(subtitles)
    print(f"📄 共 {len(segments)} 個分段")
    results = extractor.extract_all_people_loop(segments)
    data = []
    for idx, seg in enumerate(segments, 1):
        data.append({
            "分段": idx,
            "時間": f"{seg['start_time_str']} - {seg['end_time_str']}",
            "人物識別結果": results.get(idx, ""),
            "原文": seg['text']
        })
    
    pd.DataFrame(data).to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"\n✅ 完成！已儲存至: {OUTPUT_CSV}")

if __name__ == "__main__":
    main()