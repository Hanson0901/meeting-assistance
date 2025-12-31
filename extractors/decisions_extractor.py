#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
DecisionsExtractor
完全比照 People / Keypoints 的輸出方式：
只輸出決策事項本身，不含段落、不含說明
"""

from extractors.base_extractor import BaseExtractor


class DecisionsExtractor(BaseExtractor):
    def __init__(self):
        super().__init__("decisions")

    def extract(self, segments):
        """
        依 People / Keypoints 的方式：
        - 不加 [段落 X]
        - 只輸出模型生成的條列項目
        """
        decisions = []

        for seg in segments:
            text = seg.get("text", "").strip()
            if not text:
                continue

            # ===== prompt（完全沿用你原本的）=====
            prompt = (
                "你是一個會議記錄整理助手。\n"
                "請從以下會議內容中，整理出已達成的決策、共識或結論。\n"
                "僅列出『已確定』的事項，不要包含仍在討論中的想法。\n"
                "請以條列清單輸出，不要加入解釋說明。\n\n"
                f"{text}\n\n"
                "###end###"
            )

            resp = self.generate_response(
                prompt=prompt,
                max_tokens=250
            )

            for line in resp.splitlines():
                line = line.strip()
                if not line:
                    continue

                # 【完全比照前兩個】：只收 - 開頭
                if line.startswith('-'):
                    item = line.lstrip('- ').strip()
                    if item:
                        decisions.append(item)

        # 最終輸出：純決策事項（每行一個）
        return "\n".join(decisions)
