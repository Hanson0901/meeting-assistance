from core1 import SRTParser, SRTSegmentizer, LlamaCppQwen3Extractor
import os
import datetime

MODEL_PATH = "Qwen2.5-7B-Instruct-Q8_0.gguf"

SRT_FILE = "sample_meeting.srt"

OUTPUT_FILE = "result_decisions.md"

def main():
    print("🚀 啟動任務：決策事項")
    
    if not os.path.exists(MODEL_PATH):
        print(f"❌ 找不到模型檔案: {MODEL_PATH}")
        print("💡 提示：請確認您的模型檔名是否為 Qwen2.5-7B-Instruct-Q8_0.gguf")
        return
    if not os.path.exists(SRT_FILE):
        print(f"❌ 找不到字幕檔案: {SRT_FILE}")
        return

    try:
        extractor = LlamaCppQwen3Extractor(model_path=MODEL_PATH)
    except Exception as e:
        print(f"核心引擎啟動失敗: {e}")
        return

    print(f"\n📂 讀取字幕: {SRT_FILE}")
    parser = SRTParser()
    subtitles = parser.parse_srt_file(SRT_FILE)
    
    if not subtitles:
        print("❌ 字幕讀取失敗或是空檔案")
        return

    segmentizer = SRTSegmentizer(max_duration=120) 
    segments = segmentizer.segment_subtitles(subtitles)
    print(f"📄 成功切分 {len(segments)} 個段落，開始分析決策...\n")

    try:
        results = extractor.extract_all_decisions_loop(segments)
    except NameError:
        print("⚠️ 發生錯誤：請檢查 meeting_core.py 的 extract_all_decisions_loop 是否有 return 錯誤 (return result -> return results)")
        return

    print(f"\n💾 正在儲存報告至 {OUTPUT_FILE}...")
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(f"# 會議決策事項報告\n")
        f.write(f"分析時間: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"模型版本: {MODEL_PATH}\n\n")
        f.write("---\n\n")

        if isinstance(results, dict):
            for idx, content in results.items():
                time_str = f"{segments[idx-1]['start_time_str']} - {segments[idx-1]['end_time_str']}"
                f.write(f"## 第 {idx} 段 ({time_str})\n")
                f.write(f"{content}\n\n")
                f.write("---\n")
        else:
            f.write(str(results))

    print(f"✅ 完成！請開啟 {OUTPUT_FILE} 查看結果。")

if __name__ == "__main__":
    main()