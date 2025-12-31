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
                "你是一個會議記錄整理助手。\n"
                "請從以下會議內容中，整理出該段落的重點事項。\n"
                "重點應包含重要討論內容、關鍵資訊與共識。\n"
                "請以條列清單輸出，不要加入多餘說明。\n\n"
                f"{text}\n\n"
                "###end###"
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
