#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Qwen3-1.7B 會議記錄整理助手
專門用於處理CSV文件中的會議記錄並進行逐行重點整理，最後總結整個會議主題
"""

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
import warnings
import pandas as pd
from datetime import datetime
import os

warnings.filterwarnings("ignore")

class Qwen3MeetingRecordExtractor:
    """
    使用Qwen3-4B-Instruct-2507模型專門進行會議記錄整理的助手類
    """

    def __init__(self, model_name="Qwen/Qwen3-1.7B", device_map="auto", token=None):
        """
        初始化模型和tokenizer
        Args:
            model_name: 模型名稱
            device_map: 設備映射策略
            token: HuggingFace授權Token
        """
        print("正在載入Qwen3-4B-Instruct-2507模型...")
        print("注意：首次載入可能需要數分鐘時間下載模型檔案")

        # 設置授權Token
        token = "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"

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
            low_cpu_mem_usage=True,
            use_auth_token=token
        )

        # 設置模型為評估模式
        self.model.eval()

        print(f"模型載入完成！")
        print(f"模型設備: {self.model.device}")
        print(f"模型精度: {self.model.dtype}")

    def create_meeting_prompt(self, text):
        """
        創建會議記錄整理專用prompt
        Args:
            text: 要整理的會議記錄文本
        """
        prompt_template = f"""你是一位專業的會議記錄整理專家，擅長從會議記錄中提取關鍵信息。

### 任務說明 ###
請對以下會議記錄進行重點整理，要求：
1. 使用繁體中文回答
2. 提取最多2個核心要點
3. 區分決策事項、行動項目和討論重點
4. 每個要點應該簡潔明了，突出關鍵信息
5. 按重要性排序

### 輸出格式 ###
請按以下格式輸出：

## 會議記錄整理

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

    def create_overall_summary_prompt(self, all_summaries, total_records, total_chars):
        """
        創建整個會議主題總結專用prompt
        Args:
            all_summaries: 所有逐行整理結果的列表
            total_records: 總記錄數
            total_chars: 總字數
        """
        # 將所有重點整理合併成一個文本
        combined_summaries = "\n\n---\n\n".join(all_summaries)

        prompt_template = f"""你是一位資深的會議分析專家，擅長從會議記錄中提煉整體主題和核心議題。

### 分析對象 ###
以下是一場會議的完整記錄整理，共包含 {total_records} 段發言，總計 {total_chars:,} 字。

### 任務要求 ###
請基於以下所有會議記錄的重點整理，進行整個會議的主題分析：
1. 使用繁體中文回答
2. 識別會議的核心主題和議題
3. 歸納主要的討論焦點
4. 總結重要決策和行動項目
5. 分析會議的整體走向和結論

### 輸出格式 ###
請按以下格式輸出：

##  會議整體主題分析

### 會議核心主題
[用1-2句話概括整場會議的核心主題]

### 主要議題分析
1. **[議題一]** - [議題說明和討論重點]
2. **[議題二]** - [議題說明和討論重點]
3. **[議題三]** - [議題說明和討論重點]
（根據實際情況列出3-5個主要議題）

### 重要決策彙整
- [決策事項一]
- [決策事項二]
- [決策事項三]
（如無決策事項則寫"本次會議主要為討論性質，未做出具體決策"）

### 行動項目彙整
- [行動項目一]
- [行動項目二]
- [行動項目三]
（如無行動項目則寫"本次會議未明確指派具體行動項目"）

### 會議特色與亮點
- [特殊議題或討論亮點]
- [參與者的重要觀點]
- [會議過程中的特殊情況]

### 整體評述
[2-3句話總結整場會議的意義、成果和後續影響]

### 會議記錄重點整理內容 ###
{combined_summaries}

請開始分析："""

        return prompt_template

    def generate_meeting_summary(self, text, max_tokens=512, temperature=0.7, top_p=0.8, top_k=20):
        """
        生成會議記錄重點整理
        Args:
            text: 要整理的文本
            max_tokens: 最大生成長度
            temperature: 溫度參數
            top_p: top_p參數
            top_k: top_k參數
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

        return summary.strip()

    def generate_overall_summary(self, all_summaries, total_records, total_chars, max_tokens=1024, temperature=0.7):
        """
        生成整個會議的主題總結
        Args:
            all_summaries: 所有重點整理的列表
            total_records: 總記錄數
            total_chars: 總字數
            max_tokens: 最大生成長度
            temperature: 溫度參數
        """
        print("\n正在進行整個會議的主題總結分析...")

        # 創建整體總結專用prompt
        prompt = self.create_overall_summary_prompt(all_summaries, total_records, total_chars)

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

        print("正在生成整體會議主題分析（這可能需要較長時間）...")

        # 生成回應
        with torch.no_grad():
            generated_ids = self.model.generate(
                **model_inputs,
                max_new_tokens=max_tokens,
                temperature=temperature,
                top_p=0.8,
                top_k=20,
                do_sample=True,
                pad_token_id=self.tokenizer.eos_token_id,
                eos_token_id=self.tokenizer.eos_token_id,
            )

        # 解碼輸出（只取新生成的部分）
        output_ids = generated_ids[0][len(model_inputs['input_ids'][0]):].tolist()
        overall_summary = self.tokenizer.decode(output_ids, skip_special_tokens=True)

        return overall_summary.strip()

    def process_csv_file(self, csv_file_path, output_file_path=None):
        """
        處理CSV文件，對每行原文進行會議記錄整理，最後總結整個會議主題
        Args:
            csv_file_path: CSV文件路徑
            output_file_path: 輸出文件路徑（可選）
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

            # 準備結果列表
            results = []
            all_summaries = []  # 存儲所有的重點整理，用於最終總結
            total_original_chars = 0

            # 逐行處理
            for index, row in df.iterrows():
                original_text = str(row['原文']).strip()

                # 跳過空行或無效內容
                if not original_text or original_text == 'nan' or len(original_text) < 10:
                    print(f"第 {index + 1} 行內容過短，跳過處理")
                    continue

                print(f"處理第 {index + 1}/{len(df)} 行...")
                print(f"原文前50字: {original_text[:50]}...")

                try:
                    # 生成重點整理
                    print("正在生成重點整理...")
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
                    print("-" * 80)

                except Exception as e:
                    print(f"✗ 第 {index + 1} 行處理失敗: {str(e)}")
                    continue

            if not results:
                print("沒有成功處理任何記錄")
                return None

            # 生成整個會議的主題總結
            print("\n" + "="*80)
            print("開始進行整個會議的主題總結分析")
            print("="*80)

            overall_summary = self.generate_overall_summary(
                all_summaries, 
                len(results), 
                total_original_chars
            )

            print("\n✓ 整個會議主題總結完成！")

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
                f.write("# 會議整體主題總結\n\n")
                f.write(f"**分析時間**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"**會議記錄總數**: {len(results)} 段\n")
                f.write(f"**總字數**: {total_original_chars:,} 字\n\n")
                f.write("---\n\n")
                f.write(overall_summary)

            print(f"✓ 整體會議主題總結已保存至: {summary_file_path}")
            print(f"✓ 成功處理 {len(results)} 條記錄")

            # 顯示處理統計和總結預覽
            self.show_processing_stats(results_df, overall_summary)

            return results_df, overall_summary

        except FileNotFoundError:
            print(f"錯誤：找不到文件 {csv_file_path}")
            return None
        except Exception as e:
            print(f"處理CSV文件時發生錯誤: {str(e)}")
            return None

    def show_processing_stats(self, results_df, overall_summary=None):
        """
        顯示處理統計信息和整體總結預覽
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

            # 顯示第一個處理結果作為示例
            print("\n" + "-"*40)
            print("逐行整理示例（第1行）:")
            print("-"*40)
            first_result = results_df.iloc[0]
            print(f"原文: {first_result['原文'][:100]}...")
            print(f"\n重點整理:\n{first_result['重點整理']}")

            # 顯示整體總結預覽
            if overall_summary:
                print("\n" + "-"*40)
                print("整體會議主題總結預覽:")
                print("-"*40)
                # 只顯示總結的前300字
                preview = overall_summary[:300] + "..." if len(overall_summary) > 300 else overall_summary
                print(preview)

        print("="*60)

def process_meeting_records():
    """
    主要處理函數
    """
    # CSV文件路徑
    csv_file = "C:\\Users\\cbes1\\Desktop\\meeting assistence\\meeting_record\\project_test_1.csv"

    # 檢查文件是否存在
    if not os.path.exists(csv_file):
        print(f"錯誤：找不到文件 {csv_file}")
        print("請確保CSV文件在當前目錄下")
        return

    try:
        print("="*60)
        print("Qwen3-4B-Instruct-2507 會議記錄整理系統")
        print("包含逐行整理 + 整體主題總結")
        print("="*60)

        # 初始化模型
        extractor = Qwen3MeetingRecordExtractor()

        print(f"\n開始處理CSV文件: {csv_file}")

        # 處理CSV文件
        result = extractor.process_csv_file(csv_file)

        if result is not None:
            print("\n 所有會議記錄處理完成！")
            print("已生成兩個檔案：")
            print("   1️  逐行重點整理結果（CSV格式）")
            print("   2️  整體會議主題總結（TXT格式）")
            print("可直接使用Excel等軟體開啟查看")
        else:
            print("\n處理失敗，請檢查文件格式和內容")

    except Exception as e:
        print(f"執行過程中發生錯誤: {str(e)}")
        print("\n故障排除建議：")
        print("1. 確保已安裝 transformers >= 4.51.0")
        print("2. 確保已安裝 torch 和 pandas")
        print("3. 確保CSV文件包含'原文'欄位")
        print("4. 檢查網絡連接（首次使用需下載模型）")
        print("5. 如果記憶體不足，請關閉其他應用程式")

if __name__ == "__main__":
    process_meeting_records()