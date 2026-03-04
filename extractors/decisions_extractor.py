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
            prompt = (f"""你是一位專業的決策分析專家，請從以下會議記錄中識別決策事項。

                        ### 任務要求 ###
                        1. 使用繁體中文回答
                        2. 識別所有明確的決策、決定或結論
                        3. 如無明確決策，則說明討論性質

                        ### 輸出格式 ###
                        - [具體決策內容]
                        （如無決策，回覆"本段為討論性質，無具體決策"）

                ### 會議記錄內容  ###
                    {text[:1500]}

                    ###end###"""
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
