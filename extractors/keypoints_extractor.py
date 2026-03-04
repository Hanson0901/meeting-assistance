#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
KeypointsExtractor
完全比照 PeopleExtractor 的輸出方式：
只輸出重點事項本身，不含段落、不含說明
"""

from extractors.base_extractor import BaseExtractor


class KeypointsExtractor(BaseExtractor):
    def __init__(self):
        super().__init__("keypoints")

    def extract(self, segments):
        """
        依 PeopleExtractor 的方式：
        - 不加 [段落 X]
        - 只輸出模型生成的條列項目
        """
        keypoints = []

        for seg in segments:
            text = seg.get("text", "").strip()
            if not text:
                continue

            # ===== prompt（完全沿用你原本的）=====
            prompt = (
                f"""你是一位專業的內容分析專家，請從以下會議記錄中提取核心要點。

### 任務要求 ###
1. 使用繁體中文回答
2. 提取最多2個最重要的核心要點
3. 按重要性排序

### 輸出格式 ###
1. [關鍵要點] - 簡要說明
2. [關鍵要點] - 簡要說明

### 會議記錄內容  ###
{text[:1500]}
###end###"""
            )

            resp = self.generate_response(
                prompt=prompt,
                max_tokens=300
            )

            for line in resp.splitlines():
                line = line.strip()
                if not line:
                    continue

                # 【完全比照 PeopleExtractor】：只收條列項目本身
                if line.startswith('-'):
                    item = line.lstrip('- ').strip()
                    if item:
                        keypoints.append(item)

        # 最終輸出：純重點事項（每行一個）
        return "\n".join(keypoints)
