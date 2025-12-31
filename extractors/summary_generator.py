#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SummaryGenerator
生成會議整體摘要（Two-pass summarization）
輸出只包含摘要內容本身
"""

from extractors.base_extractor import BaseExtractor
from datetime import datetime


class SummaryGenerator(BaseExtractor):
    def __init__(self):
        super().__init__("summary")

    def generate(self, segments, people, keypoints, decisions, actions):
        # ======================
        # 第一階段：逐段摘要（loop）
        # ======================
        segment_summaries = []

        for seg in segments:
            text = seg.get("text", "").strip()
            if not text:
                continue

            prompt = (
                "你是一個專業的會議記錄整理助手。\n"
                "請將以下會議段落濃縮成 1～2 句摘要，保留關鍵資訊。\n"
                "請使用正式書面語，不要條列。\n\n"
                f"{text}\n\n"
                "###end###"
            )

            resp = self.generate_response(
                prompt=prompt,
                max_tokens=120
            )

            if resp.strip():
                # 不加段落、不加標記，只收摘要
                segment_summaries.append(resp.strip())

        if not segment_summaries:
            return "（無法生成摘要：沒有有效的會議內容）"

        # ======================
        # 第二階段：整體摘要（單次）
        # ======================
        final_prompt = f"""你是一位資深的會議分析專家，請基於以下已整理的會議資訊，總結整場會議的核心內容。

### 會議基本信息 ###
- 總分段數：{len(segments)} 段
- 分析日期：{datetime.now().strftime('%Y-%m-%d')}

### 逐段摘要 ###
{chr(10).join(segment_summaries)}

### 所有參與人物 ###
{people}

### 核心要點 ###
{keypoints}

### 決策事項 ###
{decisions}

### 行動項目 ###
{actions}

### 任務要求 ###
請基於以上資訊，生成一段完整、通順的會議整體摘要：
1. 使用繁體中文
2. 保留最重要的會議背景、討論重點、決策與後續行動
3. 不要使用條列格式
4. 以正式書面語撰寫

###end###

請開始總結："""

        final_summary = self.generate_response(
            prompt=final_prompt,
            max_tokens=1200
        )

        return final_summary.strip()
