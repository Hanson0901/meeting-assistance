#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
完整版會議記錄生成器 - 使用transformers庫調用Qwen本地模型
支持Qwen/Qwen2.5-7B-Instruct-1M模型
作者: AI Assistant
生成日期: 2025-10-10
版本: 1.0
"""

import json
import os
import random
import re
import gc
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

try:
    from transformers import (
        AutoTokenizer, 
        AutoModelForCausalLM, 
        GenerationConfig,
        BitsAndBytesConfig
    )
    import torch
    import torch.cuda
    HF_AVAILABLE = True
    print(" transformers庫載入成功")
except ImportError as e:
    HF_AVAILABLE = False
    print(f" transformers庫載入失敗: {e}")
    print("安裝方法: pip install transformers torch accelerate bitsandbytes")


class QwenModelInterface:
    """Qwen模型接口類 - 使用transformers庫"""

    def __init__(self, 
                 model_path: str = "Qwen/Qwen2.5-7B-Instruct-1M",
                 device_map: str = "auto",
                 load_in_8bit: bool = False,
                 load_in_4bit: bool = False):
        """
        初始化Qwen模型

        Args:
            model_path: 模型路径或HuggingFace模型名稱
            device_map: 設備映射策略
            load_in_8bit: 是否使用8bit量化
            load_in_4bit: 是否使用4bit量化
        """
        self.model_path = model_path
        self.device_map = device_map
        self.model = None
        self.tokenizer = None
        self.generation_config = None

        if not HF_AVAILABLE:
            print(" transformers庫未安裝，無法載入模型")
            return

        self._load_model(load_in_8bit, load_in_4bit)

    def _load_model(self, load_in_8bit: bool = False, load_in_4bit: bool = False):
        """載入模型和tokenizer"""
        try:
            print(f" 正在載入Qwen模型: {self.model_path}")

            # 載入tokenizer
            self.tokenizer = AutoTokenizer.from_pretrained(
                self.model_path,
                trust_remote_code=True,
                use_fast=False
            )

            # 設置量化配置（如果需要）
            quantization_config = None
            if load_in_4bit:
                quantization_config = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_compute_dtype=torch.float16,
                    bnb_4bit_use_double_quant=True,
                    bnb_4bit_quant_type="nf4"
                )
                print(" 使用4bit量化")
            elif load_in_8bit:
                quantization_config = BitsAndBytesConfig(load_in_8bit=True)
                print(" 使用8bit量化")

            # 載入模型
            model_kwargs = {
                "trust_remote_code": True,
                "device_map": self.device_map,
                "torch_dtype": torch.float16 if torch.cuda.is_available() else torch.float32,
            }

            if quantization_config:
                model_kwargs["quantization_config"] = quantization_config

            self.model = AutoModelForCausalLM.from_pretrained(
                self.model_path,
                **model_kwargs
            )

            # 設置生成配置
            self.generation_config = GenerationConfig(
                temperature=0.7,
                top_p=0.8,
                top_k=50,
                repetition_penalty=1.05,
                max_new_tokens=100,
                do_sample=True,
                pad_token_id=self.tokenizer.eos_token_id,
                eos_token_id=self.tokenizer.eos_token_id,
            )

            # 檢查模型設備
            device_info = next(self.model.parameters()).device if hasattr(self.model, 'parameters') else "unknown"
            print(f" 模型載入成功")
            print(f" 模型設備: {device_info}")
            if torch.cuda.is_available():
                print(f" GPU內存使用: {torch.cuda.memory_allocated() / 1024**3:.2f} GB")

        except Exception as e:
            print(f" 模型載入失敗: {e}")
            self.model = None
            self.tokenizer = None

    def generate_text(self, 
                     prompt: str, 
                     max_new_tokens: int = 50, 
                     temperature: float = 0.7,
                     top_p: float = 0.8) -> str:
        """
        生成文本

        Args:
            prompt: 輸入提示
            max_new_tokens: 最大新token數量
            temperature: 溫度參數
            top_p: Top-p採樣參數

        Returns:
            生成的文本
        """
        if not self.model or not self.tokenizer:
            print(" 模型未正確載入，使用備用生成")
            return self._fallback_generation(prompt)

        try:
            # 構建對話格式
            messages = [
                {"role": "system", "content": "你是一個專業的會議記錄助手，請根據要求生成高品質的內容。"},
                {"role": "user", "content": prompt}
            ]

            # 應用聊天模板
            text = self.tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True
            )

            # 編碼輸入
            model_inputs = self.tokenizer(
                [text], 
                return_tensors="pt",
                truncation=True,
                max_length=2048
            ).to(self.model.device)

            # 更新生成配置
            self.generation_config.max_new_tokens = max_new_tokens
            self.generation_config.temperature = temperature
            self.generation_config.top_p = top_p

            # 生成文本
            with torch.no_grad():
                generated_ids = self.model.generate(
                    **model_inputs,
                    generation_config=self.generation_config,
                    use_cache=True
                )

            # 解碼生成的token
            generated_ids = [
                output_ids[len(input_ids):] 
                for input_ids, output_ids in zip(model_inputs.input_ids, generated_ids)
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
        """備用生成方法"""
        prompt_lower = prompt.lower()

        if "會議主題" in prompt or "meeting topic" in prompt_lower:
            topics = [
                "人工智慧驅動的企業數位轉型策略研討會",
                "ESG永續經營與綠色金融創新論壇",
                "跨國供應鏈韌性建構與風險管理會議",
                "元宇宙商業應用與未來工作模式探討",
                "區塊鏈技術在企業治理中的實踐應用",
                "數據驅動決策與商業智能分析平台建置",
                "遠距協作時代的組織文化重塑會議",
                "綠色科技創新與循環經濟商業模式",
                "客戶體驗數位化轉型與服務設計優化",
                "新興科技趨勢對產業競爭格局的影響分析"
            ]
            return random.choice(topics)

        elif "姓名" in prompt or "name" in prompt_lower:
            surnames = ["陳", "林", "王", "李", "張", "劉", "黃", "吳", "鄭", "謝", "許", "蔡", "楊", "洪", "徐"]
            given_names = [
                "志明", "佳穎", "建華", "雅雯", "俊宇", "思妤", "宗翰", "佩芸",
                "家豪", "怡萱", "承恩", "雅芳", "宇軒", "美慧", "志豪", "詩涵",
                "承翰", "雅婷", "建志", "佳蓉", "宗憲", "美玲", "志偉", "雅琪"
            ]
            return random.choice(surnames) + random.choice(given_names)

        elif "職位" in prompt or "position" in prompt_lower:
            positions = [
                "數位轉型總監", "永續發展經理", "資料科學家", "用戶體驗設計師",
                "區塊鏈技術專家", "人工智慧工程師", "數位行銷策略師", "雲端架構師",
                "產品創新經理", "客戶成功總監", "資訊安全分析師", "業務流程優化專家",
                "敏捷開發教練", "數據治理專員", "創新實驗室負責人", "策略分析師",
                "供應鏈管理專家", "綠色金融顧問", "企業社會責任主管", "數位內容策展人"
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
                "制定創新專案孵化與投資評估機制"
            ]
            return random.choice(actions)

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
    """增強版會議記錄生成器"""

    def __init__(self, 
                 model_path: str = "Qwen/Qwen2.5-7B-Instruct-1M",
                 use_quantization: bool = True):
        """
        初始化生成器

        Args:
            model_path: Qwen模型路徑
            use_quantization: 是否使用量化（節省記憶體）
        """
        self.model_path = model_path
        self.topics_file = "meeting_topics.json"
        self.output_dir = "meeting_records"

        # 創建輸出目錄
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
            print(f" 已創建輸出目錄: {self.output_dir}")

        # 初始化Qwen模型
        self.qwen_model = QwenModelInterface(
            model_path=model_path,
            load_in_4bit=use_quantization  # 使用4bit量化節省記憶體
        )

    def generate_topics(self, count: int = 100) -> List[str]:
        """使用Qwen模型生成會議主題"""
        print(f" 使用Qwen模型生成 {count} 個會議主題...")
        topics = []
        successful_generations = 0

        for i in range(count):
            topic_prompt = """請生成一個現代企業會議主題，要求：
1. 主題要具體、專業且符合2025年商業趨勢
2. 涵蓋數位轉型、永續發展、AI應用、創新管理等領域
3. 長度控制在12-28個繁體中文字符
4. 直接返回會議主題，不要添加引號或其他格式

會議主題："""

            try:
                topic = self.qwen_model.generate_text(
                    topic_prompt, 
                    max_new_tokens=40,
                    temperature=0.8
                )

                # 清理生成的文本
                topic = self._clean_generated_text(topic)

                # 驗證主題品質
                if self._validate_topic(topic):
                    topics.append(topic)
                    successful_generations += 1

                    if (i + 1) % 10 == 0:
                        print(f"   已生成 {successful_generations}/{i + 1} 個有效主題")

            except Exception as e:
                print(f"   生成主題 {i+1} 時發生錯誤: {e}")
                continue

        print(f" 成功生成 {len(topics)} 個高品質會議主題")
        return topics

    def _validate_topic(self, topic: str) -> bool:
        """驗證主題品質"""
        if not topic or len(topic) < 8 or len(topic) > 35:
            return False

        # 檢查是否包含無意義的內容
        invalid_patterns = [
            r'^主題[：:]',
            r'^會議[：:]',
            r'^\d+[.、]',
            r'請生成',
            r'要求',
            r'根據'
        ]

        for pattern in invalid_patterns:
            if re.search(pattern, topic):
                return False

        return True

    def generate_characters(self, topic: str, min_chars: int = 2, max_chars: int = 10) -> List[Dict[str, str]]:
        """使用Qwen模型生成角色"""
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
2. 使用現代企業常見的專業職位
3. 長度控制在4-15個繁體中文字符
4. 體現專業性和現代感
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
                    max_new_tokens=25,
                    temperature=0.7
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

    def generate_todo_items(self, topic: str, min_items: int = 5, max_items: int = 20) -> List[Dict[str, Any]]:
        """使用Qwen模型生成代辦事項"""
        item_count = random.randint(min_items, max_items)
        todo_items = []

        print(f"   為主題「{topic}」生成 {item_count} 個代辦事項...")

        for i in range(item_count):
            action_prompt = f"""請根據會議主題「{topic}」生成一個具體可執行的行動項目，要求：
1. 行動項目必須與會議主題密切相關且具體可行
2. 描述明確的任務和預期成果
3. 長度控制在8-30個繁體中文字符
4. 體現專業性和可操作性
5. 直接返回行動項目，不要其他說明

具體行動項目："""

            try:
                action = self.qwen_model.generate_text(
                    action_prompt, 
                    max_new_tokens=40,
                    temperature=0.75
                )
                action = self._clean_generated_text(action)

                # 驗證代辦事項品質
                if self._validate_action(action):
                    deadline_days = random.randint(7, 30)
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
        if not action or len(action) < 6 or len(action) > 40:
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
            "主題:", "姓名:", "相關職位:", "具體行動項目:"
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
            "generation_method": "Qwen2.5-7B-Instruct using transformers",
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

        print(f" 已將 {len(topics)} 個主題保存到 {self.topics_file}")

    def generate_meeting_dialogue(self, topic: str, characters: List[Dict], todo_items: List[Dict]) -> List[Dict[str, str]]:
        """生成會議對話"""
        if not characters:
            return []

        dialogue = []
        moderator = characters[0]['name']

        # 會議開始
        dialogue.append({
            "speaker": moderator,
            "content": f"各位同事大家好，歡迎參加今天的會議。今天我們討論的主題是「{topic}」，這是一個重要的議題。首先請各位簡單自我介紹。"
        })

        # 自我介紹環節
        intro_count = min(4, len(characters) - 1)
        for char in characters[1:intro_count + 1]:
            dialogue.append({
                "speaker": char['name'],
                "content": f"大家好，我是{char['position']}{char['name']}，很高興參與這次討論。"
            })

        # 議程討論
        dialogue.append({
            "speaker": moderator,
            "content": "感謝各位的介紹。接下來我們來討論具體的執行項目和行動方案。"
        })

        # 代辦事項討論
        discussion_items = min(6, len(todo_items))
        for i, item in enumerate(todo_items[:discussion_items]):
            speaker = characters[i % len(characters)]['name']
            dialogue.append({
                "speaker": speaker,
                "content": f"關於「{item['action']}」這個項目，我建議我們設定在{item['deadline']}完成，優先等級為{item['priority']}。"
            })

            # 其他人回應
            if len(characters) > 1:
                responder = characters[(i + 1) % len(characters)]['name']
                responses = [
                    "這個提案很有建設性，我完全支持這個時程安排。",
                    "時程看起來合理，但我們需要確保資源配置充足。",
                    "我建議我們可以分階段執行，降低實施風險。",
                    "這個項目的成功關鍵在於跨部門的密切協作。",
                    "我們需要事先做好詳細的準備工作和風險評估。",
                    "優先等級設定適當，符合我們的整體策略方向。",
                    "建議我們設立里程碑檢查點，確保執行品質。"
                ]
                dialogue.append({
                    "speaker": responder,
                    "content": random.choice(responses)
                })

        # 會議總結
        dialogue.append({
            "speaker": moderator,
            "content": "今天的討論非常充實且有建設性。請各位按照既定分工執行相關任務，我們將在下次會議檢討執行進度。"
        })

        if len(characters) > 1:
            dialogue.append({
                "speaker": characters[-1]['name'],
                "content": "謝謝大家的積極參與和寶貴意見，期待我們的合作成果。會議結束。"
            })

        return dialogue

    def generate_srt_content(self, dialogue: List[Dict[str, str]], duration_per_line: int = 4) -> str:
        """生成SRT字幕內容"""
        srt_content = []
        current_time = 0

        for i, line in enumerate(dialogue):
            start_time = current_time
            # 根據內容長度動態調整持續時間
            content_length = len(line['content'])
            duration = max(duration_per_line, content_length * 0.15)  # 約每字0.15秒
            end_time = current_time + duration

            # 格式化時間
            start_formatted = self.format_srt_time(start_time)
            end_formatted = self.format_srt_time(end_time)

            # SRT格式
            srt_entry = f"{i + 1}\n{start_formatted} --> {end_formatted}\n{line['speaker']}: {line['content']}\n"
            srt_content.append(srt_entry)

            current_time = end_time + 0.8  # 添加間隔

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

        print(f" 開始批量生成 {total_topics} 個會議記錄...")
        print("=" * 60)

        for i, topic in enumerate(topics, 1):
            try:
                print(f" 處理進度 {i}/{total_topics}: {topic}")

                # 生成會議元素
                characters = self.generate_characters(topic, 3, 8)
                todo_items = self.generate_todo_items(topic, 6, 15)

                if not characters or not todo_items:
                    print(f"   跳過（生成內容不足）")
                    continue

                # 生成對話
                dialogue = self.generate_meeting_dialogue(topic, characters, todo_items)

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
                        "total_duration_seconds": len(dialogue) * 4.8
                    },
                    "generated_at": datetime.now().isoformat(),
                    "model_used": self.model_path
                }

                json_filename = f"{i:03d}-{safe_topic}.json"
                json_filepath = os.path.join(self.output_dir, json_filename)

                with open(json_filepath, 'w', encoding='utf-8') as f:
                    json.dump(meeting_data, f, ensure_ascii=False, indent=2)

                success_count += 1
                print(f"   成功生成: {filename}")

                # 每10個清理一次記憶體
                if i % 10 == 0:
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()

            except Exception as e:
                print(f"   處理主題 {i} 時發生錯誤: {e}")
                continue

        print("=" * 60)
        print(f" 批量生成完成！")
        print(f" 成功生成: {success_count}/{total_topics} 個會議記錄")
        print(f" 輸出目錄: {os.path.abspath(self.output_dir)}")

    def cleanup(self):
        """清理資源"""
        if hasattr(self, 'qwen_model'):
            self.qwen_model.cleanup()


def main():
    """主程序"""
    print("=" * 60)
    print(" 完整版會議記錄生成系統")
    print(" 使用 Qwen/Qwen2.5-7B-Instruct-1M 本地模型")
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
            model_path="Qwen/Qwen2.5-7B-Instruct-1M",
            use_quantization=True  # 使用量化節省記憶體
        )

        # 步驟1: 生成會議主題
        print("\n" + "=" * 40)
        print(" 步驟1: 生成會議主題")
        print("=" * 40)

        topics = generator.generate_topics(100)
        generator.save_topics_to_json(topics)

        # 顯示部分主題樣本
        print("\n 生成的主題樣本:")
        for i, topic in enumerate(topics[:5], 1):
            print(f"  {i}. {topic}")
        if len(topics) > 5:
            print(f"  ... 還有 {len(topics) - 5} 個主題")

        # 步驟2: 生成會議記錄
        print("\n" + "=" * 40)
        print(" 步驟2: 生成完整會議記錄")
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
                print(f"  - {filename} ({file_size} bytes)")

        print(f"\n 程序執行完成！所有會議記錄已生成完畢。")

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