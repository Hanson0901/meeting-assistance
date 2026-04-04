class TxtLoader:
    @staticmethod
    def load(path):
        segments = []
        current_speaker = None

        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for lineno, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue

                # [Speaker] or 【Speaker】
                if (
                    (line.startswith("[") and line.endswith("]")) or
                    (line.startswith("【") and line.endswith("】"))
                ):
                    current_speaker = line[1:-1].strip()
                    continue

                segments.append({
                    "speaker": current_speaker or "",
                    "text": line
                })

        if not segments:
            raise RuntimeError("❌ TxtLoader：沒有解析出任何 segments")

        return segments
