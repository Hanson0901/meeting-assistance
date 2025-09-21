#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Qwen/Qwen3-14B-AWQ 會議記錄整理助手 (AI人物識別版本)
專門用於處理CSV文件中的會議記錄並進行逐行重點整理，最後總結整個會議主題
AI增強版：使用AI智能判斷是否為同一人物
"""
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
import warnings
import pandas as pd
from datetime import datetime
import os
import gc
import re
warnings.filterwarnings("ignore")

class Qwen3MeetingRecordExtractor:
    """
    使用Qwen/Qwen3-4B-Instruct-2507模型專門進行會議記錄整理的助手類（AI人物識別版本）
    """
    def __init__(self, model_name="Qwen/Qwen3-4B-Instruct-2507", device_map="auto", token=None):
        """
        初始化模型和tokenizer
        """
        print("正在載入Qwen/Qwen3-4B-Instruct-2507模型（AI人物識別版本）...")
        print("注意：首次載入可能需要數分鐘時間下載模型檔案")

        # 設置授權Token
        token = os.getenv("Huggingface_token")

        # 載入tokenizer
        self.tokenizer = AutoTokenizer.from_pretrained(
            model_name,
            use_auth_token=token
        )

        # 載入模型
        self.model = AutoModelForCausalLM.from_pretrained(
            model_name,
            torch_dtype="auto",
            device_map=device_map,
            trust_remote_code=True,
            use_auth_token=token
        )

        # 設置模型為評估模式
        self.model.eval()

        print(f"模型載入完成！")
        print(f"模型設備: {self.model.device}")
        print(f"模型精度: {self.model.dtype}")

    def clean_memory(self):
        """
        清理GPU記憶體
        """
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        gc.collect()

    def generate_response(self, prompt, max_tokens=400):
        """
        通用的生成回應方法
        """
        # 構建消息格式
        messages = [
            {"role": "user", "content": prompt}
        ]

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

        # 生成回應
        with torch.no_grad():
            generated_ids = self.model.generate(
                **model_inputs,
                max_new_tokens=max_tokens,
                temperature=0.3,  # 降低溫度以提高一致性
                top_p=0.8,
                top_k=20,
                do_sample=True,
                pad_token_id=self.tokenizer.eos_token_id,
                eos_token_id=self.tokenizer.eos_token_id,
            )

        # 解碼輸出（只取新生成的部分）
        output_ids = generated_ids[0][len(model_inputs['input_ids'][0]):].tolist()
        response = self.tokenizer.decode(output_ids, skip_special_tokens=True)

        # 清理記憶體
        del model_inputs, generated_ids
        self.clean_memory()

        return response.strip()

    def ai_identify_same_person(self, person1_info, person2_info):
        """
        使用AI判斷兩個人物描述是否指向同一人
        """
        prompt = f"""你是一位專業的人物識別專家，請判斷以下兩個人物描述是否指向同一個人。

### 任務說明 ###
1. 仔細分析兩個人物的姓名、職位、角色
2. 考慮可能的稱呼變化（如：全名 vs 姓氏、正式職稱 vs 簡稱）
3. 判斷是否為同一人物
4. 給出明確的是/否判斷

### 人物描述一 ###
{person1_info}

### 人物描述二 ###
{person2_info}

### 判斷標準 ###
- 姓名相同或相近（考慮簡稱、別稱）
- 職位相符或相關
- 在會議中的角色一致

請回答：是/否
（只需回答「是」或「否」，不需要其他說明）"""

        response = self.generate_response(prompt, max_tokens=50)

        # 解析AI的回答
        response_clean = response.strip().lower()
        if "是" in response_clean:
            return True
        elif "否" in response_clean:
            return False
        else:
            # 如果AI回答不明確，使用傳統方法作為備用
            return self.traditional_name_match(person1_info, person2_info)

    def traditional_name_match(self, person1_info, person2_info):
        """
        傳統的姓名匹配方法（作為AI判斷的備用）
        """
        name1 = self.extract_person_name(person1_info)
        name2 = self.extract_person_name(person2_info)

        if not name1 or not name2:
            return False

        # 完全匹配
        if name1 == name2:
            return True

        # 包含關係（如：林昶佐 vs 林）
        if name1 in name2 or name2 in name1:
            if len(name1) >= 2 or len(name2) >= 2:  # 至少一個是完整姓名
                return True

        return False

    def extract_person_name(self, person_info):
        """
        從人物信息中提取人物姓名（支援中文姓名）
        """
        # 常見的分隔符號
        separators = ['-', '：', ':', '（', '(', '，', ',']
        person_name = person_info.strip()

        # 找到第一個分隔符並提取姓名
        for sep in separators:
            if sep in person_name:
                person_name = person_name.split(sep)[0].strip()
                break

        # 清理常見的前綴
        prefixes_to_remove = ['委員', '主席', '顧問', '老師', '教授', '先生', '女士', '議員', '代表']
        for prefix in prefixes_to_remove:
            if person_name.startswith(prefix):
                person_name = person_name[len(prefix):].strip()

        # 移除括號內容
        person_name = re.sub(r'[（(][^)）]*[)）]', '', person_name).strip()

        return person_name

    def merge_people_info(self, people_list):
        """
        使用AI智能合併重複的人物信息
        """
        if not people_list:
            return [], 0

        print(f"     使用AI識別重複人物...")
        print(f"     原始人物條目數: {len(people_list)}")

        # 過濾無效條目
        valid_people = []
        for person_info in people_list:
            if person_info and "本段無具體人物提及" not in person_info:
                valid_people.append(person_info)

        if not valid_people:
            return [], 0

        # 使用AI進行智能分組
        merged_groups = []
        processed_indices = set()

        for i, person1 in enumerate(valid_people):
            if i in processed_indices:
                continue

            # 創建新的人物群組
            current_group = {
                'representative_info': person1,
                'all_infos': [person1],
                'appearances': 1,
                'name': self.extract_person_name(person1)
            }
            processed_indices.add(i)

            # 與後續人物進行AI比較
            for j, person2 in enumerate(valid_people[i+1:], i+1):
                if j in processed_indices:
                    continue

                print(f"       AI比較: 人物{i+1} vs 人物{j+1}")

                # 使用AI判斷是否為同一人
                if self.ai_identify_same_person(person1, person2):
                    print(f"       AI識別為同一人")
                    current_group['all_infos'].append(person2)
                    current_group['appearances'] += 1
                    processed_indices.add(j)

                    # 選擇更完整的描述作為代表
                    if len(person2) > len(current_group['representative_info']):
                        current_group['representative_info'] = person2
                else:
                    print(f"       AI識別為不同人物")

            merged_groups.append(current_group)

        # 生成最終結果
        final_people = []
        for group in merged_groups:
            if group['appearances'] > 1:
                enhanced_info = f"{group['representative_info']} (AI識別出現 {group['appearances']} 次)"
            else:
                enhanced_info = group['representative_info']
            final_people.append(enhanced_info)

        unique_count = len(merged_groups)
        print(f"     AI識別後獨立人物數: {unique_count}")

        return final_people, unique_count

    def extract_people(self, text):
        """
        模塊1：提取會議中出現的人物
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
        模塊2：提取核心要點
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
        模塊3：提取決策事項
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
        模塊4：提取行動項目
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
        模塊5：生成總結
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
        處理單個會議記錄（模塊化執行）
        """
        print(f"   開始模塊化處理第 {index} 行...")

        # 模塊1：提取人物
        people_result = self.extract_people(text)

        # 模塊2：提取核心要點
        keypoints_result = self.extract_key_points(text)

        # 模塊3：提取決策事項
        decisions_result = self.extract_decisions(text)

        # 模塊4：提取行動項目
        actions_result = self.extract_action_items(text)

        # 模塊5：生成總結
        summary_result = self.generate_summary(text)

        # 整合所有模塊結果
        integrated_result = f"""## 會議記錄整理

{people_result}

{keypoints_result}

{decisions_result}

{actions_result}

{summary_result}"""

        return integrated_result

    def extract_key_elements(self, all_summaries):
        """
        從所有摘要中提取關鍵元素（包含AI人物識別）
        """
        key_themes = []
        decisions = []
        actions = []
        raw_people_info = []

        for summary in all_summaries:
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

        # 使用AI進行人物信息去重處理
        print("\n 開始AI人物識別去重...")
        unique_people_info, unique_people_count = self.merge_people_info(raw_people_info)

        return key_themes, decisions, actions, unique_people_info, unique_people_count

    def create_overall_summary_prompt(self, key_themes, decisions, actions, people_info, unique_people_count, total_records):
        """
        創建整體會議總結prompt
        """
        themes_text = "\n".join([f"- {theme}" for theme in key_themes[:12]])
        decisions_text = "\n".join([f"- {decision}" for decision in decisions[:10]])
        actions_text = "\n".join([f"- {action}" for action in actions[:10]])
        people_text = "\n".join([f"- {person}" for person in people_info[:15]])

        prompt_template = f"""你是一位資深的會議分析專家，請基於以下提取的關鍵信息，總結整個會議的核心主題。

### 會議基本信息 ###
- 總發言段數：{total_records} 段
- AI識別到的獨立人物數：{unique_people_count} 位
- 分析日期：{datetime.now().strftime('%Y-%m-%d')}

### AI識別的關鍵人物（已去重） ###
{people_text}

### 提取的關鍵主題 ###
{themes_text}

### 重要決策事項 ###
{decisions_text}

### 行動項目 ###
{actions_text}

### 任務要求 ###
請基於以上信息，生成簡潔的整體會議總結：
1. 使用繁體中文回答
2. 重點分析關鍵人物的角色和貢獻
3. 提取核心可以超過3個要點，並保留最重要的
4. 對於AI識別的多次出現人物，請特別標註其重要性

##  會議整體主題總結

###  會議標題
[請幫會議訂定一個吸引人的標題，不超過15字]

###  會議核心主題
[用1-2句話概括整場會議的主要目的和核心議題]

###  關鍵人物分析（AI識別共{unique_people_count}位獨立人物）
1. **[重要人物一]** - [職位] - [主要貢獻和角色]
2. **[重要人物二]** - [職位] - [主要貢獻和角色]
3. **[重要人物三]** - [職位] - [主要貢獻和角色]
（根據AI識別的關鍵人物，優先列出多次出現的重要人物）

###  主要討論焦點
1. **[焦點一]** - 簡要說明
2. **[焦點二]** - 簡要說明
3. **[焦點三]** - 簡要說明

###  重要成果
- [成果一]
- [成果二]
- [成果三]

###  待辦事項
- [行動一]
- [行動二]
- [行動三]

###  會議意義
[2句話總結這次會議的重要性和影響]

請開始總結："""

        return prompt_template

    def generate_overall_summary(self, key_themes, decisions, actions, people_info, unique_people_count, total_records):
        """
        生成整體會議總結
        """
        print("\n正在生成整體會議主題總結...")

        prompt = self.create_overall_summary_prompt(
            key_themes, decisions, actions, people_info, unique_people_count, total_records
        )

        return self.generate_response(prompt, max_tokens=2560)

    def process_csv_file(self, csv_file_path, output_file_path=None):
        """
        處理CSV文件（AI人物識別版本）
        """
        try:
            # 讀取CSV文件
            print(f"正在讀取CSV文件: {csv_file_path}")
            df = pd.read_csv(csv_file_path, encoding='utf-8')

            # 檢查是否有'原文'欄位
            if '原文' not in df.columns:
                print("錯誤：CSV文件中沒有找到'原文'欄位")
                return None

            print(f"找到 {len(df)} 行會議記錄")
            print(" 使用AI人物識別處理模式...")

            # 準備結果列表
            results = []
            all_summaries = []
            total_original_chars = 0

            # 逐行處理
            for index, row in df.iterrows():
                original_text = str(row['原文']).strip()

                # 跳過空行或無效內容
                if not original_text or original_text == 'nan' or len(original_text) < 10:
                    print(f"第 {index + 1} 行內容過短，跳過處理")
                    continue

                print(f"\n 處理第 {index + 1}/{len(df)} 行...")

                try:
                    # 使用模塊化處理
                    summary = self.process_single_record(original_text, index + 1)

                    # 累加字數統計
                    total_original_chars += len(original_text)

                    # 保存到總結列表
                    all_summaries.append(summary)

                    # 保存結果
                    result = {
                        '行號': index + 1,
                        '原文': original_text,
                        '原文長度': len(original_text),
                        '重點整理': summary,
                        '處理時間': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    }

                    # 如果原CSV有其他欄位，也一併保留
                    for col in df.columns:
                        if col != '原文' and col in row:
                            result[f'原始_{col}'] = row[col]

                    results.append(result)

                    print(f"     第 {index + 1} 行AI增強處理完成")

                    # 定期清理記憶體
                    if index % 15 == 0:
                        self.clean_memory()

                except Exception as e:
                    print(f"     第 {index + 1} 行處理失敗: {str(e)}")
                    continue

            if not results:
                print(" 沒有成功處理任何記錄")
                return None

            print("\n" + "-" * 80)

            # 提取關鍵元素（使用AI人物識別）
            print("\n 正在提取會議關鍵元素...")
            key_themes, decisions, actions, people_info, unique_people_count = self.extract_key_elements(all_summaries)

            print(f" AI識別到 {unique_people_count} 位獨立人物（智能去重）")
            print(f" 提取到 {len(key_themes)} 個關鍵主題")
            print(f" 提取到 {len(decisions)} 個決策事項")  
            print(f" 提取到 {len(actions)} 個行動項目")

            # 清理原始摘要以節省記憶體
            del all_summaries
            self.clean_memory()

            # 生成整體總結
            print("\n" + "="*80)
            print("開始生成整體會議主題總結")
            print("="*80)

            overall_summary = self.generate_overall_summary(
                key_themes, decisions, actions, people_info, unique_people_count, len(results)
            )

            print("\n 整體會議主題總結完成！")

            # 轉換為DataFrame
            results_df = pd.DataFrame(results)

            # 生成輸出文件名
            if output_file_path is None:
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                output_file_path = f'meeting_summary_ai_enhanced_{timestamp}.csv'
                summary_file_path = f'meeting_overall_summary_ai_enhanced_{timestamp}.txt'
            else:
                base_name = output_file_path.replace('.csv', '')
                summary_file_path = f'{base_name}_overall_summary.txt'

            # 保存逐行整理結果
            results_df.to_csv(output_file_path, index=False, encoding='utf-8-sig')
            print(f"\n 逐行整理結果已保存至: {output_file_path}")

            # 保存整體會議總結
            with open(summary_file_path, 'w', encoding='utf-8') as f:
                f.write("# 會議整體主題總結（AI人物識別版本）\n\n")
                f.write(f"**分析時間**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"**會議記錄總數**: {len(results)} 段\n")
                f.write(f"**總字數**: {total_original_chars:,} 字\n")
                f.write(f"**AI識別獨立人物數**: {unique_people_count}\n")
                f.write(f"**提取關鍵主題數**: {len(key_themes)}\n")
                f.write(f"**決策事項數**: {len(decisions)}\n")
                f.write(f"**行動項目數**: {len(actions)}\n\n")
                f.write("---\n\n")
                f.write(overall_summary)

            print(f" 整體會議主題總結已保存至: {summary_file_path}")
            print(f" 成功處理 {len(results)} 條記錄")

            # 顯示處理統計
            self.show_processing_stats(results_df, overall_summary, people_info, unique_people_count)

            return results_df, overall_summary

        except Exception as e:
            print(f"處理CSV文件時發生錯誤: {str(e)}")
            return None

    def show_processing_stats(self, results_df, overall_summary=None, people_info=None, unique_people_count=0):
        """
        顯示處理統計信息（包含AI人物識別統計）
        """
        print("\n" + "="*60)
        print("處理統計")
        print("="*60)

        if len(results_df) > 0:
            avg_original_length = results_df['原文長度'].mean()
            total_original_chars = results_df['原文長度'].sum()

            print(f"總處理行數: {len(results_df)}")
            print(f"平均原文長度: {avg_original_length:.0f} 字")
            print(f"總原文字數: {total_original_chars:,} 字")
            print(f"最長原文: {results_df['原文長度'].max()} 字")
            print(f"最短原文: {results_df['原文長度'].min()} 字")

            # 顯示AI人物識別統計
            if people_info and unique_people_count > 0:
                print(f"\n AI人物識別統計:")
                print(f"AI識別到的獨立人物總數: {unique_people_count} 位")
                print(f"人物信息條目總數: {len(people_info)} 條（含重複出現）")
                print("所有重要人物預覽:")
                for i, person in enumerate(people_info):
                    print(f"  {i+1}. {person}")

            # 顯示整體總結預覽
            if overall_summary:
                print("\n" + "-"*40)
                print("整體會議主題總結預覽:")
                print("-"*40)
                preview = overall_summary[:200] + "..." if len(overall_summary) > 200 else overall_summary
                print(preview)

        print("="*60)

def process_meeting_records():
    """
    主要處理函數（AI人物識別版本）
    """
    # CSV文件路徑
    csv_file = r"C:\Users\cbes1\Desktop\meeting assistence\meeting_record\project_test_1.csv"

    # 檢查文件是否存在
    if not os.path.exists(csv_file):
        print(f"錯誤：找不到文件 {csv_file}")
        print("請確保CSV文件在當前目錄下")
        return

    try:
        print("="*60)
        print("Qwen3-4B-Instruct-2507 會議記錄整理系統")
        print("AI人物識別版本 - 智能判斷同一人物")
        print("="*60)

        # 初始化模型
        extractor = Qwen3MeetingRecordExtractor()

        print(f"\n開始處理CSV文件: {csv_file}")

        # 處理CSV文件
        result = extractor.process_csv_file(csv_file)

        if result is not None:
            print("\n 所有會議記錄處理完成！")
            print(" AI人物識別模式成功運行")
            print(" 智能判斷同一人物並合併統計")
            print(" 五個模塊分別執行完成")
            print(" 已生成逐行整理和整體總結兩個檔案")
        else:
            print("\n 處理失敗，請檢查文件格式和內容")

    except Exception as e:
        print(f"執行過程中發生錯誤: {str(e)}")
        print("\n如果仍遇到記憶體問題，請嘗試以下方法：")
        print("1. 關閉其他GPU應用程式")
        print("2. 重啟Python程序清理記憶體")
        print("3. 使用CPU版本: device_map='cpu'")

if __name__ == "__main__":
    process_meeting_records()
