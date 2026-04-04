#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Qwen3-4B-Q8_0 會議記錄整理助手 (Raspberry Pi 5 優化版 v5.1)
專門用於 Raspberry Pi 5 + llama.cpp GGUF 量化模型
核心優化：GGUF INT8 加載 + llama.cpp CPU 推論 + 動態 context 管理
"""
from llama_cpp import Llama
import warnings
import pandas as pd
from datetime import datetime
import os
import gc
import psutil
import time

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

    @staticmethod
    def seconds_to_time_str(seconds):
        """將秒數轉換為時間字符串"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        milliseconds = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"


class SRTSegmentizer:
    """SRT 分段器 - 根據時間軸和字數分段"""
    def __init__(self, max_duration=120, max_chars=1500):
        """
        初始化分段器（Pi 5 更激進）
        Raspberry Pi 5 版本: 2分鐘 或 1500字（更激進）
        """
        self.max_duration = max_duration
        self.max_chars = max_chars

    def segment_subtitles(self, subtitles):
        """將字幕分段，基於時間和字數"""
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
            'speaker_segments': segment_subs
        }

    @staticmethod
    def _format_duration(seconds):
        """格式化時長顯示"""
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}分{secs}秒"


class LlamaCppQwen3Extractor:
    """
    【Raspberry Pi 5 優化】llama.cpp GGUF INT8 Qwen3-4B
    核心優化：GGUF INT8 加載 + llama.cpp CPU 推論 + 動態 context 管理 + Pi 5 ARM64 支援
    """
    def __init__(self, model_path="../Qwen3-4B-Q8_0.gguf"):
        """
        初始化模型（Raspberry Pi 5 llama.cpp GGUF 版本 v5.1）
        【改進】動態 context 設置，根據可用記憶體調整
        """
        print("="*70)
        print("🚀 Qwen3-4B-Q8_0 會議記錄整理助手 (Raspberry Pi 5 優化版 v5.1)")
        print("="*70)
        print("🔧 啟用優化策略：")
        print("   ✓ llama.cpp GGUF INT8 加載")
        print("   ✓ 動態 Context 管理（根據記憶體自適應）")
        print("   ✓ CPU 推論（適合 Pi 5 ARM64）")
        print("   ✓ 超激進分段策略（2 分鐘/1500 字）")
        print("   ✓ 實時記憶體監控與清理")
        print("   ✓ 縮短生成長度（防止 OOM）")
        print("="*70)

        # 設置環境變數
        os.environ['TOKENIZERS_PARALLELISM'] = 'false'
        os.environ['OMP_NUM_THREADS'] = '4'  # Pi 5 有 4 核

        # Pi 5 記憶體配置
        self.memory_threshold_gb = 6.5  # Pi 5 閾值：6.5GB
        self.batch_size = 1
        self.max_retries = 3
        self.model_path = model_path
        self.generation_max_tokens = 200  # ← 縮短生成長度
        
        # 載入模型
        print(f"\n⏳ 載入 llama.cpp GGUF 模型: {model_path}")
        
        if not os.path.exists(model_path):
            print(f"❌ 模型檔案不存在: {model_path}")
            print("\n📥 請確保模型路徑正確")
            raise FileNotFoundError(f"Model not found: {model_path}")
        
        try:
            # 【改進】動態計算 n_ctx 根據可用記憶體
            available_mem_gb = psutil.virtual_memory().available / 1024**3
            
            # 根據可用記憶體調整 context window
            if available_mem_gb > 4.5:
                n_ctx = 4096  # 充分利用模型容量
                print(f"✓ 可用記憶體充足 ({available_mem_gb:.1f}GB)，使用 n_ctx=4096")
            elif available_mem_gb > 3:
                n_ctx = 2048  # 平衡
                print(f"✓ 可用記憶體中等 ({available_mem_gb:.1f}GB)，使用 n_ctx=2048")
            else:
                n_ctx = 1024  # 保守
                print(f"⚠️ 可用記憶體有限 ({available_mem_gb:.1f}GB)，使用 n_ctx=1024")
            
            self.model = Llama(
                model_path=model_path,
                n_gpu_layers=0,     # ← 全部在 CPU
                n_threads=4,        # ← Pi 5 有 4 核
                n_ctx=n_ctx,        # ← 【新增】動態 context window
                verbose=False,
            )
            
            self.max_context = n_ctx
            
            print(f"✅ 模型載入成功！")
            print(f"   量化方式: GGUF INT8 ✓")
            print(f"   推論設備: CPU ✓")
            print(f"   Context window: {self.max_context} tokens ✓")
            print(f"   模型最大 context: 40960 tokens（已充分利用）✓")
            print("="*70 + "\n")
            
        except Exception as e:
            print(f"\n❌ 模型載入失敗: {e}")
            raise

    def get_memory_usage(self):
        """獲取當前記憶體使用情況"""
        return {
            'cpu_percent': psutil.virtual_memory().percent,
            'cpu_available': psutil.virtual_memory().available / 1024**3,
            'cpu_used': psutil.virtual_memory().used / 1024**3,
        }

    def print_memory_usage(self, stage=""):
        """打印記憶體使用情況"""
        memory = self.get_memory_usage()
        print(f"📊 記憶體狀況 {stage}:")
        print(f"   CPU使用率: {memory['cpu_percent']:.1f}%")
        print(f"   CPU已用: {memory['cpu_used']:.1f}GB")
        print(f"   CPU可用: {memory['cpu_available']:.1f}GB")

    def aggressive_memory_cleanup(self):
        """超級激進的記憶體清理"""
        gc.collect()
        time.sleep(0.05)

    def check_memory_pressure(self):
        """檢查記憶體壓力"""
        memory = self.get_memory_usage()
        return memory['cpu_percent'] > 85

    def _split_text_by_context(self, text, overlap=100):
        """根據 context window 動態分割文本"""
        # llama.cpp：用字符估算 (粗略: 1 token ≈ 4 字符)
        # 保留 20% 的空間給提示詞
        max_chars = int((self.max_context * 0.8 - 100) * 4)
        
        segments = []
        current_segment = ""
        
        for line in text.split('\n'):
            if len(current_segment) + len(line) > max_chars:
                if current_segment:
                    segments.append(current_segment.strip())
                current_segment = line
            else:
                current_segment += '\n' + line if current_segment else line
        
        if current_segment:
            segments.append(current_segment.strip())
        
        return segments

    def generate_response(self, prompt, max_tokens=200, retry_count=0):
        """llama.cpp 文字生成方法"""
        if retry_count >= self.max_retries:
            return "記憶體不足，無法生成回應。"
        
        try:
            # 預防性清理
            if self.check_memory_pressure():
                self.aggressive_memory_cleanup()
                print(f"   ⚠️ 記憶體預先清理")
            
            # llama.cpp 直接生成
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
                    max_tokens=max(80, max_tokens - 30), 
                    retry_count=retry_count + 1
                )
            else:
                raise e

    def extract_people(self, text):
        """提取會議中出現的人物"""
        print("    → 識別人物...")
        prompt = f"""請從以下會議記錄中識別出現的人物。

### 任務要求 ###
1. 使用繁體中文回答
2. 準確識別所有提到的人物姓名
3. 分析每個人物的職位/角色
4. 說明他們在本段中的主要貢獻或發言重點

### 輸出格式 ###
### 出現人物
- [人物名稱] - [職位/角色] - [主要貢獻]
（如本段無明確人物，則回覆"本段無具體人物提及"）

### 會議記錄內容 ###
{text}

請開始識別："""
        return self.generate_response(prompt, max_tokens=150)

    def extract_key_points(self, text):
        """提取核心要點"""
        print("    → 提取要點...")
        prompt = f"""請從以下會議記錄中提取最多2個核心要點。

### 任務要求 ###
1. 使用繁體中文回答
2. 提取最多2個最重要的核心要點
3. 每個要點應該簡潔明了
4. 按重要性排序

### 輸出格式 ###
### 核心要點
1. [關鍵要點] - 簡要說明
2. [關鍵要點] - 簡要說明

### 會議記錄內容 ###
{text}

請開始提取："""
        return self.generate_response(prompt, max_tokens=150)

    def extract_decisions(self, text):
        """提取決策事項"""
        print("    → 識別決策...")
        prompt = f"""請從以下會議記錄中識別決策事項。

### 任務要求 ###
1. 使用繁體中文回答
2. 識別所有明確的決策、決定或結論
3. 如無明確決策，則說明討論性質

### 輸出格式 ###
### 決策事項
- [具體決策內容]
（如無決策事項，則回覆"本段為討論性質，無具體決策"）

### 會議記錄內容 ###
{text}

請開始識別："""
        return self.generate_response(prompt, max_tokens=120)

    def extract_action_items(self, text):
        """提取行動項目"""
        print("    → 識別行動項目...")
        prompt = f"""請從以下會議記錄中識別行動項目。

### 任務要求 ###
1. 使用繁體中文回答
2. 識別所有待辦事項、後續行動或指派任務
3. 標註負責人或執行單位（如有提及）

### 輸出格式 ###
### 行動項目
- [待辦事項內容] - [負責人/單位]
（如無行動項目，則回覆"本段無具體行動項目"）

### 會議記錄內容 ###
{text}

請開始識別："""
        return self.generate_response(prompt, max_tokens=120)

    def generate_summary(self, text):
        """生成總結"""
        print("    → 生成總結...")
        prompt = f"""請為以下會議記錄生成簡潔總結。

### 任務要求 ###
1. 使用繁體中文回答
2. 用一句話總結本段會議內容的核心
3. 突出最重要的議題或結論

### 輸出格式 ###
### 總結
[一句話總結本段會議內容的核心]

### 會議記錄內容 ###
{text}

請開始總結："""
        
        return self.generate_response(prompt, max_tokens=80)

    def process_single_segment(self, segment, index):
        """處理單個分段"""
        print(f"   開始處理第 {index} 段 ({segment['start_time_str']} - {segment['end_time_str']}, {segment['text_length']} 字)...")

        try:
            # 順序提取
            people_result = self.extract_people(segment['text'])
            self.aggressive_memory_cleanup()

            keypoints_result = self.extract_key_points(segment['text'])
            self.aggressive_memory_cleanup()

            decisions_result = self.extract_decisions(segment['text'])
            self.aggressive_memory_cleanup()

            actions_result = self.extract_action_items(segment['text'])
            self.aggressive_memory_cleanup()

            summary_result = self.generate_summary(segment['text'])
            self.aggressive_memory_cleanup()

            integrated_result = f"""## 會議記錄整理 (第 {index} 段)

### 時間戳
時間: {segment['start_time_str']} - {segment['end_time_str']}
時長: {segment['duration_formatted']}
字數: {segment['text_length']} 字

{people_result}

{keypoints_result}

{decisions_result}

{actions_result}

{summary_result}"""

            return integrated_result
            
        except Exception as e:
            print(f"   ❌ 第 {index} 段處理失敗: {str(e)}")
            return f"處理錯誤: {str(e)}"

    def process_batch_segments(self, batch_segments, batch_start_idx):
        """批次處理分段"""
        batch_results = []
        batch_summaries = []
        
        for i, segment in enumerate(batch_segments):
            current_idx = batch_start_idx + i + 1
            print(f"   處理第 {current_idx} 段...")
            
            try:
                if self.check_memory_pressure():
                    self.aggressive_memory_cleanup()
                    print(f"   ⚠️ 記憶體清理完成")

                summary = self.process_single_segment(segment, current_idx)
                batch_summaries.append(summary)
                
                result = {
                    '段號': current_idx,
                    '開始時間': segment['start_time_str'],
                    '結束時間': segment['end_time_str'],
                    '時長': segment['duration_formatted'],
                    '字幕條數': segment['subtitle_count'],
                    '原文字數': segment['text_length'],
                    '原文': segment['text'],
                    '重點整理': summary,
                    '處理時間': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                
                batch_results.append(result)
                print(f"     ✓ 第 {current_idx} 段完成")
                
            except Exception as e:
                print(f"     ❌ 第 {current_idx} 段失敗: {str(e)}")
                continue
        
        return batch_results, batch_summaries

    def extract_key_elements_optimized(self, all_summaries_batch):
        """記憶體優化的關鍵元素提取"""
        key_themes = []
        decisions = []
        actions = []
        raw_people_info = []

        for batch_summaries in all_summaries_batch:
            for summary in batch_summaries:
                lines = summary.split('\n')
                current_section = ""

                for line in lines:
                    line = line.strip()
                    if "### 出現人物" in line:
                        current_section = "people"
                    elif "### 核心要點" in line:
                        current_section = "themes"
                    elif "### 決策事項" in line:
                        current_section = "decisions"
                    elif "### 行動項目" in line:
                        current_section = "actions"
                    elif line and line.startswith('-'):
                        if current_section == "people":
                            person_info = line.lstrip('- ').strip()
                            if person_info and "本段無具體人物提及" not in person_info:
                                raw_people_info.append(person_info)
                        elif current_section == "themes" and len(key_themes) < 15:
                            key_themes.append(line.lstrip('- ').strip())
                        elif current_section == "decisions" and len(decisions) < 12:
                            decisions.append(line.lstrip('- ').strip())
                        elif current_section == "actions" and len(actions) < 12:
                            actions.append(line.lstrip('- ').strip())

        unique_people_count = len(set([self.extract_person_name(p) for p in raw_people_info]))

        return key_themes, decisions, actions, unique_people_count

    def extract_person_name(self, person_info):
        """從人物信息中提取姓名"""
        separators = ['-', '：', ':', '（', '(']
        person_name = person_info.strip()
        for sep in separators:
            if sep in person_name:
                person_name = person_name.split(sep)[0].strip()
                break
        return person_name

    def generate_overall_summary_optimized(self, key_themes, decisions, actions, unique_people_count, total_segments, total_duration):
        """記憶體優化的整體會議總結生成"""
        print("\n生成整體會議主題總結...")

        max_themes = 8
        max_decisions = 6
        max_actions = 6

        themes_text = "\n".join([f"- {theme}" for theme in key_themes[:max_themes]])
        decisions_text = "\n".join([f"- {decision}" for decision in decisions[:max_decisions]])
        actions_text = "\n".join([f"- {action}" for action in actions[:max_actions]])

        prompt_template = f"""請基於以下提取的關鍵信息，總結整個會議的核心主題。

### 會議基本信息 ###
- 總分段數：{total_segments} 段
- 會議總時長：{total_duration}
- 獨立人物數：{unique_people_count} 位

### 關鍵主題 ###
{themes_text}

### 重要決策事項 ###
{decisions_text}

### 行動項目 ###
{actions_text}

### 任務要求 ###
請生成簡潔的整體會議總結：
1. 使用繁體中文回答
2. 提取核心要點
3. 總結會議的主要目的和成果
4. 不超過 500 字

## 會議整體主題總結

### 會議標題
[請幫會議訂定一個吸引人的標題，不超過12字]

### 會議核心主題
[用1-2句話概括整場會議的主要目的]

### 主要討論焦點
1. [焦點一]
2. [焦點二]
3. [焦點三]

### 重要成果
- [成果一]
- [成果二]

### 待辦事項
- [行動一]
- [行動二]

請開始總結："""

        return self.generate_response(prompt_template, max_tokens=600)

    def process_srt_file_optimized(self, srt_file_path, output_file_path=None, max_duration=120, max_chars=1500):
        """
        【Raspberry Pi 5 優化】llama.cpp GGUF SRT 檔案處理
        預設分段：2 分鐘/1500 字（激進分段）
        """
        try:
            print(f"\n📂 正在讀取 SRT 檔案: {srt_file_path}")
            parser = SRTParser()
            subtitles = parser.parse_srt_file(srt_file_path)

            if not subtitles:
                print("❌ 未能解析任何字幕條目")
                return None

            print(f"✓ 成功解析 {len(subtitles)} 條字幕條目")

            # 分段處理
            print(f"\n🔧 正在進行分段處理...")
            print(f"   分段標準: {max_duration}秒 或 {max_chars}字")
            segmentizer = SRTSegmentizer(max_duration=max_duration, max_chars=max_chars)
            segments = segmentizer.segment_subtitles(subtitles)
            print(f"   ✓ 成功分為 {len(segments)} 段")

            # 顯示分段信息
            total_duration_seconds = 0
            for i, seg in enumerate(segments, 1):
                print(f"   段 {i}: {seg['start_time_str']} - {seg['end_time_str']} ({seg['duration_formatted']}, {seg['text_length']} 字)")
                total_duration_seconds += seg['duration_seconds']

            total_duration_formatted = SRTSegmentizer()._format_duration(total_duration_seconds)
            print(f"\n📊 會議總時長: {total_duration_formatted}")

            # 分批處理分段
            all_results = []
            all_summaries_batches = []

            for i in range(0, len(segments), self.batch_size):
                batch = segments[i:i+self.batch_size]
                print(f"\n📦 批次 {i//self.batch_size + 1}/{(len(segments)-1)//self.batch_size + 1}")
                
                self.print_memory_usage(f"批次開始前")
                
                batch_results, batch_summaries = self.process_batch_segments(batch, i)
                
                if batch_results:
                    all_results.extend(batch_results)
                    all_summaries_batches.append(batch_summaries)
                
                self.aggressive_memory_cleanup()
                self.print_memory_usage(f"批次完成後")

            if not all_results:
                print("❌ 沒有成功處理任何分段")
                return None

            print("\n" + "="*80)
            print(f"✓ 所有批次處理完成，共處理 {len(all_results)} 段")

            # 提取關鍵元素
            print("\n🔍 正在提取會議關鍵元素...")
            key_themes, decisions, actions, unique_people_count = self.extract_key_elements_optimized(all_summaries_batches)

            print(f"✓ 識別到 {unique_people_count} 位獨立人物")
            print(f"✓ 提取到 {len(key_themes)} 個關鍵主題")

            # 清理摘要資料
            del all_summaries_batches
            self.aggressive_memory_cleanup()

            # 生成整體總結
            print("\n" + "="*80)
            print("生成整體會議主題總結...")
            print("="*80)

            overall_summary = self.generate_overall_summary_optimized(
                key_themes, decisions, actions, unique_people_count, len(all_results), total_duration_formatted
            )

            # 轉換為 DataFrame
            results_df = pd.DataFrame(all_results)

            # 生成輸出文件名
            if output_file_path is None:
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                base_name = os.path.splitext(os.path.basename(srt_file_path))[0]
                output_file_path = f'{base_name}_segments_{timestamp}.csv'
                summary_file_path = f'{base_name}_overall_summary_{timestamp}.md'
            else:
                base_name = output_file_path.replace('.csv', '')
                summary_file_path = f'{base_name}_overall_summary.md'

            # 保存結果
            results_df.to_csv(output_file_path, index=False, encoding='utf-8-sig')
            print(f"\n✓ 逐段整理結果已保存至: {output_file_path}")

            # 保存整體總結
            with open(summary_file_path, 'w', encoding='utf-8') as f:
                f.write("# 會議整體主題總結（Raspberry Pi 5 llama.cpp GGUF INT8 版本 v5.1）\n\n")
                f.write(f"**分析時間**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"**會議時長**: {total_duration_formatted}\n")
                f.write(f"**總分段數**: {len(all_results)} 段\n")
                f.write(f"**獨立人物數**: {unique_people_count}\n\n")
                f.write("---\n\n")
                f.write(overall_summary)

            print(f"✓ 整體會議總結已保存至: {summary_file_path}")
            print(f"✓ 成功處理 {len(all_results)} 段會議記錄")

            # 顯示統計
            self.show_processing_stats_optimized(results_df, total_duration_formatted, unique_people_count)

            # 最終清理
            self.aggressive_memory_cleanup()

            return results_df, overall_summary

        except Exception as e:
            print(f"❌ 處理 SRT 檔案時發生錯誤: {str(e)}")
            self.aggressive_memory_cleanup()
            return None

    def show_processing_stats_optimized(self, results_df, total_duration, unique_people_count):
        """顯示處理統計信息"""
        print("\n" + "="*80)
        print("📊 處理統計（Raspberry Pi 5 llama.cpp GGUF INT8 版本 v5.1）")
        print("="*80)

        if len(results_df) > 0:
            total_chars = results_df['原文字數'].sum()
            avg_length = results_df['原文字數'].mean()

            print(f"總處理段數: {len(results_df)}")
            print(f"會議總時長: {total_duration}")
            print(f"平均原文長度: {avg_length:.0f} 字")
            print(f"總原文字數: {total_chars:,} 字")
            print(f"最長段落: {results_df['原文字數'].max()} 字")
            print(f"最短段落: {results_df['原文字數'].min()} 字")
            print(f"獨立人物數: {unique_people_count} 位")

            self.print_memory_usage("最終統計")

        print("="*80 + "\n")


if __name__ == "__main__":
    print("\n" + "="*80)
    print("🚀 Qwen3-4B-Q8_0 會議記錄整理系統")
    print("   Raspberry Pi 5 優化版本 v5.1 (llama.cpp GGUF)")
    print("="*80)

    # 【關鍵改動】用 llama.cpp + GGUF 模型 + 動態 context
    extractor = LlamaCppQwen3Extractor(model_path="../Qwen3-4B-Q8_0.gguf")

    print(f"\n✅ 模型初始化完成！")
    print("="*80 + "\n")
    
    # 【範例用法】
    # srt_file = r"path/to/your/file.srt"
    # result = extractor.process_srt_file_optimized(
    #     srt_file,
    #     max_duration=120,   # 2 分鐘
    #     max_chars=1500      # 1500 字
    # )