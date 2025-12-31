#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ActionsExtractor
- 嚴格抽取「已明確決定 / 指派 / 要求執行」的行動項目
- 不將建議、討論、背景、他國經驗誤判為行動
- 無行動項目時不輸出
- 含 deterministic 後處理（防重複 / 防誤抓）
"""

from extractors.base_extractor import BaseExtractor


class ActionsExtractor(BaseExtractor):
    def __init__(self):
        super().__init__("actions")

        # ❗ 行動抽取黑名單（語氣 / 背景 / 建議）
        self.BLACKLIST = [
            "建議", "可以", "是否", "該於", "考慮", "希望", "詢問",
            "分享", "經驗", "他國", "例如", "說明", "背景",
            "如果", "可能", "原則上", "可以參考", "建議可以" # 濾除純建議
        ]
    def extract(self, segments):
        actions = []

        for idx, seg in enumerate(segments):
            text = seg.get("text", "").strip()
            if not text:
                continue
            start_time = seg.get("start_time_str", "")
            end_time = seg.get("end_time_str", "")

            prompt = f"""<SYSTEM_INSTRUCTION>
## 角色說明
你是一位專業的高階行政秘書，負責從會議逐字稿中提取「會後需執行」的任務清單，這是一份行政會議記錄摘要，僅用於內部流程管理。確保所有的項目都是相同的格式。

## 判斷準則 (嚴格執行)
1. 排除「已完成事項」與「現場報告」：僅提取會議結束後才要啟動的任務。
2. 排除「外部建議」：除非主持人明確下令執行，否則不提取外部專家的分享或建議。
3. 角色判定：若 A 指派 B 做事，負責人應填 B，而非指派者。
4. 嚴禁複誦：禁止輸出本指令中的任何標題、規則、範例或提示文字。

## 提取規則
- 待辦事項：以動詞開頭，不要加入時間的描述，將時間相關的描述都交給期限/時間。
- 負責人：標註執行者或單位，必須是本機構人員、內部單位或與會者。若未指派則填「待定」。
- 期限/時間：若原文有明確提到日期則填寫，若日期模糊或不確定，請填寫「依會議決議辦理」或「未定」
- 若沒有符合條件的待辦事項，請回覆「本段無具體行動項目」。
- 嚴格遵守輸出格式 待辦內容  -  負責人/單位  -  期限/時間 。
- 將[待辦內容] - [負責人/單位] - [期限/時間]作為第一項輸出。

## 完成提取輸出結果之前
確認每一項目都符合輸出格式，有內容、負責人/單位、期限/時間，不要輸出不完整項目、重複項目、提示詞。
</SYSTEM_INSTRUCTION>

<OUTPUT_FORMAT>
- [待辦內容] - [負責人/單位] - [期限/時間]
</OUTPUT_FORMAT>

<MEETING_TRANSCRIPT>
{text[:1500]}
</MEETING_TRANSCRIPT>

###end###
請開始識別：
"""

            resp = self.generate_response(
                prompt=prompt,
                max_tokens=200
            ).strip()

            # ===== 無行動項目 =====
            if "本段無具體行動項目" in resp:
                continue

            # ===== 條列抽取 + 黑名單過濾 =====
            for line in resp.splitlines():
                line = line.strip()
                if not line.startswith("-"):
                    continue

                item = line.lstrip("- ").strip()
                if not item:
                    continue

                # ❌ 黑名單語氣直接丟棄
                if any(word in item for word in self.BLACKLIST):
                    continue

                actions.append(item)

        # ===== 去重（保持原順序）=====
        seen = set()
        deduped = []
        for a in actions:
            if a not in seen:
                deduped.append(a)
                seen.add(a)

        return "\n".join(deduped)



#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# """
# ActionsExtractor
# - 使用使用者定義的「行動規劃專家 prompt」
# - 嚴格限制只擷取文本中明確行動
# - 無行動項目時不產生輸出
# """

# from extractors.base_extractor import BaseExtractor


# class ActionsExtractor(BaseExtractor):
    # def __init__(self):
        # super().__init__("actions")
# 
    # def extract(self, segments):
        # actions = []

        # for idx, seg in enumerate(segments):
            # text = seg.get("text", "").strip()
            # if not text:
                # continue

            # start_time = seg.get("start_time_str", "")
            # end_time = seg.get("end_time_str", "")

            # prompt = f"""
# 你是一位「會議行動項目抽取器」。

# 請僅根據以下會議逐字內容，抽取「已明確決定、指派或要求後續執行」的行動項目。

# 【嚴格規則】
# 1. 只能使用原文中「確定要做」的事項
# 2. 不得將建議、背景說明、他國經驗、假設性語句視為行動
# 3. 不得自行補上負責人或時間
# 4. 同一行動項目只可出現一次
# 5. 若只是討論、分享、建議，請忽略
# 【輸出格式】
# - 行動內容｜負責人（若有）｜時間（若有）

# 若無任何明確行動項目，請只輸出：
# 本段無具體行動項目



### 會議記錄內容 ###
# 【分段 {idx}】({start_time} - {end_time})
# {text[:1500]}

###end###
# 請開始識別：
# """

            # resp = self.generate_response(
        # prompt=prompt,
        # max_tokens=200
        # ).strip()


            # ===== 無行動項目直接略過 =====
            # if "本段無具體行動項目" in resp:
                # continue

            # ===== 只收集條列 =====
            # for line in resp.splitlines():
                # line = line.strip()
                # if line.startswith("-"):
                    # item = line.lstrip("- ").strip()
                    # if item:
                        # actions.append(item)
        # return "\n".join(actions)
# 