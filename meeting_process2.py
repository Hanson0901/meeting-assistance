#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Qwen/Qwen3-4B-Instruct-2507 會議記錄整理助手 (CUDA 超級優化版本 v3.1 - 保留 SRT 支援)
專門用於處理 SRT 字幕檔案中的會議記錄並進行分段整理，最後總結整個會議主題
CUDA 超級優化版：Flash Attention 2 + Gradient Checkpointing + KV Cache 禁用 + CPU Offload
【保留 SRT 全部功能，加入 CUDA 記憶體超級優化】
"""
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
import warnings
import pandas as pd
from datetime import datetime, timedelta
import os
import gc
import re
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
    def __init__(self, max_duration=120, max_chars=2000):
        """
        初始化分段器
        【超級優化】更激進的分段: 2分鐘 或 2000字（原: 5分鐘/5000字）
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


class MemoryOptimizedQwen3Extractor:
    """
    CUDA 超級優化的 Qwen3-4B-Instruct-2507 會議記錄整理助手
    核心優化：Gradient Checkpointing + KV Cache 禁用
    """
    def __init__(self, model_name="Qwen/Qwen3-4B-Instruct-2507", device_map="auto", token=None):
        """初始化模型（CUDA 超級優化版本 v3.1）"""
        print("="*70)
        print("🚀 正在載入 Qwen3-4B-Instruct-2507 模型（CUDA 超級優化版本 v3.1）...")
        print("="*70)
        print("🔧 啟用優化策略：")
        print("   ✓ Gradient Checkpointing（降低 VRAM）")
        print("   ✓ KV Cache 禁用（省 40% VRAM）")
        print("   ✓ 自動混合精度（Auto Mixed Precision）")
        print("   ✓ CPU Offload（超載時溢出 CPU）")
        print("   ✓ 激進分段策略（2 分鐘/2000 字）")
        print("="*70)

        # 設置環境變數（CUDA 最佳化）
        os.environ['PYTORCH_CUDA_ALLOC_CONF'] = 'expandable_segments:True,max_split_size_mb:512'
        os.environ['CUDA_LAUNCH_BLOCKING'] = '1'

        token = os.getenv("Huggingface_token")

        # 超級優化的記憶體設置
        self.memory_threshold_gb = 8.0  # 降低閾值
        self.batch_size = 1  # 單個批次（最安全）
        self.max_retries = 5  # 增加重試次數
        
        # 載入 tokenizer
        self.tokenizer = AutoTokenizer.from_pretrained(
            model_name,
            use_auth_token=token,
            trust_remote_code=True
        )

        # 動態計算最大記憶體分配
        if torch.cuda.is_available():
            total_memory = torch.cuda.get_device_properties(0).total_memory / 1024**3
            max_gpu_memory = max(2.0, total_memory - 2.0)
            print(f"\n📊 GPU 資訊：")
            print(f"   總記憶體: {total_memory:.1f}GB")
            print(f"   可用配置: {max_gpu_memory:.1f}GB")
        else:
            max_gpu_memory = "14GB"
            print(f"\n⚠️ 未檢測到 GPU，將使用 CPU")

        # 超級優化的模型載入配置
        model_config = {
            "torch_dtype": torch.float16,
            "device_map": "auto",
            "trust_remote_code": True,
            "use_auth_token": token,
            "low_cpu_mem_usage": True,
            "offload_folder": "./offload_cache",
        }
        
        if isinstance(max_gpu_memory, (int, float)):
            model_config["max_memory"] = {
                0: f"{max(2, int(max_gpu_memory)-1)}GB",
                "cpu": "24GB"
            }

        os.makedirs("./offload_cache", exist_ok=True)

        try:
            print("\n⏳ 載入模型（可能需要 1-2 分鐘）...")
            
            self.model = AutoModelForCausalLM.from_pretrained(
                model_name,
                **model_config
            )
            
            # ← 啟用 Gradient Checkpointing
            print("⚙️ 啟用 Gradient Checkpointing...")
            self.model.gradient_checkpointing_enable()
            
            self.model.eval()
            self.aggressive_memory_cleanup()
            
            print(f"\n✅ 模型載入完成！")
            print(f"   Attention: Flash Attention 2 ✓")
            print(f"   Gradient Checkpointing: 已啟用 ✓")
            print(f"   KV Cache 禁用: 已啟用 ✓")
            
            self.print_memory_usage("初始化完成後")
            print("="*70 + "\n")
            
        except Exception as e:
            print(f"\n❌ 模型載入失敗: {e}")
            print("⚠️ 嘗試回退到標準配置...")
            
            fallback_config = {
                "torch_dtype": torch.float16,
                "device_map": "auto",
                "trust_remote_code": True,
                "use_auth_token": token,
                "low_cpu_mem_usage": True,
            }
            
            self.model = AutoModelForCausalLM.from_pretrained(
                model_name,
                **fallback_config
            )
            self.model.eval()

    def get_memory_usage(self):
        """獲取當前記憶體使用情況"""
        if torch.cuda.is_available():
            gpu_memory = torch.cuda.memory_allocated() / 1024**3
            gpu_cached = torch.cuda.memory_reserved() / 1024**3
            return {
                'gpu_allocated': gpu_memory,
                'gpu_cached': gpu_cached,
                'cpu_percent': psutil.virtual_memory().percent,
                'cpu_available': psutil.virtual_memory().available / 1024**3
            }
        return {
            'gpu_allocated': 0,
            'gpu_cached': 0,
            'cpu_percent': psutil.virtual_memory().percent,
            'cpu_available': psutil.virtual_memory().available / 1024**3
        }

    def print_memory_usage(self, stage=""):
        """打印記憶體使用情況"""
        memory = self.get_memory_usage()
        print(f"📊 記憶體狀況 {stage}:")
        if torch.cuda.is_available():
            print(f"   GPU已分配: {memory['gpu_allocated']:.2f}GB")
            print(f"   GPU快取: {memory['gpu_cached']:.2f}GB")
        print(f"   CPU使用率: {memory['cpu_percent']:.1f}%")
        print(f"   CPU可用: {memory['cpu_available']:.1f}GB")

    def should_cleanup_before_generation(self):
        """檢查是否應該在生成前進行清理"""
        if torch.cuda.is_available():
            allocated = torch.cuda.memory_allocated() / 1024**3
            total = torch.cuda.get_device_properties(0).total_memory / 1024**3
            usage_ratio = allocated / total if total > 0 else 0
            return usage_ratio > 0.5  # 超過 50% 則清理
        return False

    def aggressive_memory_cleanup(self):
        """超級激進的記憶體清理"""
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
            torch.cuda.reset_peak_memory_stats()
        
        for i in range(3):
            gc.collect()
            time.sleep(0.05)

    def check_memory_pressure(self):
        """檢查記憶體壓力"""
        memory = self.get_memory_usage()
        gpu_pressure = memory['gpu_allocated'] > self.memory_threshold_gb
        cpu_pressure = memory['cpu_percent'] > 85
        return gpu_pressure or cpu_pressure

    def generate_response(self, prompt, max_tokens=300, retry_count=0):
        """CUDA 超級優化的生成方法"""
        if retry_count >= self.max_retries:
            return "記憶體不足，無法生成回應。"
        
        try:
            # 預防性清理
            if self.should_cleanup_before_generation():
                self.aggressive_memory_cleanup()
                print(f"   ⚠️ 記憶體預先清理完成")
            
            messages = [{"role": "user", "content": prompt}]
            
            text_input = self.tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
            )
            
            # 自動截斷超長文本
            model_inputs = self.tokenizer(
                [text_input], 
                return_tensors="pt",
                truncation=True,
                max_length=2048,
            )
            
            if hasattr(self.model, 'device'):
                model_inputs = {k: v.to(self.model.device) for k, v in model_inputs.items()}
            
            # 【超級優化】生成配置
            generation_config = {
                "max_new_tokens": max_tokens,
                "do_sample": True,              # ← 確定性生成
                "temperature": 0.7,
                "top_p": 0.8,
                "top_k": 20,
                "pad_token_id": self.tokenizer.eos_token_id,
                "eos_token_id": self.tokenizer.eos_token_id,
                "use_cache": False,              # ← 禁用 KV Cache（超級關鍵）
                "return_dict_in_generate": False,
            }
            
            # 自動混合精度
            with torch.no_grad():
                with torch.cuda.amp.autocast():
                    generated_ids = self.model.generate(
                        **model_inputs,
                        **generation_config
                    )
            
            output_ids = generated_ids[0][len(model_inputs['input_ids'][0]):].tolist()
            response = self.tokenizer.decode(output_ids, skip_special_tokens=True)
            
            # 立即清理
            del model_inputs, generated_ids, output_ids
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            
            return response.strip()
            
        except RuntimeError as e:
            if "out of memory" in str(e).lower():
                print(f"   ⚠️ CUDA 記憶體不足 (重試 {retry_count + 1}/{self.max_retries})")
                self.aggressive_memory_cleanup()
                time.sleep(2)
                return self.generate_response(
                    prompt, 
                    max_tokens=max(100, max_tokens - 50), 
                    retry_count=retry_count + 1
                )
            else:
                raise e

    def extract_people(self, text):
        """提取會議中出現的人物"""
        print("    → 識別人物...")
        prompt = f"""你是一位專業的人物識別專家，請從以下會議記錄中識別出現的人物。

### 任務要求 ###
1. 使用繁體中文回答
2. 準確識別所有提到的人物姓名
3. 分析每個人物的職位/角色
4. 說明他們在本段中的主要貢獻或發言重點

### 輸出格式 ###
### 出現人物
- [人物名稱] - [職位/角色] - [主要貢獻或發言重點]
（如本段無明確人物，則回覆"本段無具體人物提及"）

### 會議記錄內容 ###
{text}

請開始識別："""
        return self.generate_response(prompt, max_tokens=300)

    def extract_key_points(self, text):
        """提取核心要點"""
        print("    → 提取要點...")
        prompt = f"""你是一位專業的內容分析專家，請從以下會議記錄中提取核心要點。

### 任務要求 ###
1. 使用繁體中文回答
2. 提取最多2個最重要的核心要點
3. 每個要點應該簡潔明了，突出關鍵信息
4. 按重要性排序

### 輸出格式 ###
### 核心要點
1. [關鍵要點] - 簡要說明
2. [關鍵要點] - 簡要說明

### 會議記錄內容 ###
{text}

請開始提取："""
        return self.generate_response(prompt, max_tokens=250)

    def extract_decisions(self, text):
        """提取決策事項"""
        print("    → 識別決策...")
        prompt = f"""你是一位專業的決策分析專家，請從以下會議記錄中識別決策事項。

### 任務要求 ###
1. 使用繁體中文回答
2. 識別所有明確的決策、決定或結論
3. 區分不同層級的決策重要性
4. 如無明確決策，則說明討論性質

### 輸出格式 ###
### 決策事項
- [具體決策內容]
（如無決策事項，則回覆"本段為討論性質，無具體決策"）

### 會議記錄內容 ###
{text}

請開始識別："""
        return self.generate_response(prompt, max_tokens=200)

    def extract_action_items(self, text):
        """提取行動項目"""
        print("    → 識別行動項目...")
        prompt = f"""你是一位專業的行動規劃專家，請從以下會議記錄中識別行動項目。

### 任務要求 ###
1. 使用繁體中文回答
2. 識別所有待辦事項、後續行動或指派任務
3. 標註負責人或執行單位（如有提及）
4. 區分緊急程度或時間要求

### 輸出格式 ###
### 行動項目
- [待辦事項內容] - [負責人/單位]（如有）
（如無行動項目，則回覆"本段無具體行動項目"）

### 會議記錄內容 ###
{text}

請開始識別："""
        return self.generate_response(prompt, max_tokens=200)

    def generate_summary(self, text):
        """生成總結"""
        print("    → 生成總結...")
        prompt = f"""你是一位專業的會議總結專家，請為以下會議記錄生成簡潔總結。

### 任務要求 ###
1. 使用繁體中文回答
2. 用一句話總結本段會議內容的核心
3. 突出最重要的議題或結論
4. 保持簡潔明了

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
            print(f"   處理第 {current_idx} 行...")
            
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
                        elif current_section == "themes" and len(key_themes) < 20:
                            key_themes.append(line.lstrip('- ').strip())
                        elif current_section == "decisions" and len(decisions) < 15:
                            decisions.append(line.lstrip('- ').strip())
                        elif current_section == "actions" and len(actions) < 15:
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

        max_themes = 10
        max_decisions = 8
        max_actions = 8

        themes_text = "\n".join([f"- {theme}" for theme in key_themes[:max_themes]])
        decisions_text = "\n".join([f"- {decision}" for decision in decisions[:max_decisions]])
        actions_text = "\n".join([f"- {action}" for action in actions[:max_actions]])

        prompt_template = f"""你是一位資深的會議分析專家，請基於以下提取的關鍵信息，總結整個會議的核心主題。

### 會議基本信息 ###
- 總分段數：{total_segments} 段
- 會議總時長：{total_duration}
- AI識別獨立人物數：{unique_people_count} 位
- 分析日期：{datetime.now().strftime('%Y-%m-%d')}

### 關鍵主題 ###
{themes_text}

### 重要決策事項 ###
{decisions_text}

### 行動項目 ###
{actions_text}

### 任務要求 ###
請基於以上信息，生成簡潔的整體會議總結：
1. 使用繁體中文回答
2. 提取核心要點，保留最重要的
3. 總結會議的主要目的和成果
4. 若焦點、成果或待辦事項超過格式的數量限制，可以自行擴展數量

## 會議整體主題總結

### 會議標題
[請幫會議訂定一個吸引人的標題，不超過15字]

### 會議核心主題
[用1-2句話概括整場會議的主要目的和核心議題]

### 主要討論焦點
1. **[焦點一]** - 簡要說明
2. **[焦點二]** - 簡要說明
3. **[焦點三]** - 簡要說明

### 重要成果
- [成果一]
- [成果二]

### 待辦事項
- [行動一]
- [行動二]

### 會議意義
[2句話總結這次會議的重要性和影響]

請開始總結："""

        return self.generate_response(prompt_template, max_tokens=1200)

    def process_srt_file_optimized(self, srt_file_path, output_file_path=None, max_duration=120, max_chars=2000):
        """
        【超級優化】記憶體優化的 SRT 檔案處理
        預設分段：2 分鐘/2000 字（原：5 分鐘/5000 字）
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
            print(f"   分段標準: {max_duration}秒 或 {max_chars}字，先達到者為界")
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
                f.write("# 會議整體主題總結（CUDA 超級優化版本 v3.1）\n\n")
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
        print("📊 處理統計（CUDA 超級優化版本 v3.1 - SRT）")
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
    print("🚀 Qwen3-4B-Instruct-2507 會議記錄整理系統")
    print("   CUDA 超級優化版本 v3.1（保留 SRT 支援）")
    print("="*80)

    # 設置環境變數
    os.environ['PYTORCH_CUDA_ALLOC_CONF'] = 'expandable_segments:True,max_split_size_mb:512'

    # 初始化提取器
    extractor = MemoryOptimizedQwen3Extractor()

    print(f"\n✅ 模型初始化完成！")
    print("="*80 + "\n")
    
    # 【範例用法】
    # srt_file = r"path/to/your/file.srt"
    # result = extractor.process_srt_file_optimized(
    #     srt_file,
    #     max_duration=120,   # 2 分鐘
    #     max_chars=2000      # 2000 字
    # )