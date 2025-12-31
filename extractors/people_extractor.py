#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PeopleExtractor
（依你貼的 extract_all_people_loop 改寫，回傳 SRT）
"""

from extractors.base_extractor import BaseExtractor
from typing import List, Dict


def seconds_to_srt_time(sec: float) -> str:
    """秒數轉 SRT 時間格式"""
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    ms = int((sec - int(sec)) * 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


class PeopleExtractor(BaseExtractor):
    def __init__(self):
        super().__init__("people")

    def extract(self, segments: List[Dict]) -> str:
        """
        用 for 迴圈逐段提取人物，最後回傳 SRT 格式字串
        """
        srt_blocks = []

        for idx, seg in enumerate(segments, 1):
            text = seg.get("text", "").strip()
            if not text:
                continue

            prompt = f"""你是一位專業的人物識別專家，請從以下會議記錄中識別出現的人物。

### 任務要求 ###
1. 使用繁體中文回答
2. 準確識別所有提到的人物姓名
3. 分析每個人物的職位/角色
4. 說明他們在本段中的主要貢獻或發言重點

### 輸出格式 ###
### 出現人物
- [人物名稱] - [職位/角色] - [主要貢獻或發言重點]
（如本段無明確人物，則回覆"本段無具體人物提及"）

### 會議記錄內容 ###
{text[:1500]}

###end###

請開始識別："""

            content = self.generate_response(
                prompt=prompt,
                max_tokens=200
            ).strip()

            # ===== SRT 時間 =====
            start_sec = seg.get("start", (idx - 1) * 5)
            end_sec = seg.get("end", idx * 5)

            start_time = seconds_to_srt_time(start_sec)
            end_time = seconds_to_srt_time(end_sec)

            srt_block = (
                f"{idx}\n"
                f"{start_time} --> {end_time}\n"
                f"{content}\n"
            )

            srt_blocks.append(srt_block)

        return "\n".join(srt_blocks)
