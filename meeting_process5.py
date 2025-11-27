#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Qwen3-4B-Q5_K_M 會議記錄整理助手 (Raspberry Pi 5 16GB 優化版 v5.4)
【新增】類型聚合迴圈處理 + 進度追蹤
核心優化：for 迴圈按類型連續執行 + processing_status 即時更新 + 記憶體最優化
"""
from llama_cpp import Llama
import warnings
import pandas as pd
from datetime import datetime
import os
import gc
import psutil
import time
import json
from typing import List, Dict

warnings.filterwarnings("ignore")

process_add=0
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
                        print(f"   ⚠️ 解析字幕塊失敗: {e}")
                        continue
            return subtitles
        except Exception as e:
            print(f"   ❌ 讀取 SRT 檔案失敗: {e}")
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
            print(f"   ⚠️ 時間解析失敗 '{time_str}': {e}")
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
        current_duration = 0
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
                current_duration = 0
                current_chars = len(subtitle['text'])
            else:
                current_segment.append(subtitle)
                current_duration = new_duration
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
    【v5.4 新增】類型聚合迴圈處理 + 進度追蹤
    """
    def __init__(self, model_path="../Qwen3-4B-Q8_0.gguf"):
        """初始化模型（Pi 5 16GB 版本 v5.4）"""
        print("="*70)
        print("🚀 Qwen3-4B-Q8_0 會議記錄整理助手 (Pi 5 16GB 優化版 v5.4)")
        print("="*70)
        print("🔧 啟用優化策略：")
        print("   ✓ llama.cpp GGUF Q8_0 加載 (快 40%)")
        print("   ✓ 16GB 記憶體充分利用 (n_ctx=8192)")
        print("   ✓ 【新】類型聚合迴圈（for 迴圈按類型執行）")
        print("   ✓ 【新】進度追蹤 (processing_status)")
        print("   ✓ CPU 推論優化")
        print("   ✓ 實時記憶體監控")
        print("="*70)

        os.environ['TOKENIZERS_PARALLELISM'] = 'false'
        os.environ['OMP_NUM_THREADS'] = '4'

        self.memory_threshold_gb = 10.0
        self.batch_size = 1
        self.max_retries = 3
        self.model_path = model_path
        self.generation_max_tokens = 250
        
        print(f"\n⏳ 載入 llama.cpp GGUF 模型: {model_path}")
        
        if not os.path.exists(model_path):
            print(f"❌ 模型檔案不存在: {model_path}")
            raise FileNotFoundError(f"Model not found: {model_path}")
        
        try:
            available_mem_gb = psutil.virtual_memory().available / 1024**3
            total_mem_gb = psutil.virtual_memory().total / 1024**3
            
            print(f"\n📊 記憶體狀況：")
            print(f"   總記憶體: {total_mem_gb:.1f}GB")
            print(f"   可用記憶體: {available_mem_gb:.1f}GB")
            
            if total_mem_gb >= 15:
                n_ctx = 8192
                memory_threshold = 10.0
                print(f"\n✅ Pi 5 16GB 版本檢測成功！")
                print(f"   配置: n_ctx=8192")
                
            elif total_mem_gb >= 7:
                n_ctx = 4096
                memory_threshold = 6.0
                print(f"⚠️ Pi 5 8GB 版本檢測")
                
            else:
                n_ctx = 2048
                memory_threshold = 4.0
                print(f"⚠️ 記憶體版本偏低")
            
            self.model = Llama(
                model_path=model_path,
                n_gpu_layers=0,
                n_threads=4,
                n_ctx=n_ctx,
                verbose=False,
            )
            
            self.max_context = n_ctx
            self.memory_threshold_gb = memory_threshold
            
            print(f"\n✅ 模型載入成功！")
            print(f"   Context window: {self.max_context} tokens ✓")
            print("="*70 + "\n")
            
        except Exception as e:
            print(f"\n❌ 模型載入失敗: {e}")
            raise

    def get_memory_usage(self):
        """獲取記憶體使用情況"""
        return {
            'cpu_percent': psutil.virtual_memory().percent,
            'cpu_available': psutil.virtual_memory().available / 1024**3,
            'cpu_used': psutil.virtual_memory().used / 1024**3,
        }

    def print_memory_usage(self, stage=""):
        """打印記憶體使用情況"""
        memory = self.get_memory_usage()
        print(f"📊 記憶體狀況 {stage}:")
        print(f"   使用率: {memory['cpu_percent']:.1f}%")
        print(f"   已用: {memory['cpu_used']:.1f}GB")
        print(f"   可用: {memory['cpu_available']:.1f}GB")

    def aggressive_memory_cleanup(self):
        """超級激進的記憶體清理"""
        gc.collect()
        time.sleep(0.05)

    def check_memory_pressure(self):
        """檢查記憶體壓力"""
        memory = self.get_memory_usage()
        return memory['cpu_percent'] > 90

    def generate_response(self, prompt, max_tokens=250, retry_count=0):
        """文字生成"""
        if retry_count >= self.max_retries:
            return "記憶體不足，無法生成回應。"
        
        try:
            if self.check_memory_pressure():
                self.aggressive_memory_cleanup()
                print(f"   ⚠️ 記憶體預先清理")
            
            response = self.model(
                prompt,
                max_tokens=max_tokens,
                temperature=0.7,
                top_p=0.8,
                top_k=20,
            )
            
            return response['choices'][0]['text'].strip()
            
        except RuntimeError as e:
            if "out of memory" in str(e).lower():
                print(f"   ⚠️ 記憶體不足 (重試 {retry_count + 1}/{self.max_retries})")
                self.aggressive_memory_cleanup()
                time.sleep(1)
                return self.generate_response(
                    prompt, 
                    max_tokens=max(100, max_tokens - 50), 
                    retry_count=retry_count + 1
                )
            else:
                raise e

    # ============ 【新增】類型聚合迴圈方法 ============

    def extract_all_people_loop(self, segments: List[Dict], session_id: str = None, processing_status: dict = None) -> Dict:
        """
        【新】用 for 迴圈連續提取所有分段的人物
        """
        print("\n【階段 1】提取所有分段的人物...")
        
        results = {}
        total_segments = len(segments)
        
        for idx, seg in enumerate(segments, 1):
            # 更新進度
            if session_id and processing_status:
                process_add=int( 8 * (idx / total_segments))
                progress = 60 + process_add
                processing_status[session_id] = {
                    'stage': f'提取人物中... ({idx}/{total_segments})',
                    'progress': progress,
                    'timestamp': datetime.now().isoformat()
                }
            
            prompt = f"""請從以下會議記錄中識別所有出現的人物。

### 任務要求 ###
1. 使用繁體中文回答
2. 準確識別所有人物姓名（去重）
3. 分析每個人物的職位/角色
4. 說明他們在會議中的主要貢獻

### 輸出格式 ###
### 所有出現人物
- [人物名稱] - [職位/角色] - [主要貢獻]
- ...

### 會議記錄 ###
【分段 {idx}】({seg['start_time_str']} - {seg['end_time_str']})
{seg['text']}

請開始識別："""
            
            result = self.generate_response(prompt, max_tokens=200)
            results[idx] = result
            self.aggressive_memory_cleanup()
            print(f"  ✓ 分段 {idx}/{total_segments} 人物提取完成")
        
        print(f"✓ 所有分段人物提取完成")
        return results

    def extract_all_key_points_loop(self, segments: List[Dict], session_id: str = None, processing_status: dict = None) -> Dict:
        """
        【新】用 for 迴圈連續提取所有分段的要點
        """
        print("【階段 2】提取所有分段的核心要點...")
        
        results = {}
        total_segments = len(segments)
        
        for idx, seg in enumerate(segments, 1):
            # 更新進度
            if session_id and processing_status:
                process_add=int( 8 * (idx / total_segments))
                progress = 68 +process_add
                processing_status[session_id] = {
                    'stage': f'提取要點中... ({idx}/{total_segments})',
                    'progress': progress,
                    'timestamp': datetime.now().isoformat()
                }
            
            prompt = f"""請從以下會議記錄中提取核心要點。

### 任務要求 ###
1. 使用繁體中文回答
2. 提取 3-5 個最重要的核心要點
3. 去除重複
4. 按重要性排序

### 輸出格式 ###
### 核心要點
1. [要點] - 簡要說明
2. [要點] - 簡要說明
...

### 會議記錄 ###
【分段 {idx}】({seg['start_time_str']} - {seg['end_time_str']})
{seg['text']}

請開始提取："""
            
            result = self.generate_response(prompt, max_tokens=200)
            results[idx] = result
            self.aggressive_memory_cleanup()
            print(f"  ✓ 分段 {idx}/{total_segments} 要點提取完成")
        
        print(f"✓ 所有分段要點提取完成")
        return results

    def extract_all_decisions_loop(self, segments: List[Dict], session_id: str = None, processing_status: dict = None) -> Dict:
        """
        【新】用 for 迴圈連續提取所有分段的決策
        """
        print("【階段 3】提取所有分段的決策事項...")
        
        results = {}
        total_segments = len(segments)
        
        for idx, seg in enumerate(segments, 1):
            # 更新進度
            if session_id and processing_status:
                progress = 76 + int(8 * (idx / total_segments))
                processing_status[session_id] = {
                    'stage': f'提取決策中... ({idx}/{total_segments})',
                    'progress': progress,
                    'timestamp': datetime.now().isoformat()
                }
            
            prompt = f"""請從以下會議記錄中識別決策事項。

### 任務要求 ###
1. 使用繁體中文回答
2. 識別所有明確的決策、決定或結論
3. 區分「已決策」vs「討論中」
4. 去除重複

### 輸出格式 ###
### 決策事項
✓ [已決策] - [內容]
? [待決策] - [內容]
...

### 會議記錄 ###
【分段 {idx}】({seg['start_time_str']} - {seg['end_time_str']})
{seg['text']}

請開始識別："""
            
            result = self.generate_response(prompt, max_tokens=150)
            results[idx] = result
            self.aggressive_memory_cleanup()
            print(f"  ✓ 分段 {idx}/{total_segments} 決策提取完成")
        
        print(f"✓ 所有分段決策提取完成")
        return results

    def extract_all_actions_loop(self, segments: List[Dict], session_id: str = None, processing_status: dict = None) -> Dict:
        """
        【新】用 for 迴圈連續提取所有分段的行動項目
        """
        print("【階段 4】提取所有分段的行動項目...")
        
        results = {}
        total_segments = len(segments)
        
        for idx, seg in enumerate(segments, 1):
            # 更新進度
            if session_id and processing_status:
                progress = 84 + int(8 * (idx / total_segments))
                processing_status[session_id] = {
                    'stage': f'提取行動項目中... ({idx}/{total_segments})',
                    'progress': progress,
                    'timestamp': datetime.now().isoformat()
                }
            
            prompt = f"""請從以下會議記錄中識別行動項目。

### 任務要求 ###
1. 使用繁體中文回答
2. 識別所有待辦事項、後續行動或指派任務
3. 標註負責人或執行單位
4. 標註優先級（高/中/低）
5. 去除重複

### 輸出格式 ###
### 行動項目
[優先級] [待辦事項] - [負責人/單位] - [預期完成]
...

### 會議記錄 ###
【分段 {idx}】({seg['start_time_str']} - {seg['end_time_str']})
{seg['text']}

請開始識別："""
            
            result = self.generate_response(prompt, max_tokens=200)
            results[idx] = result
            self.aggressive_memory_cleanup()
            print(f"  ✓ 分段 {idx}/{total_segments} 行動項目提取完成")
        
        print(f"✓ 所有分段行動項目提取完成")
        return results

    def generate_overall_summary(self, all_people_results, all_keypoints_results, all_decisions_results, all_actions_results, total_segments, total_duration, session_id: str = None, processing_status: dict = None):
        """
        【新】生成會議整體總結（基於聚合的 for 迴圈結果）
        """
        print("\n【階段 5】生成會議整體總結...")
        
        if session_id and processing_status:
            processing_status[session_id] = {
                'stage': '生成總結中...',
                'progress': 84,
                'timestamp': datetime.now().isoformat()
            }
        
        # 聚合所有結果
        people_text = "\n".join(all_people_results.values())
        keypoints_text = "\n".join(all_keypoints_results.values())
        decisions_text = "\n".join(all_decisions_results.values())
        actions_text = "\n".join(all_actions_results.values())
        
        prompt = f"""### 任務：基於會議信息生成專業總結

### 會議基本信息
- 總分段數：{total_segments} 段
- 會議總時長：{total_duration}

### 聚合的會議信息

#### 所有參與人物
{people_text[:2000]}

#### 核心要點
{keypoints_text[:2000]}

#### 決策事項
{decisions_text}

#### 行動項目
{actions_text}

### 輸出格式（JSON）
請直接輸出以下JSON格式，不添加任何額外說明或思考過程：

{{
  "title": "會議標題（不超過12字）",
  "core_topic": "會議核心主題（2-3句話）",
  "participants": "參與人物簡介",
  "discussion_points": ["焦點1", "焦點2", "焦點3", "焦點4"],
  "achievements": ["成果1", "成果2", "成果3"],
  "action_items": ["待辦1 - 負責人 - 預期完成", "待辦2 - 負責人 - 預期完成"],
  "recommendations": "後續跟進建議"
}}"""
        
        result = self.generate_response(prompt, max_tokens=800)
        
        # 【後處理】將 JSON 轉換為 markdown
        try:
            data = json.loads(result)
            summary = f"""## 會議整體主題總結

### 會議標題
{data.get('title', '無標題')}

### 參與人物及角色
{data.get('participants', '無')}

### 會議目標
{data.get('core_topic', '無')}

### 主要討論焦點
"""
            for i, point in enumerate(data.get('discussion_points', []), 1):
                summary += f"{i}. {point}\n"
            
            summary += "\n### 重要成果\n"
            for achievement in data.get('achievements', []):
                summary += f"- {achievement}\n"
            
            summary += "\n### 待辦事項與責任人\n"
            for action in data.get('action_items', []):
                summary += f"- {action}\n"
            
            summary += f"\n### 後續跟進建議\n{data.get('recommendations', '無')}\n"
            
            print(f"✓ 總結完成")
            return summary
            
        except json.JSONDecodeError:
            print(f"✓ 總結完成（非 JSON 格式）")
            return result

    def process_srt_file_aggregated(self, srt_file_path, output_file_path=None, max_duration=120, max_chars=2000, session_id: str = None, processing_status: dict = None):
        """
        【新】類型聚合迴圈處理 SRT 檔案 (v5.4)
        用 for 迴圈按類型連續執行 + processing_status 進度追蹤
        """
        try:
            print(f"\n📂 正在讀取 SRT 檔案: {srt_file_path}")
            parser = SRTParser()
            subtitles = parser.parse_srt_file(srt_file_path)

            if not subtitles:
                print("❌ 未能解析任何字幕條目")
                return None

            print(f"✓ 成功解析 {len(subtitles)} 條字幕條目")

            # 分段
            print(f"\n🔧 正在進行分段處理...")
            segmentizer = SRTSegmentizer(max_duration=max_duration, max_chars=max_chars)
            segments = segmentizer.segment_subtitles(subtitles)
            print(f"✓ 成功分為 {len(segments)} 段")

            # 顯示分段信息
            total_duration_seconds = 0
            for i, seg in enumerate(segments, 1):
                print(f"   段 {i}: {seg['start_time_str']} - {seg['end_time_str']} ({seg['duration_formatted']}, {seg['text_length']} 字)")
                total_duration_seconds += seg['duration_seconds']

            total_duration_formatted = SRTSegmentizer()._format_duration(total_duration_seconds)
            print(f"\n📊 會議總時長: {total_duration_formatted}")

            # 【新】類型聚合迴圈處理
            print("\n" + "="*70)
            print("【類型聚合迴圈處理開始】")
            print("="*70)

            self.print_memory_usage("迴圈處理開始前")

            # for 迴圈按類型連續執行
            all_people = self.extract_all_people_loop(segments, session_id, processing_status)
            self.aggressive_memory_cleanup()

            all_key_points = self.extract_all_key_points_loop(segments, session_id, processing_status)
            self.aggressive_memory_cleanup()

            all_decisions = self.extract_all_decisions_loop(segments, session_id, processing_status)
            self.aggressive_memory_cleanup()

            all_actions = self.extract_all_actions_loop(segments, session_id, processing_status)
            self.aggressive_memory_cleanup()

            # 生成最終總結
            overall_summary = self.generate_overall_summary(
                all_people, all_key_points, all_decisions, all_actions,
                len(segments), total_duration_formatted, session_id, processing_status
            )
            self.aggressive_memory_cleanup()

            print("\n" + "="*70)
            print("【類型聚合迴圈處理完成】")
            print("="*70)

            # 保存結果
            if output_file_path is None:
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                base_name = os.path.splitext(os.path.basename(srt_file_path))[0]
                summary_file_path = f'{base_name}_loop_aggregated_summary_{timestamp}.md'
            else:
                summary_file_path = output_file_path.replace('.csv', '_loop_aggregated.md')

            with open(summary_file_path, 'w', encoding='utf-8') as f:
                f.write("# 會議整體主題總結（Pi 5 16GB llama.cpp GGUF Q5_K_M 版本 v5.4 類型聚合迴圈版）\n\n")
                f.write(f"**分析時間**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"**會議時長**: {total_duration_formatted}\n")
                f.write(f"**總分段數**: {len(segments)} 段\n\n")
                f.write("---\n\n")
                f.write("## 詳細分段結果\n\n")
                f.write("### 參與人物\n\n")
                for seg_id, result in all_people.items():
                    f.write(f"#### 分段 {seg_id}\n{result}\n\n")
                f.write("### 核心要點\n\n")
                for seg_id, result in all_key_points.items():
                    f.write(f"#### 分段 {seg_id}\n{result}\n\n")
                f.write("### 決策事項\n\n")
                for seg_id, result in all_decisions.items():
                    f.write(f"#### 分段 {seg_id}\n{result}\n\n")
                f.write("### 行動項目\n\n")
                for seg_id, result in all_actions.items():
                    f.write(f"#### 分段 {seg_id}\n{result}\n\n")
                f.write("---\n\n")
                f.write("## 會議整體總結\n\n")
                f.write(overall_summary)

            print(f"\n✓ 會議總結已保存至: {summary_file_path}")
            self.print_memory_usage("迴圈處理完成後")

            return summary_file_path

        except Exception as e:
            print(f"❌ 處理失敗: {str(e)}")
            self.aggressive_memory_cleanup()
            return None


if __name__ == "__main__":
    print("\n" + "="*80)
    print("🚀 Qwen3-4B-Q5_K_M 會議記錄整理系統")
    print("   Raspberry Pi 5 16GB 優化版本 v5.4 (類型聚合迴圈版)")
    print("="*80)

    extractor = LlamaCppQwen3Extractor(model_path="../Qwen3-4B-Q5_K_M.gguf")

    print(f"\n✅ 模型初始化完成！")
    print("="*80 + "\n")
    
    # 【使用新方法】
    # processing_status = {}
    # session_id = "test_session"
    # srt_file = r"path/to/your/file.srt"
    # result = extractor.process_srt_file_loop_aggregated(
    #     srt_file,
    #     session_id=session_id,
    #     processing_status=processing_status
    # )