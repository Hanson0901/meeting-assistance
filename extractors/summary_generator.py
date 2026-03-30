from extractors.base_extractor import BaseExtractor
from datetime import datetime
import re
import json


class SummaryGenerator(BaseExtractor):
    def __init__(self):
        super().__init__("summary")

    @staticmethod
    def post_process(text: str) -> str:
        if not text:
            return ""

        text = re.sub(r"(最終輸出|符合所有要求|最終回應|輸出完成|總結)\s*[:：]?\s*", "", text)
        text = text.replace("（最終輸出完成）", "")
        text = re.sub(r"^-{3,}\s*$", "", text, flags=re.MULTILINE)

        text = re.sub(r"(請開始|請開始總結|下面開始|總結如下|具體如下|內容如下|詳情如下|以下是|以下為)\s*[:：]?\s*", "", text)
        text = re.sub(r"^(基於|根據|根據上述|綜合|綜合上述).*?[:：]\s*", "", text, flags=re.MULTILINE)

        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        unique_lines = list(dict.fromkeys(lines))

        clean_text = " ".join(unique_lines)

        clean_text = re.sub(r"(.{6,30}[。！？])\s*\1+", r"\1", clean_text)

        sentences = re.split(r'([。！？])', clean_text)
        unique_sentences = []
        seen_sentences = set()

        for i in range(0, len(sentences), 2):
            if i < len(sentences):
                sent = sentences[i].strip()
                punct = sentences[i + 1] if i + 1 < len(sentences) else '。'

                if sent and sent not in seen_sentences:
                    unique_sentences.append(sent + punct)
                    seen_sentences.add(sent)

        clean_text = "".join(unique_sentences).strip()

        return clean_text

    def parse_model_output(self, text: str):
        """
        從模型輸出解析 title / summary
        """
        if not text:
            return None, None

        try:
            data = json.loads(text)
            return data.get("title"), data.get("summary")
        except Exception:
            pass

        match = re.search(r"\{.*\}", text, re.S)
        if match:
            try:
                data = json.loads(match.group())
                return data.get("title"), data.get("summary")
            except Exception:
                pass

        return None, None

    def generate(self, segments, people, keypoints, decisions, actions):

        seg_count = 0
        try:
            seg_count = len(segments) if segments is not None else 0
        except Exception:
            seg_count = 0

        final_prompt = f"""你是一位資深的會議分析專家，請基於以下已整理的會議資訊生成會議標題與摘要。

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

### 任務 ###
1. 生成一個精簡的會議標題（10~20字）
2. 生成一段約200字的會議摘要

### 輸出格式（必須為 JSON） ###
{{
"title": "會議標題",
"summary": "會議摘要"
}}

### 規範 ###
- 僅限繁體中文
- 不要任何解釋文字
- 摘要應該清晰、具體，避免模糊和籠統的描述
- 標題應該能夠概括會議的核心主題
- 若資訊不足輸出
{{"title":"會議標題","summary":"無法生成摘要"}}

###end###
"""

        model_output = self.generate_response(
            prompt=final_prompt,
            max_tokens=1200
        )

        title, summary = self.parse_model_output(model_output)

        if summary:
            summary = self.post_process(summary)

        return {
            "title": title if title else "（無法生成標題）",
            "summary": summary if summary else "（無法生成摘要）"
        }