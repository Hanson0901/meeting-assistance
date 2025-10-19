#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
完整版會議記錄生成器 - 使用transformers庫調用Qwen本地模型
支持生成10000字左右的詳細會議記錄
支持Qwen/Qwen3-4B-Instruct-2507模型
作者: AI Assistant
生成日期: 2025-10-10
版本: 2.2 - 增強主題多樣性
"""

import json
import os
import random
import re
import gc
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Set

# 設置環境變數避免警告
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

try:
    from transformers import (
        AutoTokenizer, 
        AutoModelForCausalLM, 
        GenerationConfig
    )
    import torch
    import torch.cuda
    HF_AVAILABLE = True
    print(" transformers庫載入成功")
except ImportError as e:
    HF_AVAILABLE = False
    print(f" transformers庫載入失敗: {e}")
    print("安裝方法: pip install transformers torch accelerate")


class QwenModelInterface:
    """Qwen模型接口類 - 使用transformers庫，eval模式，無量化"""

    def __init__(self, 
                 model_path: str = "Qwen/Qwen3-4B-Instruct-2507",
                 device_map: str = "auto"):
        """
        初始化Qwen模型

        Args:
            model_path: 模型路径或HuggingFace模型名稱
            device_map: 設備映射策略
        """
        self.model_path = model_path
        self.device_map = device_map
        self.model = None
        self.tokenizer = None
        self.generation_config = None

        if not HF_AVAILABLE:
            print(" transformers庫未安裝，無法載入模型")
            return

        self._load_model()

    def _load_model(self):
        """載入模型和tokenizer"""
        try:
            print(f" 正在載入Qwen模型: {self.model_path}")

            # 載入tokenizer
            self.tokenizer = AutoTokenizer.from_pretrained(
                self.model_path,
                trust_remote_code=True,
                use_fast=False
            )

            # 設置pad_token_id避免警告
            if self.tokenizer.pad_token_id is None:
                self.tokenizer.pad_token_id = self.tokenizer.eos_token_id

            # 載入模型 - 移除量化配置
            model_kwargs = {
                "trust_remote_code": True,
                "device_map": self.device_map,
                "torch_dtype": torch.float16 if torch.cuda.is_available() else torch.float32,
            }

            self.model = AutoModelForCausalLM.from_pretrained(
                self.model_path,
                **model_kwargs
            )

            # 設置為評估模式
            self.model.eval()
            print(" 模型已設置為評估模式")

            # 設置生成配置
            self.generation_config = GenerationConfig(
                temperature=0.7,
                top_p=0.8,
                top_k=20,
                repetition_penalty=1.05,
                max_new_tokens=150,  # 增加生成長度
                do_sample=True,
                pad_token_id=self.tokenizer.pad_token_id,
                eos_token_id=self.tokenizer.eos_token_id,
            )

            # 檢查模型設備
            device_info = next(self.model.parameters()).device if hasattr(self.model, 'parameters') else "unknown"
            print(f" 模型載入成功")
            print(f" 模型設備: {device_info}")
            print(f" 模型模式: {'評估模式' if not self.model.training else '訓練模式'}")

            if torch.cuda.is_available():
                print(f" GPU內存使用: {torch.cuda.memory_allocated() / 1024**3:.2f} GB")

        except Exception as e:
            print(f" 模型載入失敗: {e}")
            self.model = None
            self.tokenizer = None

    def generate_text(self, 
                     prompt: str, 
                     max_new_tokens: int = 80, 
                     temperature: float = 0.7,
                     top_p: float = 0.8,
                     top_k: int = 20) -> str:
        """
        生成文本

        Args:
            prompt: 輸入提示
            max_new_tokens: 最大新token數量
            temperature: 溫度參數
            top_p: Top-p採樣參數
            top_k: Top-k採樣參數

        Returns:
            生成的文本
        """
        if not self.model or not self.tokenizer:
            print(" 模型未正確載入，使用備用生成")
            return self._fallback_generation(prompt)

        try:
            # 確保模型在評估模式
            self.model.eval()

            # 構建對話格式
            messages = [
                {"role": "system", "content": "你是一個專業的會議記錄助手，請根據要求生成高品質、詳細的內容。"},
                {"role": "user", "content": prompt}
            ]

            # 應用聊天模板
            text = self.tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True
            )

            # 編碼輸入並設置attention_mask
            model_inputs = self.tokenizer(
                [text], 
                return_tensors="pt",
                truncation=True,
                max_length=2048,
                padding=True  # 確保生成attention_mask
            )

            # 移動到模型設備
            model_inputs = {k: v.to(self.model.device) for k, v in model_inputs.items()}

            # 更新生成配置
            self.generation_config.max_new_tokens = max_new_tokens
            self.generation_config.temperature = temperature
            self.generation_config.top_p = top_p
            self.generation_config.top_k = top_k

            # 生成文本，確保傳遞attention_mask
            with torch.no_grad():
                generated_ids = self.model.generate(
                    input_ids=model_inputs["input_ids"],
                    attention_mask=model_inputs["attention_mask"],
                    generation_config=self.generation_config,
                    use_cache=True
                )

            # 解碼生成的token
            generated_ids = [
                output_ids[len(input_ids):] 
                for input_ids, output_ids in zip(model_inputs["input_ids"], generated_ids)
            ]

            response = self.tokenizer.batch_decode(
                generated_ids, 
                skip_special_tokens=True
            )[0]

            # 清理生成的文本
            response = response.strip()

            # 清理GPU內存
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

            return response

        except Exception as e:
            print(f" 模型生成時發生錯誤: {e}")
            return self._fallback_generation(prompt)

    def _fallback_generation(self, prompt: str) -> str:
        """備用生成方法 - 增加多樣性"""
        prompt_lower = prompt.lower()

        if "會議主題" in prompt or "meeting topic" in prompt_lower:
            # 大幅擴展主題庫，涵蓋各行各業
            diverse_topics = [
                # 科技創新類
                "人工智慧在醫療診斷的應用前景",
                "5G網路建設與智慧城市發展",
                "區塊鏈技術在金融業的實踐案例",
                "物聯網設備安全防護策略研討",
                "雲端運算成本優化與效益分析",

                # 商業管理類
                "跨國企業文化融合與管理挑戰",
                "中小企業數位行銷策略規劃",
                "供應鏈風險管理與應變機制",
                "客戶關係管理系統導入評估",
                "組織變革與員工心理適應輔導",

                # 教育培訓類
                "線上教學平台使用者體驗優化",
                "職場技能培訓課程設計研習",
                "學習成效評估與改進機制",
                "企業內部講師培訓計畫",
                "終身學習制度建立與推動",

                # 健康醫療類
                "遠距醫療服務品質標準制定",
                "醫院資訊系統整合優化方案",
                "慢性病患居家照護模式創新",
                "醫護人員工作壓力管理策略",
                "醫療器材採購成本控制分析",

                # 環境永續類
                "企業碳足跡追蹤與減量目標",
                "循環經濟商業模式創新探討",
                "再生能源投資效益評估會議",
                "廢棄物處理技術改善研習",
                "綠色建築認證標準討論",

                # 金融投資類
                "金融科技創新應用趨勢分析",
                "投資組合風險評估與管理",
                "數位貨幣監管政策影響評估",
                "保險業務數位化轉型規劃",
                "企業融資策略與成本分析",

                # 製造業類
                "自動化生產線導入可行性研究",
                "品質管理系統持續改善計畫",
                "工業4.0技術導入效益分析",
                "生產成本控制與利潤優化",
                "設備維護預測性管理策略",

                # 零售服務類
                "消費者行為分析與市場趨勢",
                "電商平台營運策略優化討論",
                "門市服務流程改善研習",
                "庫存管理智慧化解決方案",
                "顧客滿意度提升行動方案",

                # 交通運輸類
                "智慧交通系統建置規劃會議",
                "物流配送路線最佳化研究",
                "交通安全管理制度檢討",
                "大眾運輸服務品質提升",
                "綠色運輸政策推動策略",

                # 法務合規類
                "個人資料保護法規遵循檢討",
                "智慧財產權管理制度建立",
                "勞動法規變更因應措施",
                "合約管理作業流程優化",
                "企業法律風險評估機制",

                # 人力資源類
                "遠距工作管理制度建立",
                "員工績效考核制度改革",
                "人才招募策略與流程優化",
                "職場多元包容文化推動",
                "員工福利制度檢討與改善",

                # 市場行銷類
                "品牌形象重塑策略規劃",
                "社群媒體行銷效果評估",
                "產品定價策略與競爭分析",
                "客戶分群與精準行銷",
                "市場進入策略可行性研究"
            ]
            return random.choice(diverse_topics)

        elif "姓名" in prompt or "name" in prompt_lower:
            surnames = ["陳", "林", "王", "李", "張", "劉", "黃", "吳", "鄭", "謝", "許", "蔡", "楊", "洪", "徐", "曾", "彭", "游", "周", "胡"]
            given_names = [
                "志明", "佳穎", "建華", "雅雯", "俊宇", "思妤", "宗翰", "佩芸",
                "家豪", "怡萱", "承恩", "雅芳", "宇軒", "美慧", "志豪", "詩涵",
                "承翰", "雅婷", "建志", "佳蓉", "宗憲", "美玲", "志偉", "雅琪",
                "文斌", "淑芬", "冠廷", "欣儀", "柏宇", "婷婷", "偉志", "琪琪"
            ]
            return random.choice(surnames) + random.choice(given_names)

        elif "職位" in prompt or "position" in prompt_lower:
            positions = [
                "數位轉型總監", "永續發展經理", "資料科學家", "用戶體驗設計師",
                "區塊鏈技術專家", "人工智慧工程師", "數位行銷策略師", "雲端架構師",
                "產品創新經理", "客戶成功總監", "資訊安全分析師", "業務流程優化專家",
                "敏捷開發教練", "數據治理專員", "創新實驗室負責人", "策略分析師",
                "供應鏈管理專家", "綠色金融顧問", "企業社會責任主管", "數位內容策展人",
                "品質管理總監", "營運效率專家", "客戶關係經理", "市場研發主任",
                "技術創新顧問", "系統整合專員", "商業智能分析師", "風險管理經理"
            ]
            return random.choice(positions)

        elif "行動" in prompt or "代辦" in prompt or "action" in prompt_lower:
            actions = [
                "建立跨部門數位協作平台與工作流程",
                "完成競爭對手AI技術應用情況調研",
                "設計客戶旅程地圖並識別數位化機會點",
                "制定數據治理框架與隱私保護策略",
                "開發永續發展指標監控儀表板",
                "建立供應商ESG評估與管理標準",
                "完成區塊鏈技術可行性評估報告",
                "設計員工數位技能培訓與認證計畫",
                "建立客戶反饋收集與分析自動化系統",
                "制定創新專案孵化與投資評估機制",
                "建立績效管理系統與KPI監控機制",
                "完成市場調研報告與競爭策略分析",
                "制定品質改善計劃與執行時程表",
                "建立風險預警系統與應變機制",
                "完成成本分析與預算規劃報告"
            ]
            return random.choice(actions)

        elif "詳細發言" in prompt or "長篇內容" in prompt:
            # 生成較長的發言內容
            detailed_speeches = [
                "從我們目前的市場分析來看，這個項目具有很高的戰略價值。首先，它能夠幫助我們提升核心競爭力，其次可以優化我們的業務流程，最重要的是能夠為客戶創造更大的價值。我建議我們從三個方面來推進：技術層面的創新、流程的標準化，以及團隊能力的提升。根據初步評估，預計投資回報期約為12-18個月。",
                "根據我們的財務分析報告，這個方案的投資回報率預計在18個月內達到正值。雖然初期投入較大，但長期效益非常明顯。我們需要考慮的風險因素包括市場變化、技術更新速度，以及競爭對手的策略調整。建議我們制定階段性的里程碑和風險控制機制，並建立定期檢討會議來追蹤進度。",
                "從客戶需求的角度來分析，我們發現有三個關鍵趨勢值得關注。第一是個性化需求的增加，客戶希望得到更貼近自身需求的解決方案。第二是對服務效率的更高要求，現代客戶期待即時且高品質的服務體驗。第三是對數據安全和隱私保護的重視程度不斷提升。我們的解決方案必須能夠同時滿足這三個方面的需求。",
                "技術實施方面，我們需要考慮系統的可擴展性、穩定性和安全性三大面向。建議採用微服務架構，這樣可以提高系統的靈活性和維護性，也便於未來的功能擴展。同時，我們還需要建立完整的監控和警報機制，確保系統運行的穩定性。在安全方面，建議實施多層次的安全策略，包括網路安全、數據加密和身份驗證等機制。"
            ]
            return random.choice(detailed_speeches)

        return "根據會議主題生成的專業內容"

    def cleanup(self):
        """清理模型資源"""
        if self.model:
            del self.model
        if self.tokenizer:
            del self.tokenizer

        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        gc.collect()
        print(" 模型資源已清理")


class EnhancedMeetingRecordGenerator:
    """增強版會議記錄生成器 - 支持10000字會議記錄，主題多樣化"""

    def __init__(self, 
                 model_path: str = "Qwen/Qwen3-4B-Instruct-2507"):
        """
        初始化生成器

        Args:
            model_path: Qwen模型路徑
        """
        self.model_path = model_path
        self.topics_file = "meeting_topics.json"
        self.output_dir = "meeting_records"
        self.generated_topics: Set[str] = set()  # 用於去重

        # 創建輸出目錄
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
            print(f" 已創建輸出目錄: {self.output_dir}")

        # 初始化Qwen模型 - 移除量化參數
        self.qwen_model = QwenModelInterface(model_path=model_path)

    def generate_topics(self, count: int = 100) -> List[str]:
        """使用Qwen模型生成多樣化會議主題"""
        print(f" 使用Qwen模型生成 {count} 個多樣化會議主題...")
        topics = []
        successful_generations = 0
        self.generated_topics.clear()  # 清空之前的記錄

        # 定義多樣化的領域清單
        topic_domains = [
            "科技創新與數位轉型",
            "商業管理與策略規劃", 
            "教育培訓與人才發展",
            "健康醫療與生技產業",
            "環境永續與綠色發展",
            "金融投資與風險管理",
            "製造業與工業革新",
            "零售服務與消費趨勢",
            "交通運輸與物流管理",
            "法務合規與智財管理",
            "人力資源與組織發展",
            "市場行銷與品牌建立",
            "農業科技與食品安全",
            "能源產業與基礎建設",
            "文化創意與媒體娛樂",
            "社會公益與非營利組織",
            "政府治理與公共政策",
            "國際貿易與跨境合作",
            "學校社團與活動策劃",
            "家庭理財與生活規劃"
        ]

        for i in range(count):
            # 隨機選擇領域，增加多樣性
            selected_domain = random.choice(topic_domains)

            topic_prompt = f"""請生成一個{selected_domain}領域的專業會議主題，要求：
1. 主題要具體且專業，避免過於籠統
2. 長度控制在10-25個繁體中文字符
3. 體現該領域的實務挑戰或創新應用
4. 適合企業或組織內部討論
5. 避免使用"策略規劃"、"研討會"等過於常見的詞彙
6. 直接返回會議主題，不要添加引號或其他格式

請生成一個具體的{selected_domain}會議主題："""

            try:
                # 使用更高的創造性參數
                topic = self.qwen_model.generate_text(
                    topic_prompt, 
                    max_new_tokens=50,
                    temperature=0.9,  # 提高創造性
                    top_p=0.95,
                    top_k=20
                )

                # 清理生成的文本
                topic = self._clean_generated_text(topic)

                # 驗證主題品質和唯一性
                if self._validate_topic(topic) and self._is_topic_unique(topic):
                    topics.append(topic)
                    self.generated_topics.add(topic.lower().strip())  # 加入去重集合
                    successful_generations += 1

                    if (i + 1) % 10 == 0:
                        print(f"   已生成 {successful_generations}/{i + 1} 個有效主題")

            except Exception as e:
                print(f"   生成主題 {i+1} 時發生錯誤: {e}")
                continue

        print(f" 成功生成 {len(topics)} 個多樣化高品質會議主題")
        print(f" 主題重複率: {((count - len(topics)) / count * 100):.1f}%")
        return topics

    def _is_topic_unique(self, topic: str) -> bool:
        """檢查主題是否唯一"""
        topic_normalized = topic.lower().strip()

        # 完全相同檢查
        if topic_normalized in self.generated_topics:
            return False

        # 相似度檢查（簡化版）
        for existing_topic in self.generated_topics:
            # 計算重疊字符比例
            set1 = set(topic_normalized)
            set2 = set(existing_topic)
            overlap = len(set1.intersection(set2))
            min_length = min(len(set1), len(set2))

            # 如果重疊度超過80%，視為重複
            if min_length > 0 and overlap / min_length > 0.8:
                return False

        return True

    def _validate_topic(self, topic: str) -> bool:
        """驗證主題品質"""
        if not topic or len(topic) < 8 or len(topic) > 30:
            return False

        # 檢查是否包含無意義的內容
        invalid_patterns = [
            r'^主題[：:]',
            r'^會議[：:]',
            r'^請生成',
            r'^\d+[.、]',
            r'請生成',
            r'要求',
            r'根據',
            r'領域',
            r'範圍',
            r'^生成'
        ]

        for pattern in invalid_patterns:
            if re.search(pattern, topic):
                return False

        # 檢查是否過於簡單或重複詞彙過多
        words = list(topic)
        unique_words = set(words)
        if len(unique_words) < len(words) * 0.6:  # 重複字符過多
            return False

        return True

    def generate_characters(self, topic: str, min_chars: int = 6, max_chars: int = 12) -> List[Dict[str, str]]:
        """使用Qwen模型生成角色 - 增加角色數量以支持更長會議"""
        char_count = random.randint(min_chars, max_chars)
        characters = []

        print(f"   為主題「{topic}」生成 {char_count} 位角色...")

        for i in range(char_count):
            # 生成姓名
            name_prompt = """請生成一個台灣常見的中文姓名，要求：
1. 符合台灣人命名習慣和文化背景
2. 姓名長度2-3個繁體中文字
3. 直接返回完整姓名，不要其他說明

中文姓名："""

            # 生成與主題相關的職位
            position_prompt = f"""請根據會議主題「{topic}」生成一個相關且專業的職位名稱，要求：
1. 職位必須與會議主題高度相關
2. 長度控制在4-15個繁體中文字符
3. 體現現代企業職位特色
4. 避免使用過於籠統的職位名稱
5. 直接返回職位名稱，不要其他說明

相關職位："""

            try:
                # 生成姓名
                name = self.qwen_model.generate_text(
                    name_prompt, 
                    max_new_tokens=20,
                    temperature=0.6
                )
                name = self._clean_generated_text(name)

                # 生成職位
                position = self.qwen_model.generate_text(
                    position_prompt, 
                    max_new_tokens=30,
                    temperature=0.8
                )
                position = self._clean_generated_text(position)

                # 驗證生成品質
                if (self._validate_name(name) and 
                    self._validate_position(position)):

                    characters.append({
                        "name": name,
                        "position": position,
                        "id": i + 1
                    })

            except Exception as e:
                print(f"     生成角色 {i+1} 時發生錯誤: {e}")
                continue

        print(f"   成功生成 {len(characters)} 位角色")
        return characters

    def _validate_name(self, name: str) -> bool:
        """驗證姓名品質"""
        if not name or len(name) < 2 or len(name) > 4:
            return False

        # 檢查是否包含無效字符
        if re.search(r'[a-zA-Z0-9：:「」『』]', name):
            return False

        return True

    def _validate_position(self, position: str) -> bool:
        """驗證職位品質"""
        if not position or len(position) < 3 or len(position) > 20:
            return False

        # 檢查是否包含無效內容
        invalid_patterns = [
            r'職位[：:]',
            r'相關[：:]',
            r'請生成',
            r'根據',
            r'^[：:]'
        ]

        for pattern in invalid_patterns:
            if re.search(pattern, position):
                return False

        return True

    def generate_todo_items(self, topic: str, min_items: int = 12, max_items: int = 20) -> List[Dict[str, Any]]:
        """使用Qwen模型生成代辦事項 - 增加事項數量"""
        item_count = random.randint(min_items, max_items)
        todo_items = []

        print(f"   為主題「{topic}」生成 {item_count} 個代辦事項...")

        for i in range(item_count):
            action_prompt = f"""請根據會議主題「{topic}」生成一個具體可執行的行動項目，要求：
1. 行動項目必須與會議主題密切相關且具體可行
2. 描述明確的任務和預期成果
3. 長度控制在8-35個繁體中文字符
4. 體現專業性和可操作性
5. 使用動詞開頭，如"建立"、"完成"、"制定"、"評估"等
6. 直接返回行動項目，不要其他說明

具體行動項目："""

            try:
                action = self.qwen_model.generate_text(
                    action_prompt, 
                    max_new_tokens=50,
                    temperature=0.8
                )
                action = self._clean_generated_text(action)

                # 驗證代辦事項品質
                if self._validate_action(action):
                    deadline_days = random.randint(7, 60)  # 擴展期限範圍
                    deadline = (datetime.now() + timedelta(days=deadline_days)).strftime("%Y-%m-%d")

                    todo_items.append({
                        "id": i + 1,
                        "action": action,
                        "deadline": deadline,
                        "priority": random.choice(["高", "中", "低"]),
                        "status": "待處理"
                    })

            except Exception as e:
                print(f"     生成代辦事項 {i+1} 時發生錯誤: {e}")
                continue

        print(f"   成功生成 {len(todo_items)} 個代辦事項")
        return todo_items

    def _validate_action(self, action: str) -> bool:
        """驗證代辦事項品質"""
        if not action or len(action) < 6 or len(action) > 45:
            return False

        # 檢查是否包含無效內容
        invalid_patterns = [
            r'行動項目[：:]',
            r'代辦事項[：:]',
            r'具體[：:]',
            r'請生成',
            r'根據',
            r'^[：:]'
        ]

        for pattern in invalid_patterns:
            if re.search(pattern, action):
                return False

        return True

    def _clean_generated_text(self, text: str) -> str:
        """清理生成的文本"""
        if not text:
            return ""

        # 移除常見的前綴和後綴
        prefixes = [
            "會議主題：", "中文姓名：", "職位：", "代辦事項：", "行動項目：",
            "會議主題:", "中文姓名:", "職位:", "代辦事項:", "行動項目:",
            "主題：", "姓名：", "相關職位：", "具體行動項目：",
            "主題:", "姓名:", "相關職位:", "具體行動項目:",
            "請生成一個具體的", "領域的專業會議主題", "會議主題",
        ]

        for prefix in prefixes:
            if text.startswith(prefix):
                text = text[len(prefix):].strip()

        # 移除引號和括號
        text = text.strip('"「」『』()（）[]【】<>')

        # 移除多餘的標點符號和空格
        text = re.sub(r'^[：:：。，、！？]+', '', text)
        text = re.sub(r'[：:：。，、！？]+$', '', text)
        text = re.sub(r'\s+', ' ', text.strip())

        return text

    def save_topics_to_json(self, topics: List[str]) -> None:
        """保存主題到JSON文件"""
        topics_data = {
            "generated_at": datetime.now().isoformat(),
            "model_used": self.model_path,
            "total_count": len(topics),
            "generation_method": "Qwen3-4B-Instruct using transformers (eval mode, no quantization, diverse topics)",
            "target_length": "10000+ characters per meeting",
            "diversity_features": {
                "domain_coverage": 18,  # 涵蓋18個不同領域
                "uniqueness_check": True,
                "similarity_threshold": 0.8
            },
            "model_settings": {
                "eval_mode": True,
                "quantization": False,
                "torch_dtype": "float16" if torch.cuda.is_available() else "float32"
            },
            "topics": [
                {
                    "id": i + 1, 
                    "title": topic,
                    "length": len(topic)
                } for i, topic in enumerate(topics)
            ]
        }

        with open(self.topics_file, 'w', encoding='utf-8') as f:
            json.dump(topics_data, f, ensure_ascii=False, indent=2)

        print(f" 已將 {len(topics)} 個多樣化主題保存到 {self.topics_file}")

    def generate_detailed_speech(self, topic: str, speaker_name: str, speaker_position: str, context: str) -> str:
        """生成詳細的發言內容"""
        speech_prompt = f"""請根據以下信息生成一段詳細的會議發言，要求：
1. 發言人：{speaker_name}（{speaker_position}）
2. 會議主題：{topic}
3. 發言背景：{context}
4. 發言長度：80-150字
5. 體現專業性和深度思考
6. 包含具體的分析、建議或觀點
7. 語調自然且符合職場會議情境
8. 避免過於學術化的表達
9. 直接返回發言內容，不要添加其他格式

詳細發言："""

        try:
            speech = self.qwen_model.generate_text(
                speech_prompt, 
                max_new_tokens=200,
                temperature=0.8
            )
            return self._clean_generated_text(speech)
        except Exception as e:
            print(f"     生成詳細發言時發生錯誤: {e}")
            # 返回備用內容
            return f"感謝大家的關注。關於{context}這個議題，我認為我們需要從多個角度來分析。首先是市場趨勢，其次是技術可行性，最後是實施成本。建議我們制定詳細的執行計劃，並設立階段性目標來確保項目的順利推進。我們也需要建立風險管控機制，以應對執行過程中可能遇到的挑戰。"

    def generate_extended_meeting_dialogue(self, topic: str, characters: List[Dict], todo_items: List[Dict]) -> List[Dict[str, str]]:
        """生成擴展的會議對話 - 目標10000字"""
        if not characters:
            return []

        dialogue = []
        moderator = characters[0]['name']

        # 會議開場 (約500字)
        dialogue.append({
            "speaker": moderator,
            "content": f"各位同事大家好，歡迎參加今天的重要會議。今天我們要深入討論的主題是「{topic}」，這個議題對我們組織的未來發展具有重要的戰略意義。在開始正式討論之前，我想先簡單說明今天會議的流程安排。我們將分為四個部分：首先是各部門代表的詳細報告，接著是針對具體執行方案的深入討論，然後是風險評估與資源配置，最後是決策總結和後續行動計劃。希望各位能夠積極參與討論，共同為這個項目的成功實施貢獻智慧和力量。"
        })

        # 自我介紹環節 (約800字)
        intro_speeches = [
            "很榮幸能參與這次重要的會議。作為部門負責人，我將從戰略規劃的角度為大家分享我們的分析和建議。",
            "感謝會議組織者的邀請。我會結合我們部門的專業經驗，為這個項目提供技術層面的支持和建議。",
            "大家好，我期待在今天的會議中聽到各位的寶貴意見，並希望能夠為項目的成功實施做出貢獻。",
            "很高興與各位專家同事一起討論這個重要議題。我將從實務執行的角度分享我們的經驗和想法。"
        ]

        intro_count = min(len(intro_speeches), len(characters) - 1)
        for i, char in enumerate(characters[1:intro_count + 1]):
            base_intro = intro_speeches[i % len(intro_speeches)]
            detailed_intro = self.generate_detailed_speech(
                topic, char['name'], char['position'], 
                f"自我介紹和對{topic}的初步看法"
            )

            dialogue.append({
                "speaker": char['name'],
                "content": f"大家好，我是{char['position']}{char['name']}。{base_intro} {detailed_intro}"
            })

        # 議程說明
        dialogue.append({
            "speaker": moderator,
            "content": f"感謝各位的介紹。現在我們進入正式議程。首先，我想請各部門針對{topic}提供詳細的現狀分析和建議方案。我們將按照重要性順序來進行討論，每位發言人請詳細說明您的觀點和建議。"
        })

        # 詳細討論環節 (約4000字)
        discussion_contexts = [
            "現狀分析與市場趨勢",
            "技術可行性評估",
            "財務投資與效益分析",
            "實施策略與時程規劃",
            "風險評估與控制措施",
            "資源配置與團隊建設",
            "法規遵循與合規要求",
            "競爭對手分析",
            "客戶需求與市場定位",
            "長期發展與擴展計劃"
        ]

        # 第一輪詳細討論
        for i, item in enumerate(todo_items[:min(10, len(todo_items))]):
            speaker = characters[i % len(characters)]['name']
            speaker_pos = characters[i % len(characters)]['position']
            context = discussion_contexts[i % len(discussion_contexts)]

            detailed_speech = self.generate_detailed_speech(
                topic, speaker, speaker_pos, context
            )

            dialogue.append({
                "speaker": speaker,
                "content": f"關於「{item['action']}」這個重要項目，{detailed_speech} 我建議我們將完成期限設定為{item['deadline']}，優先等級為{item['priority']}。這個時程安排是基於我們對資源配置和技術難度的綜合評估。"
            })

            # 其他人的回應和討論
            if len(characters) > 1:
                responder = characters[(i + 1) % len(characters)]['name']
                responder_pos = characters[(i + 1) % len(characters)]['position']

                response_speech = self.generate_detailed_speech(
                    topic, responder, responder_pos, 
                    f"對{item['action']}的回應和補充建議"
                )

                dialogue.append({
                    "speaker": responder,
                    "content": response_speech
                })

                # 如果有第三個人，增加進一步討論
                if len(characters) > 2 and i < 5:  # 限制前5個項目有三方討論
                    third_speaker = characters[(i + 2) % len(characters)]['name']
                    third_pos = characters[(i + 2) % len(characters)]['position']

                    third_speech = self.generate_detailed_speech(
                        topic, third_speaker, third_pos,
                        f"從{third_pos}角度對討論的補充"
                    )

                    dialogue.append({
                        "speaker": third_speaker,
                        "content": third_speech
                    })

        # 中場休息與階段性總結 (約300字)
        dialogue.append({
            "speaker": moderator,
            "content": f"經過剛才的深入討論，我們已經對{topic}的各個重要面向有了更清楚的認識。現在我想請大家暫時休息一下，整理思路。待會我們將進入第二階段的討論，重點關注實施細節和具體的執行策略。請大家準備好針對剛才提到的關鍵議題進行更深入的分析。"
        })

        # 第二輪深入討論 (約2500字)
        advanced_contexts = [
            "詳細實施方案與執行步驟",
            "跨部門協作機制建立",
            "績效指標設定與監控機制",
            "預算分配與成本控制",
            "品質保證與標準制定"
        ]

        for i, item in enumerate(todo_items[10:min(15, len(todo_items))]):
            speaker = characters[i % len(characters)]['name']
            speaker_pos = characters[i % len(characters)]['position']
            context = advanced_contexts[i % len(advanced_contexts)]

            detailed_speech = self.generate_detailed_speech(
                topic, speaker, speaker_pos, context
            )

            dialogue.append({
                "speaker": speaker,
                "content": f"針對「{item['action']}」的執行細節，{detailed_speech} 我們需要特別注意時程管控，確保在{item['deadline']}前達成目標。"
            })

            # 深度互動討論
            for j in range(min(2, len(characters) - 1)):
                responder = characters[(i + j + 1) % len(characters)]['name']
                responder_pos = characters[(i + j + 1) % len(characters)]['position']

                response_context = f"對{item['action']}實施方案的{['技術分析', '風險評估'][j]}"
                response_speech = self.generate_detailed_speech(
                    topic, responder, responder_pos, response_context
                )

                dialogue.append({
                    "speaker": responder,
                    "content": response_speech
                })

        # 決策與總結環節 (約1000字)
        dialogue.append({
            "speaker": moderator,
            "content": f"經過今天充分而深入的討論，我們對{topic}已經有了全面而深刻的理解。現在我想請各位對今天討論的重點進行總結，並提出最終的建議和決策方向。首先，我們來總結一下今天達成的共識和需要進一步討論的議題。"
        })

        # 最終發言輪
        for i, char in enumerate(characters[:5]):  # 限制最後發言人數
            final_speech = self.generate_detailed_speech(
                topic, char['name'], char['position'],
                f"對{topic}的最終總結和建議"
            )

            dialogue.append({
                "speaker": char['name'],
                "content": f"{final_speech} 我認為這個項目具有重要的戰略價值，值得我們全力投入。"
            })

        # 會議結論 (約400字)
        dialogue.append({
            "speaker": moderator,
            "content": f"今天的會議非常成功，各位的專業分析和建議都非常有價值。基於大家的討論，我們對{topic}形成了清楚的共識和具體的行動方案。接下來，我們將按照今天確定的時程和分工來推進各項工作。我會在會後整理會議紀錄，並在三個工作日內發送給各位。同時，我們將建立定期檢討機制，確保各項任務的順利執行。再次感謝各位的積極參與，期待我們合作的成果。"
        })

        dialogue.append({
            "speaker": characters[-1]['name'],
            "content": f"謝謝{moderator}的主持和各位同事的寶貴貢獻。今天的討論讓我對{topic}有了更深入的理解，也讓我對未來的合作充滿信心。我們將全力以赴，確保項目的成功實施。會議結束，謝謝大家。"
        })

        print(f"   生成了 {len(dialogue)} 段對話，預估總字數約 {self._estimate_word_count(dialogue)} 字")
        return dialogue

    def _estimate_word_count(self, dialogue: List[Dict[str, str]]) -> int:
        """估算對話總字數"""
        total_chars = sum(len(line['content']) + len(line['speaker']) + 2 for line in dialogue)
        return total_chars

    def generate_meeting_dialogue(self, topic: str, characters: List[Dict], todo_items: List[Dict]) -> List[Dict[str, str]]:
        """生成會議對話 - 調用擴展版本"""
        return self.generate_extended_meeting_dialogue(topic, characters, todo_items)

    def generate_srt_content(self, dialogue: List[Dict[str, str]], duration_per_line: int = 5) -> str:
        """生成SRT字幕內容 - 調整時間以適應更長內容"""
        srt_content = []
        current_time = 0

        for i, line in enumerate(dialogue):
            start_time = current_time
            # 根據內容長度動態調整持續時間
            content_length = len(line['content'])
            # 更長的內容需要更多時間
            duration = max(duration_per_line, content_length * 0.12)  # 約每字0.12秒
            end_time = current_time + duration

            # 格式化時間
            start_formatted = self.format_srt_time(start_time)
            end_formatted = self.format_srt_time(end_time)

            # SRT格式
            srt_entry = f"{i + 1}\n{start_formatted} --> {end_formatted}\n{line['speaker']}: {line['content']}\n"
            srt_content.append(srt_entry)

            current_time = end_time + 1.0  # 增加間隔時間

        return "\n".join(srt_content)

    def format_srt_time(self, seconds: float) -> str:
        """格式化SRT時間戳"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millisecs = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millisecs:03d}"

    def sanitize_filename(self, filename: str) -> str:
        """清理文件名"""
        # 移除或替換不合法的文件名字符
        filename = re.sub(r'[<>:"/\\|?*]', '', filename)
        filename = filename.replace(' ', '_').replace('　', '_')  # 處理全形空格
        return filename[:45]  # 限制長度

    def generate_all_meetings(self, topics: List[str]) -> None:
        """為所有主題生成完整會議記錄"""
        total_topics = len(topics)
        success_count = 0

        print(f" 開始批量生成 {total_topics} 個多樣化詳細會議記錄（目標每個10000字+）...")
        print("=" * 60)

        for i, topic in enumerate(topics, 1):
            try:
                print(f" 處理進度 {i}/{total_topics}: {topic}")

                # 生成會議元素
                characters = self.generate_characters(topic, 6, 12)  # 增加角色數量
                todo_items = self.generate_todo_items(topic, 12, 20)  # 增加事項數量

                if not characters or not todo_items:
                    print(f"   跳過（生成內容不足）")
                    continue

                # 生成詳細對話
                dialogue = self.generate_meeting_dialogue(topic, characters, todo_items)

                # 計算實際字數
                actual_word_count = self._estimate_word_count(dialogue)

                # 生成SRT內容
                srt_content = self.generate_srt_content(dialogue)

                # 生成文件名
                safe_topic = self.sanitize_filename(topic)
                filename = f"{i:03d}-{safe_topic}.srt"
                filepath = os.path.join(self.output_dir, filename)

                # 保存SRT文件
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(srt_content)

                # 保存詳細資訊JSON
                meeting_data = {
                    "id": i,
                    "topic": topic,
                    "characters": characters,
                    "todo_items": todo_items,
                    "dialogue": dialogue,
                    "statistics": {
                        "character_count": len(characters),
                        "todo_count": len(todo_items),
                        "dialogue_lines": len(dialogue),
                        "estimated_word_count": actual_word_count,
                        "total_duration_seconds": len(dialogue) * 6.0,
                        "target_achieved": actual_word_count >= 8000
                    },
                    "model_settings": {
                        "eval_mode": True,
                        "quantization": False,
                        "model_path": self.model_path,
                        "diversity_enhanced": True
                    },
                    "generated_at": datetime.now().isoformat(),
                    "model_used": self.model_path
                }

                json_filename = f"{i:03d}-{safe_topic}.json"
                json_filepath = os.path.join(self.output_dir, json_filename)

                with open(json_filepath, 'w', encoding='utf-8') as f:
                    json.dump(meeting_data, f, ensure_ascii=False, indent=2)

                success_count += 1
                print(f"   成功生成: {filename} ({actual_word_count} 字)")

                # 每5個清理一次記憶體（由於內容更長，更頻繁清理）
                if i % 5 == 0:
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()

            except Exception as e:
                print(f"   處理主題 {i} 時發生錯誤: {e}")
                continue

        print("=" * 60)
        print(f" 批量生成完成！")
        print(f" 成功生成: {success_count}/{total_topics} 個多樣化詳細會議記錄")
        print(f" 輸出目錄: {os.path.abspath(self.output_dir)}")

    def cleanup(self):
        """清理資源"""
        if hasattr(self, 'qwen_model'):
            self.qwen_model.cleanup()


def main():
    """主程序"""
    print("=" * 60)
    print(" 完整版會議記錄生成系統 v2.2")
    print(" 使用 Qwen/Qwen3-4B-Instruct-2507 本地模型")
    print(" 模式: 評估模式 (eval mode)")
    print(" 量化: 已關閉")
    print(" 特色: 主題多樣化增強")
    print(" 目標: 生成10000字詳細會議記錄")
    print(" 基於 transformers 庫實現")
    print("=" * 60)

    try:
        # 檢查系統資源
        if torch.cuda.is_available():
            print(f" GPU設備: {torch.cuda.get_device_name()}")
            print(f" GPU記憶體: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f} GB")
        else:
            print(" 未偵測到GPU，將使用CPU運行（速度較慢）")

        # 初始化生成器
        print("\n 初始化會議記錄生成器...")
        generator = EnhancedMeetingRecordGenerator(
            model_path="Qwen/Qwen3-4B-Instruct-2507"
        )

        # 步驟1: 生成多樣化會議主題
        print("\n" + "=" * 40)
        print(" 步驟1: 生成多樣化會議主題")
        print("=" * 40)

        topics = generator.generate_topics(100)
        generator.save_topics_to_json(topics)

        # 顯示部分主題樣本
        print("\n 生成的多樣化主題樣本:")
        for i, topic in enumerate(topics[:8], 1):  # 顯示更多樣本
            print(f"  {i}. {topic}")
        if len(topics) > 8:
            print(f"  ... 還有 {len(topics) - 8} 個主題")

        # 分析主題多樣性
        topic_keywords = {}
        for topic in topics:
            words = topic.replace('與', ' ').replace('和', ' ').split()
            for word in words:
                if len(word) > 1:
                    topic_keywords[word] = topic_keywords.get(word, 0) + 1

        most_common = sorted(topic_keywords.items(), key=lambda x: x[1], reverse=True)[:10]
        print("\n 主題關鍵詞分析（前10名）:")
        for word, count in most_common:
            print(f"  - {word}: {count} 次")

        # 步驟2: 生成詳細會議記錄
        print("\n" + "=" * 40)
        print(" 步驟2: 生成詳細會議記錄 (10000字+)")
        print("=" * 40)

        generator.generate_all_meetings(topics)

        # 生成統計報告
        print("\n" + "=" * 40)
        print(" 最終統計報告")
        print("=" * 40)

        # 統計生成的文件
        srt_files = [f for f in os.listdir(generator.output_dir) if f.endswith('.srt')]
        json_files = [f for f in os.listdir(generator.output_dir) if f.endswith('.json') and not f.endswith('topics.json')]

        print(f" SRT字幕文件: {len(srt_files)} 個")
        print(f" 詳細JSON文件: {len(json_files)} 個")
        print(f" 輸出目錄: {os.path.abspath(generator.output_dir)}")

        # 計算字數統計
        if json_files:
            total_word_count = 0
            achieved_target_count = 0

            for json_file in json_files:
                try:
                    with open(os.path.join(generator.output_dir, json_file), 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        word_count = data.get('statistics', {}).get('estimated_word_count', 0)
                        total_word_count += word_count
                        if word_count >= 8000:
                            achieved_target_count += 1
                except:
                    continue

            avg_word_count = total_word_count / len(json_files) if json_files else 0

            print(f" 平均字數: {avg_word_count:.0f} 字/會議")
            print(f" 達成8000字+目標: {achieved_target_count}/{len(json_files)} 個會議")
            print(f" 總字數: {total_word_count:,} 字")

        # 顯示文件大小統計
        if srt_files:
            total_size = sum(
                os.path.getsize(os.path.join(generator.output_dir, f)) 
                for f in srt_files + json_files
            )
            print(f" 總文件大小: {total_size / 1024:.1f} KB")

            print(f"\n 前5個生成的文件:")
            for filename in sorted(srt_files)[:5]:
                filepath = os.path.join(generator.output_dir, filename)
                file_size = os.path.getsize(filepath)
                print(f"  - {filename} ({file_size:,} bytes)")

        print(f"\n 程序執行完成！所有多樣化詳細會議記錄已生成完畢。")

    except KeyboardInterrupt:
        print("\n 用戶中斷程序執行")
    except Exception as e:
        print(f"\n 程序執行時發生錯誤: {e}")
    finally:
        # 清理資源
        try:
            generator.cleanup()
        except:
            pass
        print(" 資源清理完成")


if __name__ == "__main__":
    main()