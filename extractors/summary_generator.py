from extractors.base_extractor import BaseExtractor
from datetime import datetime
import re

class SummaryGenerator(BaseExtractor):
    def __init__(self):
        super().__init__("summary")

    @staticmethod
    def post_process(text: str) -> str:
        if not text:
            return ""

        # 1) 移除常見干擾字樣/分隔線/自我檢核
        text = re.sub(r"(最終輸出|符合所有要求|最終回應|輸出完成)\s*[:：]?\s*", "", text)
        text = text.replace("（最終輸出完成）", "")
        text = re.sub(r"^-{3,}\s*$", "", text, flags=re.MULTILINE)

        # 2) 行級去重（保留第一次出現，維持順序）
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        unique_lines = list(dict.fromkeys(lines))

        # 3) 合併回段落（避免變條列）
        clean_text = " ".join(unique_lines)

        # 4) 簡單處理「A。A。」這種句子連續重複（可選）
        clean_text = re.sub(r"(.{6,30}[。！？])\s*\1+", r"\1", clean_text)

        return clean_text.strip()
    def generate(self, segments, people, keypoints, decisions, actions):
        # =====================================================
        # 第一階段：逐段摘要（loop）——已停用（不使用 segments）
        # =====================================================
        # segment_summaries = []
        #
        # for seg in segments:
        #     text = seg.get("text", "").strip()
        #     if not text:
        #         continue
        #
        #     prompt = (
        #         "你是一個專業的會議記錄整理助手。\n"
        #         "請將以下會議段落濃縮成 1～2 句摘要，保留關鍵資訊。\n"
        #         "請使用正式書面語，不要條列。\n\n"
        #         f"{text}\n\n"
        #         "###end###"
        #     )
        #
        #     resp = self.generate_response(
        #         prompt=prompt,
        #         max_tokens=120
        #     )
        #
        #     if resp.strip():
        #         segment_summaries.append(resp.strip())
        #
        # if not segment_summaries:
        #     return "（無法生成摘要：沒有有效的會議內容）"

        # =====================================================
        # 第二階段：整體摘要（單次）——改為只用 P/K/D/Actions
        # =====================================================
        # segments 仍保留參數是為了相容 pipeline，但不作為內容來源
        seg_count = 0
        try:
            seg_count = len(segments) if segments is not None else 0
        except Exception:
            seg_count = 0

        final_prompt = f"""你是一位資深的會議分析專家，請基於以下已整理的會議資訊，總結整場會議的核心內容。

### 會議基本信息 ###
- 分析日期：{datetime.now().strftime('%Y-%m-%d')}
- 段落數（供參考）：{seg_count}

### 所有參與人物 ###
{people}

### 核心要點 ###
{keypoints}

### 決策事項 ###
{decisions}

### 行動項目 ###
{actions}
### 輸出規範 ###
- 僅限繁體中文，採用流暢的段落敘述（非條列式）。
- 嚴禁包含任何標題、前言（如：這是一份摘要）、自我檢核文字或結束語。
- 若資訊不足，僅回覆「無法生成摘要」。
- 內容須整合討論重點、決策與行動項，避免資訊重複。


###end###

請開始總結："""

        final_summary = self.generate_response(
            prompt=final_prompt,
            max_tokens=1200
        )

        return final_summary.strip() if final_summary else "（無法生成摘要：模型未回傳內容）"

        