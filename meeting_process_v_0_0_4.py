#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Qwen/Qwen3-14B-AWQ 會議記錄整理助手 (記憶體優化版本)
專門用於處理CSV文件中的會議記錄並進行逐行重點整理，最後總結整個會議主題
加強版：包含完整的人物識別和角色分析功能，支援人物去重
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
    使用Qwen/Qwen3-4B-Instruct-2507模型專門進行會議記錄整理的助手類（記憶體優化版本）
    """

    def __init__(self, model_name="Qwen/Qwen3-4B-Instruct-2507", device_map="auto", token=None):
        """
        初始化模型和tokenizer
        """
        print("正在載入Qwen/Qwen3-4B-Instruct-2507模型（記憶體優化版本）...")
        print("注意：首次載入可能需要數分鐘時間下載模型檔案")

        # 設置授權Token

        # 載入tokenizer
        self.tokenizer = AutoTokenizer.from_pretrained(
            model_name,
            use_auth_token=token
        )

        # 載入模型
        self.model = AutoModelForCausalLM.from_pretrained(
            model_name,
            dtype="auto",
            device_map=device_map,
            trust_remote_code=True,
            use_auth_token=token
        )

        # 設置模型為評估模式
        self.model.eval()

        print(f"模型載入完成！")
        print(f"模型設備: {self.model.device}")
        print(f"模型精度: {self.model.dtype}")

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
        合併重複的人物信息，保留最完整的描述
        """
        people_dict = {}

        for person_info in people_list:
            if not person_info or "本段無具體人物提及" in person_info:
                continue

            # 提取人物姓名作為key
            person_name = self.extract_person_name(person_info)

            if not person_name:
                continue

            # 如果是新人物，直接加入
            if person_name not in people_dict:
                people_dict[person_name] = {
                    'name': person_name,
                    'full_info': person_info,
                    'appearances': 1,
                    'roles': set(),
                    'contributions': set()
                }
            else:
                # 如果是重複人物，合併信息
                people_dict[person_name]['appearances'] += 1

                # 如果新信息更完整（更長），則更新
                if len(person_info) > len(people_dict[person_name]['full_info']):
                    people_dict[person_name]['full_info'] = person_info

                # 提取角色和貢獻信息
                parts = person_info.split('-')
                if len(parts) >= 2:
                    role = parts[1].strip()
                    people_dict[person_name]['roles'].add(role)
                if len(parts) >= 3:
                    contribution = parts[2].strip()
                    people_dict[person_name]['contributions'].add(contribution)

        # 轉換為最終格式
        final_people = []
        for person_name, info in people_dict.items():
            if info['appearances'] > 1:
                # 對於多次出現的人物，加上出現次數
                enhanced_info = f"{info['full_info']} (出現 {info['appearances']} 次)"
            else:
                enhanced_info = info['full_info']
            final_people.append(enhanced_info)

        return final_people, len(people_dict)

    def create_meeting_prompt(self, text):
        """
        創建會議記錄整理專用prompt（強化人物識別）
        """
        prompt_template = f"""你是一位專業的會議記錄整理專家，擅長從會議記錄中提取關鍵信息和識別重要人物。

### 任務說明 ###
請對以下會議記錄進行重點整理，要求：
1. 使用繁體中文回答
2. 準確識別會議中出現的所有人物及其角色
3. 提取最多2個核心要點
4. 區分決策事項、行動項目和討論重點
5. 每個要點應該簡潔明了，突出關鍵信息
6. 按重要性排序

### 輸出格式 ###
請按以下格式輸出：

## 會議記錄整理

### 出現人物
- [人物名稱] - [職位/角色] - [在本段中的主要貢獻或發言重點]
（如本段無明確人物，則寫"本段無具體人物提及"）

### 核心要點
1. [關鍵要點] - 簡要說明
2. [關鍵要點] - 簡要說明

### 決策事項
- [決策內容]（如有）

### 行動項目
- [待辦事項]（如有）

### 總結
[一句話總結本段會議內容的核心]

### 待整理的會議記錄 ###
{text}

請開始整理："""

        return prompt_template

    def create_compact_summary_prompt(self, key_themes, decisions, actions, people_info, unique_people_count, total_records):
        """
        創建精簡版整體會議總結prompt（記憶體優化，包含去重人物分析）
        """
        themes_text = "\n".join([f"- {theme}" for theme in key_themes[:10]])
        decisions_text = "\n".join([f"- {decision}" for decision in decisions[:8]])
        actions_text = "\n".join([f"- {action}" for action in actions[:8]])
        people_text = "\n".join([f"- {person}" for person in people_info[:12]])

        prompt_template = f"""你是一位資深的會議分析專家，請基於以下提取的關鍵信息，總結整個會議的核心主題。

### 會議基本信息 ###
- 總發言段數：{total_records} 段
- 識別到的獨立人物數：{unique_people_count} 位
- 分析日期：{datetime.now().strftime('%Y-%m-%d')}

### 提取的關鍵人物（已去重） ###
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
4. 對於多次出現的人物，請特別標註其重要性

##  會議整體主題總結

###  會議標題
[請幫會議訂定一個吸引人的標題，不超過15字]

###  會議核心主題
[用1-2句話概括整場會議的主要目的和核心議題]

###  關鍵人物分析（共{unique_people_count}位獨立人物）
1. **[重要人物一]** - [職位] - [主要貢獻和角色]
2. **[重要人物二]** - [職位] - [主要貢獻和角色]
3. **[重要人物三]** - [職位] - [主要貢獻和角色]
（根據實際情況列出3-5位關鍵人物，優先列出多次出現的重要人物）

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

    def clean_memory(self):
        """
        清理GPU記憶體
        """
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        gc.collect()

    def generate_meeting_summary(self, text, max_tokens=600, temperature=0.7, top_p=0.8, top_k=20):
        """
        生成會議記錄重點整理（增加token數以容納人物信息）
        """
        # 創建會議記錄專用prompt
        prompt = self.create_meeting_prompt(text)

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
                temperature=temperature,
                top_p=top_p,
                top_k=top_k,
                do_sample=True,
                pad_token_id=self.tokenizer.eos_token_id,
                eos_token_id=self.tokenizer.eos_token_id,
            )

        # 解碼輸出（只取新生成的部分）
        output_ids = generated_ids[0][len(model_inputs['input_ids'][0]):].tolist()
        summary = self.tokenizer.decode(output_ids, skip_special_tokens=True)

        # 清理記憶體
        del model_inputs, generated_ids
        self.clean_memory()

        return summary.strip()

    def extract_key_elements(self, all_summaries):
        """
        從所有摘要中提取關鍵元素（記憶體優化，包含人物提取和去重）
        """
        key_themes = []
        decisions = []
        actions = []
        raw_people_info = []  # 原始人物信息列表

        for summary in all_summaries:
            # 簡單提取關鍵信息
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
                        # 提取人物信息，去除前綴符號
                        person_info = line.lstrip('- 123.').strip()
                        if person_info and "本段無具體人物提及" not in person_info:
                            raw_people_info.append(person_info)
                    elif current_section == "themes" and len(key_themes) < 15:
                        key_themes.append(line.lstrip('- 123.').strip())
                    elif current_section == "decisions" and len(decisions) < 10:
                        decisions.append(line.lstrip('- ').strip())
                    elif current_section == "actions" and len(actions) < 10:
                        actions.append(line.lstrip('- ').strip())

        # 對人物信息進行去重處理
        unique_people_info, unique_people_count = self.merge_people_info(raw_people_info)

        return key_themes, decisions, actions, unique_people_info, unique_people_count

    def generate_compact_summary(self, key_themes, decisions, actions, people_info, unique_people_count, total_records):
        """
        生成精簡版整體總結（記憶體優化，包含去重人物分析）
        """
        print("\n正在生成整體會議主題總結（記憶體優化模式）...")

        # 創建精簡版prompt
        prompt = self.create_compact_summary_prompt(key_themes, decisions, actions, people_info, unique_people_count, total_records)

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

        print("正在生成整體總結...")

        # 生成回應
        with torch.no_grad():
            generated_ids = self.model.generate(
                **model_inputs,
                max_new_tokens=1000,  # 增加輸出長度以容納人物分析
                temperature=0.7,
                top_p=0.8,
                top_k=20,
                do_sample=True,
                pad_token_id=self.tokenizer.eos_token_id,
                eos_token_id=self.tokenizer.eos_token_id,
            )

        # 解碼輸出
        output_ids = generated_ids[0][len(model_inputs['input_ids'][0]):].tolist()
        overall_summary = self.tokenizer.decode(output_ids, skip_special_tokens=True)

        # 清理記憶體
        del model_inputs, generated_ids
        self.clean_memory()

        return overall_summary.strip()

    def process_csv_file(self, csv_file_path, output_file_path=None):
        """
        處理CSV文件（記憶體優化版本，包含人物分析和去重）
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
            print(" 使用記憶體優化模式處理...")

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

                print(f"處理第 {index + 1}/{len(df)} 行...")

                try:
                    # 生成重點整理
                    summary = self.generate_meeting_summary(original_text)

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

                    print(f"✓ 第 {index + 1} 行處理完成")

                    # 定期清理記憶體
                    if index % 20 == 0:
                        self.clean_memory()

                except Exception as e:
                    print(f"✗ 第 {index + 1} 行處理失敗: {str(e)}")
                    continue

            if not results:
                print(" 沒有成功處理任何記錄")
                return None

            print("-" * 80)

            # 提取關鍵元素（記憶體優化，包含人物去重）
            print("\n 正在提取會議關鍵元素...")
            key_themes, decisions, actions, people_info, unique_people_count = self.extract_key_elements(all_summaries)

            print(f"✓ 識別到 {unique_people_count} 位獨立人物（已去重）")
            print(f"✓ 提取到 {len(key_themes)} 個關鍵主題")
            print(f"✓ 提取到 {len(decisions)} 個決策事項")  
            print(f"✓ 提取到 {len(actions)} 個行動項目")

            # 清理原始摘要以節省記憶體
            del all_summaries
            self.clean_memory()

            # 生成精簡版整體總結
            print("\n" + "="*80)
            print("開始生成整體會議主題總結")
            print("="*80)

            overall_summary = self.generate_compact_summary(
                key_themes, decisions, actions, people_info, unique_people_count, len(results)
            )

            print("\n✓ 整體會議主題總結完成！")

            # 轉換為DataFrame
            results_df = pd.DataFrame(results)

            # 生成輸出文件名
            if output_file_path is None:
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                output_file_path = f'meeting_summary_{timestamp}.csv'
                summary_file_path = f'meeting_overall_summary_{timestamp}.txt'
            else:
                base_name = output_file_path.replace('.csv', '')
                summary_file_path = f'{base_name}_overall_summary.txt'

            # 保存逐行整理結果
            results_df.to_csv(output_file_path, index=False, encoding='utf-8-sig')
            print(f"\n✓ 逐行整理結果已保存至: {output_file_path}")

            # 保存整體會議總結
            with open(summary_file_path, 'w', encoding='utf-8') as f:
                f.write("# 會議整體主題總結（記憶體優化版本）\n\n")
                f.write(f"**分析時間**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"**會議記錄總數**: {len(results)} 段\n")
                f.write(f"**總字數**: {total_original_chars:,} 字\n")
                f.write(f"**識別獨立人物數**: {unique_people_count}\n")
                f.write(f"**提取關鍵主題數**: {len(key_themes)}\n")
                f.write(f"**決策事項數**: {len(decisions)}\n")
                f.write(f"**行動項目數**: {len(actions)}\n\n")
                f.write("---\n\n")
                f.write(overall_summary)

            print(f"✓ 整體會議主題總結已保存至: {summary_file_path}")
            print(f"✓ 成功處理 {len(results)} 條記錄")

            # 顯示處理統計
            self.show_processing_stats(results_df, overall_summary, people_info, unique_people_count)

            return results_df, overall_summary

        except Exception as e:
            print(f"處理CSV文件時發生錯誤: {str(e)}")
            return None

    def show_processing_stats(self, results_df, overall_summary=None, people_info=None, unique_people_count=0):
        """
        顯示處理統計信息（包含去重人物統計）
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

            # 顯示人物統計
            if people_info and unique_people_count > 0:
                print(f"\n👥 人物識別統計:")
                print(f"識別到的獨立人物總數: {unique_people_count} 位")
                print(f"人物信息條目總數: {len(people_info)} 條（含重複出現）")
                print("前5位重要人物預覽:")
                for i, person in enumerate(people_info[:5]):
                    print(f"  {i+1}. {person}")

            # 顯示整體總結預覽
            if overall_summary:
                print("\n" + "-"*40)
                print("整體會議主題總結預覽:")
                print("-"*40)
                # 只顯示總結的前200字
                preview = overall_summary[:200] + "..." if len(overall_summary) > 200 else overall_summary
                print(preview)

        print("="*60)

def process_meeting_records():
    """
    主要處理函數（記憶體優化版本）
    """
    # CSV文件路徑
    csv_file = "/home/cgu-csie/meeting-assistence/meeting_record/project_test_1.csv"

    # 檢查文件是否存在
    if not os.path.exists(csv_file):
        print(f"錯誤：找不到文件 {csv_file}")
        print("請確保CSV文件在當前目錄下")
        return

    try:
        print("="*60)
        print("Qwen3-4B-Instruct-2507 會議記錄整理系統")
        print("記憶體優化版本 - 包含人物去重功能")
        print("="*60)

        # 初始化模型
        extractor = Qwen3MeetingRecordExtractor()

        print(f"\n開始處理CSV文件: {csv_file}")

        # 處理CSV文件
        result = extractor.process_csv_file(csv_file)

        if result is not None:
            print("\n 所有會議記錄處理完成！")
            print(" 記憶體優化模式成功運行")
            print(" 包含智能人物去重和角色分析")
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
