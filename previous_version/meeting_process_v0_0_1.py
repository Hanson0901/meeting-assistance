#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Qwen3-4B-Instruct-2507 重點整理助手
適用於文本摘要、要點提取、內容整理等任務
"""

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
import warnings
import pandas as pd
import os
from datetime import datetime
warnings.filterwarnings("ignore")

class Qwen3KeyPointsExtractor:
    """
    使用Qwen3-4B-Instruct-2507模型進行重點整理的助手類
    """

    def __init__(self, model_name="Qwen/Qwen3-4B-Instruct-2507", device_map="auto",token=None):
        """
        初始化模型和tokenizer

        Args:
            model_name: 模型名稱
            device_map: 設備映射策略
        """
        print("正在載入Qwen3-4B-Instruct-2507模型...")
        print("注意：首次載入可能需要數分鐘時間下載模型檔案")
        # 載入tokenizer
        self.tokenizer = AutoTokenizer.from_pretrained(
            model_name,
            use_auth_token=token
        )
                # 獲取Huggingface token
        token = os.getenv("Huggingface_token")

        # 載入模型
        self.model = AutoModelForCausalLM.from_pretrained(
            model_name,
            torch_dtype="auto",  # 自動選擇最佳精度
            device_map=device_map,  # 自動分配到GPU/CPU
            trust_remote_code=True,
            low_cpu_mem_usage=True,  # 減少CPU記憶體使用
            use_auth_token=token
        )

        # 設置模型為評估模式
        self.model.eval()

        print(f"模型載入完成！")
        print(f"模型設備: {self.model.device}")
        print(f"模型精度: {self.model.dtype}")

    def create_summary_prompt(self, text, summary_type="重點整理", max_points=5, 
                            language="繁體中文", additional_requirements=""):
        """
        創建適合重點整理的prompt模板

        Args:
            text: 要整理的文本
            summary_type: 摘要類型 (重點整理, 會議記錄, 學習筆記等)
            max_points: 最大要點數量
            language: 輸出語言
            additional_requirements: 額外需求
        """

        prompt_template = f"""你是一位專業的內容整理師，擅長從長篇文本中提取關鍵信息。

### 任務說明 ###
請對以下內容進行{summary_type}，要求：
1. 使用{language}回答
2. 提取最多{max_points}個核心要點
3. 每個要點應該簡潔明了，突出關鍵信息
4. 按重要性排序
5. 使用條列式格式呈現
{f"6. {additional_requirements}" if additional_requirements else ""}

### 內容格式 ###
請按以下格式輸出：

## {summary_type}

### 核心要點
1. [第一個重點] - 簡要說明
2. [第二個重點] - 簡要說明
3. [第三個重點] - 簡要說明
...

### 總結
[一句話總結整體內容的精髓]

### 待整理內容 ###
{text}

請開始整理："""

        return prompt_template

    def create_meeting_prompt(self, text):
        """
        創建會議記錄整理專用prompt
        """
        return self.create_summary_prompt(
            text,
            summary_type="會議記錄整理",
            max_points=8,
            additional_requirements="區分決策事項、行動項目和討論重點"
        )

    def create_learning_prompt(self, text):
        """
        創建學習筆記整理專用prompt
        """
        return self.create_summary_prompt(
            text,
            summary_type="學習重點整理",
            max_points=6,
            additional_requirements="突出重要概念、關鍵定義和核心原理"
        )

    def create_article_prompt(self, text):
        """
        創建文章摘要專用prompt
        """
        return self.create_summary_prompt(
            text,
            summary_type="文章重點摘要",
            max_points=5,
            additional_requirements="保留作者觀點和論述邏輯"
        )

    def generate_summary(self, text, prompt_type="general", max_tokens=2048,
                        temperature=0.7, top_p=0.8, top_k=20):
        """
        生成重點整理

        Args:
            text: 要整理的文本
            prompt_type: prompt類型 (general, meeting, learning, article)
            max_tokens: 最大生成長度
            temperature: 溫度參數
            top_p: top_p參數
            top_k: top_k參數
        """

        # 選擇適當的prompt
        if prompt_type == "meeting":
            prompt = self.create_meeting_prompt(text)
        elif prompt_type == "learning": 
            prompt = self.create_learning_prompt(text)
        elif prompt_type == "article":
            prompt = self.create_article_prompt(text)
        else:
            prompt = self.create_summary_prompt(text)

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

        print("正在生成重點整理...")

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

    def batch_summarize(self, texts, prompt_type="general", **kwargs):
        """
        批量處理多個文本

        Args:
            texts: 文本列表
            prompt_type: prompt類型
            **kwargs: 其他參數
        """
        results = []
        for i, text in enumerate(texts):
            print(f"處理第 {i+1}/{len(texts)} 個文本...")
            summary = self.generate_summary(text, prompt_type, **kwargs)
            results.append(summary)
        return results

    def save_summary(self, text, summary, filename, original_filename=""):
        """
        保存整理結果到文件
        """
        with open(filename, 'w', encoding='utf-8') as f:
            f.write("# 重點整理結果\n\n")
            if original_filename:
                f.write(f"**原始文件**: {original_filename}\n\n")
            f.write(f"**整理時間**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write("## 整理結果\n\n")
            f.write(summary)
            f.write("\n\n---\n\n")
            f.write("## 原始內容\n\n")
            f.write(text)
        print(f"整理結果已保存至: {filename}")

# 使用示例函數
def example_usage():
    """
    使用示例
    """

    # 示例文本（可以替換為您的實際內容）
    sample_text = """
    人工智能（AI）技術正在快速發展，並在各個領域產生深遠影響。機器學習作為AI的核心技術之一，
    使計算機能夠從數據中學習並做出預測。深度學習進一步推進了這一領域，通過神經網絡模擬人腦
    的學習過程。在實際應用中，AI技術已經被廣泛應用於圖像識別、自然語言處理、推薦系統等領域。
    然而，AI技術的發展也帶來了一些挑戰，包括數據隱私、算法偏見、就業影響等問題。
    未來，我們需要在推進AI技術發展的同時，也要關注相關的倫理和社會問題，確保AI技術能夠
    真正造福人類社會。企業和研究機構應該加強合作，制定相關的規範和標準，
    促進AI技術的健康發展。
    """

    try:
        # 初始化重點整理助手
        extractor = Qwen3KeyPointsExtractor()

        print("\n" + "="*50)
        print("開始重點整理示例")
        print("="*50)
        
        '''
        # 一般重點整理
        print("\n【一般重點整理】")
        summary1 = extractor.generate_summary(sample_text, prompt_type="general")
        print(summary1)
        '''
        
        '''
        # 學習重點整理  
        print("\n【學習重點整理】")
        summary2 = extractor.generate_summary(sample_text, prompt_type="learning")
        print(summary2)
        '''
        # 文章摘要
        print("\n【文章摘要】") 
        summary3 = extractor.generate_summary(sample_text, prompt_type="article")
        print(summary3)

    except Exception as e:
        print(f"執行過程中發生錯誤: {str(e)}")
        print("請確保：")
        print("1. 已安裝 transformers >= 4.51.0")
        print("2. 已安裝 torch")
        print("3. 有足夠的GPU記憶體或使用CPU模式")

if __name__ == "__main__":
    example_usage()