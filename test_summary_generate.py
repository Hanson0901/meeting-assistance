#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path

from extractors.people_extractor import PeopleExtractor
from extractors.keypoints_extractor import KeypointsExtractor
from extractors.decisions_extractor import DecisionsExtractor
from extractors.actions_extractor import ActionsExtractor
from extractors.summary_generator import SummaryGenerator


def test_one(name, func):
    print(f"\n===== Testing {name} =====")
    result = func()
    print(result)
    assert isinstance(result, str)
    assert len(result.strip()) > 0
    print(f"✓ {name} OK")
    return result


def load_srt_texts(output_dir=".", output_prefix="output"):
    """
    讀取 output_*.srt → 轉成 segments = [{"text": ...}, ...]
    注意：這裡採「逐 SRT / 逐段」，每個 SRT 變成一個 segment
    """
    pattern = f"{output_prefix}_*.srt"
    srt_files = sorted(Path(output_dir).glob(pattern))
    if not srt_files:
        raise FileNotFoundError(f"No SRT matched: {output_dir}/{pattern}")

    # 用 ActionsExtractor 的 srt_file_to_text 來轉文字（沿用你現有的方法）
    a = ActionsExtractor()
    segments = []
    for srt in srt_files:
        text = a.srt_file_to_text(str(srt)).strip()
        if text:
            segments.append({"text": text})

    if not segments:
        raise ValueError("All SRTs are empty after conversion.")

    return segments


def main():
    output_dir = "."
    output_prefix = "output"

    segments = load_srt_texts(output_dir=output_dir, output_prefix=output_prefix)

    people_extractor = PeopleExtractor()
    keypoints_extractor = KeypointsExtractor()
    decisions_extractor = DecisionsExtractor()
    actions_extractor = ActionsExtractor()
    summary_generator = SummaryGenerator()

    people = test_one("PeopleExtractor", lambda: people_extractor.extract(segments))
    keypoints = test_one("KeypointsExtractor", lambda: keypoints_extractor.extract(segments))
    decisions = test_one("DecisionsExtractor", lambda: decisions_extractor.extract(segments))
    actions = test_one("ActionsExtractor", lambda: actions_extractor.extract(segments))

    # ✅ SummaryGenerator driver：跟你給的 generate(...) 接口一致
    summary = test_one(
        "SummaryGenerator",
        lambda: summary_generator.generate(
            segments=segments,
            people=people,
            keypoints=keypoints,
            decisions=decisions,
            actions=actions,
        ),
    )

    out_path = Path(output_dir) / f"{output_prefix}_summary.txt"
    out_path.write_text(summary + "\n", encoding="utf-8")
    print(f"\n💾 Summary saved to: {out_path}\n")


if __name__ == "__main__":
    main()
