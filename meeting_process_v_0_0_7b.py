#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Qwen/Qwen3-14B-AWQ 會議記錄整理助手 (記憶體優化版本)
專門用於處理CSV文件中的會議記錄並進行逐行重點整理，最後總結整個會議主題
優化版：解決CUDA記憶體不足問題，加強記憶體管理和批次處理
"""
import os
import torch
# Skip importing torchvision to avoid binary mismatches when transformers loads image utilities.
os.environ.setdefault("DISABLE_TORCHVISION_IMPORT", "1")
from transformers import AutoModelForCausalLM, AutoTokenizer
import warnings
import pandas as pd
from datetime import datetime
import gc
import re
import psutil
import time
warnings.filterwarnings("ignore")


class MemoryOptimizedQwen2Extractor:
    """
    記憶體優化的Qwen/Qwen2.5-7B-Instruct-1M會議記錄整理助手
    """
    def __init__(self, model_name="Qwen/Qwen2.5-7B-Instruct-1M", device_map="auto", token=None):
        """
        初始化模型和tokenizer（記憶體優化版本）
        """
        print("正在載入Qwen/Qwen2.5-7B-Instruct-1M模型（記憶體優化版本）...")
        print("注意：首次載入可能需要數分鐘時間下載模型檔案")

        # 設置授權Token
        token = os.getenv("Huggingface_token")

        # 記憶體優化設置
        self.memory_threshold_gb = 12.0  # 記憶體使用閾值
        self.batch_size = 5  # 批次處理大小
        self.max_retries = 3  # 重試次數

        # 載入tokenizer
        self.tokenizer = AutoTokenizer.from_pretrained(
            model_name,
            use_auth_token=token
        )

        # 記憶體優化的模型載入配置
        model_config = {
            "torch_dtype": torch.float16,  # 使用float16以節省記憶體
            "device_map": device_map,
            "trust_remote_code": True,
            "use_auth_token": token,
            "low_cpu_mem_usage": True,  # 啟用低CPU記憶體使用
            "offload_folder": "./offload_cache",  # 設置offload資料夾
        }

        # 建立offload資料夾
        os.makedirs("./offload_cache", exist_ok=True)

        # 載入模型
        self.model = AutoModelForCausalLM.from_pretrained(
            model_name,
            **model_config
        )

        # 設置模型為評估模式
        self.model.eval()

        # 初始記憶體清理
        self.aggressive_memory_cleanup()

        print(f"模型載入完成！")
        print(f"模型設備: {self.model.device}")
        print(f"模型精度: {self.model.dtype}")
        self.print_memory_usage("初始化完成後")

    def get_memory_usage(self):
        """
        獲取當前記憶體使用情況
        """
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
        """
        打印記憶體使用情況
        """
        memory = self.get_memory_usage()
        print(f"📊 記憶體狀況 {stage}:")
        print(f"   GPU已分配: {memory['gpu_allocated']:.2f}GB")
        print(f"   GPU快取: {memory['gpu_cached']:.2f}GB") 
        print(f"   CPU使用率: {memory['cpu_percent']:.1f}%")
        print(f"   CPU可用: {memory['cpu_available']:.1f}GB")

    def aggressive_memory_cleanup(self):
        """
        積極的記憶體清理
        """
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
        gc.collect()
        
        # 強制Python垃圾收集
        for i in range(3):
            gc.collect()
        
        time.sleep(0.1)  # 給系統一點時間

    def check_memory_pressure(self):
        """
        檢查記憶體壓力
        """
        memory = self.get_memory_usage()
        gpu_pressure = memory['gpu_allocated'] > self.memory_threshold_gb
        cpu_pressure = memory['cpu_percent'] > 85
        return gpu_pressure or cpu_pressure

    def generate_response(self, prompt, max_tokens=400, retry_count=0):
        """
        記憶體優化的生成回應方法
        """
        if retry_count >= self.max_retries:
            return "記憶體不足，無法生成回應"
        
        try:
            # 檢查記憶體壓力
            if self.check_memory_pressure():
                self.aggressive_memory_cleanup()
                print(f"⚠️ 記憶體壓力過高，已執行清理")

            # 構建消息格式
            messages = [{"role": "user", "content": prompt}]

            # 應用聊天模板
            text_input = self.tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
            )

            # 編碼輸入
            model_inputs = self.tokenizer([text_input], return_tensors="pt")

            # 移動到模型設備
            if hasattr(self.model, 'device'):
                model_inputs = {k: v.to(self.model.device) for k, v in model_inputs.items()}

            # 記憶體優化的生成參數
            generation_config = {
                "max_new_tokens": max_tokens,
                "temperature": 0.3,
                "top_p": 0.8,
                "top_k": 20,
                "do_sample": True,
                "pad_token_id": self.tokenizer.eos_token_id,
                "eos_token_id": self.tokenizer.eos_token_id,
                "use_cache": False,  # 禁用快取以節省記憶體
            }

            # 生成回應
            with torch.no_grad():  # 確保不計算梯度
                generated_ids = self.model.generate(
                    **model_inputs,
                    **generation_config
                )

            # 解碼輸出
            output_ids = generated_ids[0][len(model_inputs['input_ids'][0]):].tolist()
            response = self.tokenizer.decode(output_ids, skip_special_tokens=True)

            # 立即清理記憶體
            del model_inputs, generated_ids, output_ids
            self.aggressive_memory_cleanup()

            return response.strip()

        except RuntimeError as e:
            if "out of memory" in str(e).lower():
                print(f"❌ CUDA記憶體不足，嘗試重試 {retry_count + 1}/{self.max_retries}")
                self.aggressive_memory_cleanup()
                time.sleep(1)  # 等待一秒讓記憶體釋放
                return self.generate_response(prompt, max_tokens, retry_count + 1)
            else:
                raise e

    def ai_identify_same_person(self, person1_info, person2_info):
        """
        記憶體優化的AI人物識別
        """
        # 簡化的比較邏輯，減少AI呼叫次數
        if self.simple_name_match(person1_info, person2_info):
            return True
        
        # 只在必要時使用AI
        if self.check_memory_pressure():
            return self.traditional_name_match(person1_info, person2_info)
        
        prompt = f"""你是一位專業的人物識別專家，請判斷以下兩個人物描述是否指向同一個人。

### 人物描述一 ###
{person1_info}

### 人物描述二 ###
{person2_info}

請只回答：是/否"""

        response = self.generate_response(prompt, max_tokens=10)
        response_clean = response.strip().lower()
        
        if "是" in response_clean:
            return True
        elif "否" in response_clean:
            return False
        else:
            return self.traditional_name_match(person1_info, person2_info)

    def simple_name_match(self, person1_info, person2_info):
        """
        簡單的姓名匹配（減少AI使用）
        """
        name1 = self.extract_person_name(person1_info)
        name2 = self.extract_person_name(person2_info)
        
        if not name1 or not name2:
            return False
        
        # 完全匹配
        if name1 == name2:
            return True
        
        # 包含關係
        if (name1 in name2 or name2 in name1) and min(len(name1), len(name2)) >= 2:
            return True
        
        return False

    def traditional_name_match(self, person1_info, person2_info):
        """
        傳統的姓名匹配方法
        """
        return self.simple_name_match(person1_info, person2_info)

    def extract_person_name(self, person_info):
        """
        從人物信息中提取人物姓名
        """
        separators = ['-', '：', ':', '（', '(', '，', ',']
        person_name = person_info.strip()

        for sep in separators:
            if sep in person_name:
                person_name = person_name.split(sep)[0].strip()
                break

        prefixes_to_remove = ['委員', '主席', '顧問', '老師', '教授', '先生', '女士', '議員', '代表']
        for prefix in prefixes_to_remove:
            if person_name.startswith(prefix):
                person_name = person_name[len(prefix):].strip()

        person_name = re.sub(r'[（(][^)）]*[)）]', '', person_name).strip()
        return person_name

    def merge_people_info_optimized(self, people_list):
        """
        記憶體優化的人物信息合併
        """
        if not people_list:
            return [], 0

        print(f"     使用優化版人物識別...")
        print(f"     原始人物條目數: {len(people_list)}")

        valid_people = []
        for person_info in people_list:
            if person_info and "本段無具體人物提及" not in person_info:
                valid_people.append(person_info)

        if not valid_people:
            return [], 0

        # 分批處理以減少記憶體使用
        merged_groups = []
        processed_indices = set()
        batch_size = 10  # 小批次處理

        for i in range(0, len(valid_people), batch_size):
            batch = valid_people[i:i+batch_size]
            batch_start_idx = i
            
            for j, person1 in enumerate(batch):
                actual_idx = batch_start_idx + j
                if actual_idx in processed_indices:
                    continue

                current_group = {
                    'representative_info': person1,
                    'all_infos': [person1],
                    'appearances': 1,
                    'name': self.extract_person_name(person1)
                }
                processed_indices.add(actual_idx)

                # 與剩餘人物比較
                for k, person2 in enumerate(valid_people[actual_idx+1:], actual_idx+1):
                    if k in processed_indices:
                        continue

                    if self.ai_identify_same_person(person1, person2):
                        current_group['all_infos'].append(person2)
                        current_group['appearances'] += 1
                        processed_indices.add(k)
                        
                        if len(person2) > len(current_group['representative_info']):
                            current_group['representative_info'] = person2

                merged_groups.append(current_group)
                
                # 定期清理記憶體
                if len(merged_groups) % 5 == 0:
                    self.aggressive_memory_cleanup()

        # 生成最終結果
        final_people = []
        for group in merged_groups:
            if group['appearances'] > 1:
                enhanced_info = f"{group['representative_info']} (AI識別出現 {group['appearances']} 次)"
            else:
                enhanced_info = group['representative_info']
            final_people.append(enhanced_info)

        unique_count = len(merged_groups)
        print(f"     優化識別後獨立人物數: {unique_count}")
        return final_people, unique_count

    def process_batch_records(self, batch_records, batch_start_idx):
        """
        批次處理會議記錄
        """
        batch_results = []
        batch_summaries = []
        
        for i, record in enumerate(batch_records):
            current_idx = batch_start_idx + i + 1
            print(f"   處理第 {current_idx} 行...")
            
            try:
                # 檢查記憶體壓力
                if self.check_memory_pressure():
                    self.aggressive_memory_cleanup()
                    print(f"   記憶體清理完成")

                summary = self.process_single_record(record['原文'], current_idx)
                batch_summaries.append(summary)
                
                result = {
                    '行號': current_idx,
                    '原文': record['原文'],
                    '原文長度': len(record['原文']),
                    '重點整理': summary,
                    '處理時間': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                
                # 保留其他欄位
                for col, value in record.items():
                    if col != '原文':
                        result[f'原始_{col}'] = value
                
                batch_results.append(result)
                print(f"     第 {current_idx} 行處理完成")
                
            except Exception as e:
                print(f"     第 {current_idx} 行處理失敗: {str(e)}")
                continue
        
        return batch_results, batch_summaries

    def extract_people(self, text):
        """
        提取會議中出現的人物
        """
        print("    -> 正在識別出現人物...")
        
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
        """
        提取核心要點
        """
        print("    -> 正在提取核心要點...")
        
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
        """
        提取決策事項
        """
        print("    -> 正在識別決策事項...")
        
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
        """
        提取行動項目
        """
        print("    -> 正在識別行動項目...")
        
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
        """
        生成總結
        """
        print("    -> 正在生成段落總結...")
        
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
        
        return self.generate_response(prompt, max_tokens=100)

    def process_single_record(self, text, index):
        """
        處理單個會議記錄（記憶體優化）
        """
        print(f"   開始處理第 {index} 行...")

        try:
            # 模塊1：提取人物
            people_result = self.extract_people(text)
            self.aggressive_memory_cleanup()

            # 模塊2：提取核心要點
            keypoints_result = self.extract_key_points(text)
            self.aggressive_memory_cleanup()

            # 模塊3：提取決策事項
            decisions_result = self.extract_decisions(text)
            self.aggressive_memory_cleanup()

            # 模塊4：提取行動項目
            actions_result = self.extract_action_items(text)
            self.aggressive_memory_cleanup()

            # 模塊5：生成總結
            summary_result = self.generate_summary(text)
            self.aggressive_memory_cleanup()

            # 整合所有模塊結果
            integrated_result = f"""## 會議記錄整理

{people_result}

{keypoints_result}

{decisions_result}

{actions_result}

{summary_result}"""

            return integrated_result
            
        except Exception as e:
            print(f"   處理第 {index} 行時發生錯誤: {str(e)}")
            return f"處理錯誤: {str(e)}"

    def extract_key_elements_optimized(self, all_summaries_batch):
        """
        記憶體優化的關鍵元素提取（批次處理）
        """
        key_themes = []
        decisions = []
        actions = []
        raw_people_info = []

        # 分批處理摘要
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
                    elif "### 總結" in line:
                        current_section = "summary"
                    elif line and line.startswith(('-', '1.', '2.', '3.')):
                        if current_section == "people":
                            person_info = line.lstrip('- 123.').strip()
                            if person_info and "本段無具體人物提及" not in person_info:
                                raw_people_info.append(person_info)
                        elif current_section == "themes" and len(key_themes) < 20:
                            key_themes.append(line.lstrip('- 123.').strip())
                        elif current_section == "decisions" and len(decisions) < 15:
                            decisions.append(line.lstrip('- ').strip())
                        elif current_section == "actions" and len(actions) < 15:
                            actions.append(line.lstrip('- ').strip())

        # 使用優化版本的人物識別去重處理
        print("\n 開始優化版人物識別去重...")
        unique_people_info, unique_people_count = self.merge_people_info_optimized(raw_people_info)

        return key_themes, decisions, actions, unique_people_info, unique_people_count

    def generate_overall_summary_optimized(self, key_themes, decisions, actions, people_info, unique_people_count, total_records):
        """
        記憶體優化的整體會議總結生成
        """
        print("\n正在生成整體會議主題總結（記憶體優化）...")

        # 限制輸入資料大小以減少記憶體使用
        max_themes = 10
        max_decisions = 8
        max_actions = 8
        max_people = 10

        themes_text = "\n".join([f"- {theme}" for theme in key_themes[:max_themes]])
        decisions_text = "\n".join([f"- {decision}" for decision in decisions[:max_decisions]])
        actions_text = "\n".join([f"- {action}" for action in actions[:max_actions]])
        people_text = "\n".join([f"- {person}" for person in people_info[:max_people]])

        prompt_template = f"""你是一位資深的會議分析專家，請基於以下提取的關鍵信息，總結整個會議的核心主題。

### 會議基本信息 ###
- 總發言段數：{total_records} 段
- AI識別到的獨立人物數：{unique_people_count} 位
- 分析日期：{datetime.now().strftime('%Y-%m-%d')}

### 關鍵人物（已去重） ###
{people_text}

### 關鍵主題 ###
{themes_text}

### 重要決策事項 ###
{decisions_text}

### 行動項目 ###
{actions_text}

### 任務要求 ###
請基於以上信息，生成簡潔的整體會議總結：
1. 使用繁體中文回答
2. 重點分析關鍵人物的角色和貢獻
3. 提取核心要點，保留最重要的
4. 對於多次出現人物，請特別標註其重要性

## 會議整體主題總結

### 會議標題
[請幫會議訂定一個吸引人的標題，不超過15字]

### 會議核心主題
[用1-2句話概括整場會議的主要目的和核心議題]

### 關鍵人物分析（共{unique_people_count}位獨立人物）
1. **[重要人物一]** - [職位] - [主要貢獻和角色]
2. **[重要人物二]** - [職位] - [主要貢獻和角色]
3. **[重要人物三]** - [職位] - [主要貢獻和角色]

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

        # 使用較小的max_tokens以減少記憶體使用
        return self.generate_response(prompt_template, max_tokens=1800)

    def process_csv_file_optimized(self, csv_file_path, output_file_path=None):
        """
        記憶體優化的CSV文件處理
        """
        try:
            print(f"正在讀取CSV文件: {csv_file_path}")
            df = pd.read_csv(csv_file_path, encoding='utf-8')

            if '原文' not in df.columns:
                print("錯誤：CSV文件中沒有找到'原文'欄位")
                return None

            print(f"找到 {len(df)} 行會議記錄")
            print("使用記憶體優化處理模式...")

            # 過濾有效記錄
            valid_records = []
            for index, row in df.iterrows():
                original_text = str(row['原文']).strip()
                if original_text and original_text != 'nan' and len(original_text) >= 10:
                    record = {'原文': original_text}
                    for col in df.columns:
                        if col != '原文':
                            record[col] = row[col]
                    valid_records.append(record)

            if not valid_records:
                print("沒有找到有效的會議記錄")
                return None

            print(f"有效記錄數：{len(valid_records)}")

            # 分批處理記錄
            all_results = []
            all_summaries_batches = []
            total_original_chars = 0

            for i in range(0, len(valid_records), self.batch_size):
                batch = valid_records[i:i+self.batch_size]
                print(f"\n 處理批次 {i//self.batch_size + 1}/{(len(valid_records)-1)//self.batch_size + 1}...")
                
                self.print_memory_usage(f"批次 {i//self.batch_size + 1} 開始前")
                
                # 處理當前批次
                batch_results, batch_summaries = self.process_batch_records(batch, i)
                
                if batch_results:
                    all_results.extend(batch_results)
                    all_summaries_batches.append(batch_summaries)
                    
                    # 累計字數
                    for result in batch_results:
                        total_original_chars += result['原文長度']
                
                # 批次間的積極記憶體清理
                self.aggressive_memory_cleanup()
                self.print_memory_usage(f"批次 {i//self.batch_size + 1} 完成後")

            if not all_results:
                print("沒有成功處理任何記錄")
                return None

            print("\n" + "-" * 80)
            print(f"所有批次處理完成，共處理 {len(all_results)} 條記錄")

            # 提取關鍵元素（記憶體優化版本）
            print("\n 正在提取會議關鍵元素（記憶體優化）...")
            key_themes, decisions, actions, people_info, unique_people_count = self.extract_key_elements_optimized(all_summaries_batches)

            print(f" 識別到 {unique_people_count} 位獨立人物")
            print(f" 提取到 {len(key_themes)} 個關鍵主題")
            print(f" 提取到 {len(decisions)} 個決策事項")
            print(f" 提取到 {len(actions)} 個行動項目")

            # 清理摘要資料以節省記憶體
            del all_summaries_batches
            self.aggressive_memory_cleanup()

            # 生成整體總結（記憶體優化版本）
            print("\n" + "="*80)
            print("開始生成整體會議主題總結（記憶體優化）")
            print("="*80)

            overall_summary = self.generate_overall_summary_optimized(
                key_themes, decisions, actions, people_info, unique_people_count, len(all_results)
            )

            print("\n 整體會議主題總結完成！")

            # 轉換為DataFrame
            results_df = pd.DataFrame(all_results)

            # 生成輸出文件名
            if output_file_path is None:
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                output_file_path = f'meeting_summary_optimized_{timestamp}.csv'
                summary_file_path = f'meeting_overall_summary_optimized_{timestamp}.md'
                people_file_path = f'meeting_people_list_optimized_{timestamp}.csv'
            else:
                base_name = output_file_path.replace('.csv', '')
                summary_file_path = f'{base_name}_overall_summary.md'
                people_file_path = f'{base_name}_people_list.csv'

            # 保存逐行整理結果
            results_df.to_csv(output_file_path, index=False, encoding='utf-8-sig')
            print(f"\n 逐行整理結果已保存至: {output_file_path}")

            # 匯出人物信息
            people_df = self.export_people_to_csv_optimized(people_info, people_file_path)

            # 保存整體會議總結
            with open(summary_file_path, 'w', encoding='utf-8') as f:
                f.write("# 會議整體主題總結（記憶體優化版本）\n\n")
                f.write(f"**分析時間**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"**會議記錄總數**: {len(all_results)} 段\n")
                f.write(f"**總字數**: {total_original_chars:,} 字\n")
                f.write(f"**識別獨立人物數**: {unique_people_count}\n")
                f.write(f"**提取關鍵主題數**: {len(key_themes)}\n")
                f.write(f"**決策事項數**: {len(decisions)}\n")
                f.write(f"**行動項目數**: {len(actions)}\n\n")
                f.write("---\n\n")
                f.write(overall_summary)

            print(f" 整體會議主題總結已保存至: {summary_file_path}")
            print(f" 成功處理 {len(all_results)} 條記錄")

            # 顯示處理統計
            self.show_processing_stats_optimized(results_df, overall_summary, people_info, unique_people_count)

            # 最終記憶體清理
            self.aggressive_memory_cleanup()

            return results_df, overall_summary, people_df

        except Exception as e:
            print(f"處理CSV文件時發生錯誤: {str(e)}")
            self.aggressive_memory_cleanup()
            return None

    def export_people_to_csv_optimized(self, people_info, output_path):
        """
        記憶體優化的人物信息匯出
        """
        print(f"\n 正在匯出人物信息為CSV...")

        people_data = []
        for i, person_info in enumerate(people_info, 1):
            parsed = self.parse_person_info(person_info)
            people_data.append({
                '序號': i,
                '姓名': parsed['name'],
                '職位/角色': parsed['position'],
                '主要貢獻': parsed['contribution'],
                '出現次數': parsed['appearances'],
                '完整描述': parsed['full_info']
            })

        people_df = pd.DataFrame(people_data)
        people_df = people_df.sort_values('出現次數', ascending=False).reset_index(drop=True)
        people_df['序號'] = range(1, len(people_df) + 1)

        people_df.to_csv(output_path, index=False, encoding='utf-8-sig')

        print(f" 人物信息已匯出至: {output_path}")
        print(f" 共匯出 {len(people_df)} 位獨立人物")

        return people_df

    def parse_person_info(self, person_info):
        """
        解析人物信息
        """
        clean_info = re.sub(r'\s*\(AI識別出現\s*\d+\s*次\)', '', person_info).strip()
        parts = clean_info.split('-')

        name = parts[0].strip() if len(parts) > 0 else ""
        position = parts[1].strip() if len(parts) > 1 else ""
        contribution = parts[2].strip() if len(parts) > 2 else ""

        appearance_match = re.search(r'\(AI識別出現\s*(\d+)\s*次\)', person_info)
        appearances = int(appearance_match.group(1)) if appearance_match else 1

        return {
            'name': name,
            'position': position,
            'contribution': contribution,
            'appearances': appearances,
            'full_info': person_info
        }

    def show_processing_stats_optimized(self, results_df, overall_summary=None, people_info=None, unique_people_count=0):
        """
        顯示處理統計信息（記憶體優化版本）
        """
        print("\n" + "="*60)
        print("處理統計（記憶體優化版本）")
        print("="*60)

        if len(results_df) > 0:
            avg_original_length = results_df['原文長度'].mean()
            total_original_chars = results_df['原文長度'].sum()

            print(f"總處理行數: {len(results_df)}")
            print(f"平均原文長度: {avg_original_length:.0f} 字")
            print(f"總原文字數: {total_original_chars:,} 字")
            print(f"最長原文: {results_df['原文長度'].max()} 字")
            print(f"最短原文: {results_df['原文長度'].min()} 字")

            if people_info and unique_people_count > 0:
                print(f"\n 優化版人物識別統計:")
                print(f"識別到的獨立人物總數: {unique_people_count} 位")
                print(f"人物信息條目總數: {len(people_info)} 條")

            self.print_memory_usage("最終統計")

        print("="*60)


def process_meeting_records_optimized():
    """
    記憶體優化的主要處理函數
    """
    csv_file = r"/home/cgu-csie/meeting-assistence/meeting_record/project_test_1.csv"

    if not os.path.exists(csv_file):
        print(f"錯誤：找不到文件 {csv_file}")
        print("請確保CSV文件在當前目錄下")
        return

    try:
        print("="*60)
        print("Qwen3-4B-Instruct-2507 會議記錄整理系統")
        print("記憶體優化版本 - 解決CUDA記憶體不足問題")
        print("="*60)

        # 設置環境變數
        os.environ['PYTORCH_CUDA_ALLOC_CONF'] = 'expandable_segments:True'

        # 初始化記憶體優化的提取器
        extractor = MemoryOptimizedQwen2Extractor()

        print(f"\n開始處理CSV文件: {csv_file}")

        # 處理CSV文件（記憶體優化版本）
        result = extractor.process_csv_file_optimized(csv_file)

        if result is not None:
            print("\n 所有會議記錄處理完成！")
            print(" 記憶體優化模式成功運行")
            print(" 已解決CUDA記憶體不足問題")
            print(" 分批處理和積極記憶體清理生效")
            print(" 已生成三個檔案：逐行整理、整體總結、人物列表")
        else:
            print("\n 處理失敗，請檢查文件格式和內容")

    except Exception as e:
        print(f"執行過程中發生錯誤: {str(e)}")
        print("\n記憶體優化建議：")
        print("1. 確認GPU記憶體足夠（建議8GB以上）")
        print("2. 關閉其他GPU應用程式")
        print("3. 重啟Python程序清理記憶體")
        print("4. 調整batch_size參數（在初始化時設置）")


if __name__ == "__main__":
    process_meeting_records_optimized()