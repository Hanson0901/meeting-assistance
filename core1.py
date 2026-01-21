# meeting_core.py
# -*- coding: utf-8 -*-
"""
Qwen3-4B-Q8_0 會議記錄整理核心庫 (Raspberry Pi 5 16GB 優化版 v5.5)
包含: SRTParser, SRTSegmentizer, LlamaCppQwen3Extractor
"""
from llama_cpp import Llama
import warnings
import psutil
import os
import gc
import time
from typing import List, Dict

warnings.filterwarnings("ignore")

class SRTParser:
    """SRT 檔案解析器"""
    @staticmethod
    def parse_srt_file(file_path):
        """解析 SRT 檔案，返回字幕條目列表"""
        subtitles = []
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            blocks = content.strip().split('\n\n')
            for block in blocks:
                lines = block.strip().split('\n')
                if len(lines) >= 3:
                    try:
                        seq_num = int(lines[0].strip())
                        time_line = lines[1].strip()
                        start_time_str, end_time_str = time_line.split(' --> ')
                        start_time = SRTParser.parse_time(start_time_str.strip())
                        end_time = SRTParser.parse_time(end_time_str.strip())
                        
                        content_lines = lines[2:]
                        subtitle_text = '\n'.join(content_lines).strip()
                        
                        subtitles.append({
                            'seq': seq_num,
                            'start_time': start_time,
                            'end_time': end_time,
                            'start_time_str': start_time_str.strip(),
                            'end_time_str': end_time_str.strip(),
                            'text': subtitle_text
                        })
                    except Exception as e:
                        continue
            return subtitles
        except Exception as e:
            print(f"    讀取 SRT 檔案失敗: {e}")
            return []

    @staticmethod
    def parse_time(time_str):
        """將 SRT 時間格式轉換為秒數"""
        try:
            parts = time_str.replace(',', '.').split(':')
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = float(parts[2])
            total_seconds = hours * 3600 + minutes * 60 + seconds
            return total_seconds
        except Exception as e:
            return 0


class SRTSegmentizer:
    """SRT 分段器"""
    def __init__(self, max_duration=120, max_chars=2000):
        self.max_duration = max_duration
        self.max_chars = max_chars

    def segment_subtitles(self, subtitles):
        """將字幕分段"""
        if not subtitles:
            return []
        
        segments = []
        current_segment = []
        current_chars = 0
        segment_start_idx = 0

        for i, subtitle in enumerate(subtitles):
            new_duration = subtitle['end_time'] - subtitles[segment_start_idx]['start_time']
            new_chars = current_chars + len(subtitle['text'])

            if current_segment and (new_duration > self.max_duration or new_chars > self.max_chars):
                segment = self._create_segment(current_segment, segment_start_idx, i - 1, subtitles)
                segments.append(segment)

                current_segment = [subtitle]
                segment_start_idx = i
                current_chars = len(subtitle['text'])
            else:
                current_segment.append(subtitle)
                current_chars = new_chars

        if current_segment:
            segment = self._create_segment(current_segment, segment_start_idx, len(subtitles) - 1, subtitles)
            segments.append(segment)

        return segments

    def _create_segment(self, segment_subs, start_idx, end_idx, all_subtitles):
        """創建分段對象"""
        start_time = segment_subs[0]['start_time']
        end_time = segment_subs[-1]['end_time']
        duration = end_time - start_time
        full_text = '\n'.join([sub['text'] for sub in segment_subs])

        return {
            'start_idx': start_idx + 1,
            'end_idx': end_idx + 1,
            'start_time': start_time,
            'end_time': end_time,
            'start_time_str': segment_subs[0]['start_time_str'],
            'end_time_str': segment_subs[-1]['end_time_str'],
            'duration_seconds': duration,
            'duration_formatted': self._format_duration(duration),
            'subtitle_count': len(segment_subs),
            'text': full_text,
            'text_length': len(full_text),
        }

    @staticmethod
    def _format_duration(seconds):
        """格式化時長顯示"""
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}分{secs}秒"


class LlamaCppQwen3Extractor:
    """
    【Raspberry Pi 5 16GB 優化】llama.cpp GGUF Q8_0 Qwen3-4B
    核心推論引擎：包含記憶體監控與重試機制
    """
    def __init__(self, model_path="../qwen3-4b-instruct-2507-q8_0.gguf"):
        """初始化模型（Pi 5 16GB 版本 v5.5）"""
        print("="*70)
        print(" Qwen3-4B-Q8_0 核心引擎載入中...")
        
        os.environ['TOKENIZERS_PARALLELISM'] = 'false'
        os.environ['OMP_NUM_THREADS'] = '4'

        self.max_retries = 3
        self.model_path = model_path
        
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Model not found: {model_path}")
        
        # 記憶體檢測與參數配置
        total_mem_gb = psutil.virtual_memory().total / 1024**3
        if total_mem_gb >= 15:
            n_ctx = 8192
            print(f"  ✓ Pi 5 16GB 模式 (n_ctx=8192)")
        elif total_mem_gb >= 7:
            n_ctx = 4096
            print(f"  ✓ Pi 5 8GB 模式 (n_ctx=4096)")
        else:
            n_ctx = 2048
            print(f"  ⚠ 低記憶體模式 (n_ctx=2048)")
        
        try:
            self.model = Llama(
                model_path=model_path,
                n_gpu_layers=0,
                n_threads=4,
                n_ctx=n_ctx,
                verbose=False,
            )
            print("  ✓ 模型載入成功")
        except Exception as e:
            print(f"  ❌ 模型載入失敗: {e}")
            raise

    def get_memory_usage(self):
        return {
            'cpu_percent': psutil.virtual_memory().percent,
            'cpu_used': psutil.virtual_memory().used / 1024**3,
        }

    def aggressive_memory_cleanup(self):
        """超級激進的記憶體清理"""
        gc.collect()
        time.sleep(0.05)

    def check_memory_pressure(self):
        return psutil.virtual_memory().percent > 90

    def generate_response(self, prompt, max_tokens=250, retry_count=0):
        """文字生成 (含自動重試與 OOM 防護)"""
        if retry_count >= self.max_retries:
            return "記憶體不足，無法生成回應。"
        
        try:
            if self.check_memory_pressure():
                self.aggressive_memory_cleanup()
            
            response = self.model(
                prompt,
                max_tokens=max_tokens,
                temperature=0.7,
                top_p=0.8,
                stop=["###end###"]
            )
            return response['choices'][0]['text'].strip()
            
        except RuntimeError as e:
            if "out of memory" in str(e).lower():
                print(f"    ⚠ OOM 偵測，正在重試 ({retry_count + 1}/{self.max_retries})...")
                self.aggressive_memory_cleanup()
                time.sleep(1)
                return self.generate_response(prompt, max(100, max_tokens - 50), retry_count + 1)
            else:
                return f"生成錯誤: {str(e)}"

    # =========================================================
    #  以下為三個核心提取迴圈 (供外部腳本呼叫)
    # =========================================================

    def extract_all_people_loop(self, segments: List[Dict]) -> Dict:
        """【人物識別模式】"""
        print(f"\n【模式】人物識別執行中 (共 {len(segments)} 段)...")
        results = {}
        for idx, seg in enumerate(segments, 1):
            print(f"  處理分段 {idx}/{len(segments)}...", end="\r")
            
            prompt = f"""你是一位專業的人物識別專家，請從以下會議記錄中識別出現的人物。

### 任務要求 ###
1. 使用繁體中文回答
2. 準確識別所有提到的人物姓名
3. 分析每個人物的職位/角色
4. 說明他們在本段中的主要貢獻或發言重點

### 輸出格式 ###
- [人物名稱] - [職位/角色] - [主要貢獻或發言重點]
（如無具體人物，回覆"本段無具體人物提及"）

### 會議記錄內容 ({seg['start_time_str']} - {seg['end_time_str']}) ###
{seg['text'][:1500]}

###end###"""
            
            results[idx] = self.generate_response(prompt, max_tokens=200)
            self.aggressive_memory_cleanup()
        print("\n  ✓ 人物識別完成")
        return results

    def extract_all_key_points_loop(self, segments: List[Dict]) -> Dict:
        """【會議重點模式】"""
        print(f"\n【模式】核心要點提取中 (共 {len(segments)} 段)...")
        results = {}
        for idx, seg in enumerate(segments, 1):
            print(f"  處理分段 {idx}/{len(segments)}...", end="\r")
            
            prompt = f"""你是一位專業的內容分析專家，請從以下會議記錄中提取核心要點。

### 任務要求 ###
1. 使用繁體中文回答
2. 提取最多2個最重要的核心要點
3. 按重要性排序

### 輸出格式 ###
1. [關鍵要點] - 簡要說明
2. [關鍵要點] - 簡要說明

### 會議記錄內容 ({seg['start_time_str']} - {seg['end_time_str']}) ###
{seg['text'][:1500]}

###end###"""
            
            results[idx] = self.generate_response(prompt, max_tokens=200)
            self.aggressive_memory_cleanup()
        print("\n  ✓ 重點提取完成")
        return results

    def extract_all_decisions_loop(self, segments: List[Dict]) -> Dict:
        """【分段決策模式】"""
        print(f"\n【模式】決策事項提取中 (共 {len(segments)} 段)...")
        results = {}
        for idx, seg in enumerate(segments, 1):
            print(f"  處理分段 {idx}/{len(segments)}...", end="\r")
            
            prompt = f"""你是一位專業的決策分析專家，請從以下會議記錄中識別決策事項。

### 任務要求 ###
1. 使用繁體中文回答
2. 識別所有明確的決策、決定或結論
3. 如無明確決策，則說明討論性質

### 輸出格式 ###
- [具體決策內容]
（如無決策，回覆"本段為討論性質，無具體決策"）

### 會議記錄內容 ({seg['start_time_str']} - {seg['end_time_str']}) ###
{seg['text'][:1500]}

###end###"""
            
            results[idx] = self.generate_response(prompt, max_tokens=200)
            self.aggressive_memory_cleanup()
        print("\n  ✓ 決策提取完成")
        return results