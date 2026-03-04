#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import argparse
from pathlib import Path

# 專案根目錄
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

from extractors.summary_generator import SummaryGenerator


def list_srt_files(output_dir: str, output_prefix: str):
    return sorted(Path(output_dir).glob(f"{output_prefix}_*.srt"))


def srt_to_segments(srt_path: str, max_chars: int = 500):
    """
    將 SRT 轉成 SummaryGenerator 可用的 segments
    """
    segments = []
    buffer = ""

    encodings = ["utf-8", "utf-8-sig", "cp950", "gbk"]
    lines = []
    for enc in encodings:
        try:
            with open(srt_path, "r", encoding=enc) as f:
                lines = f.readlines()
            break
        except Exception:
            continue

    for line in lines:
        line = line.strip()
        if not line or line.isdigit() or "-->" in line:
            continue

        if len(buffer) + len(line) > max_chars:
            segments.append({"text": buffer.strip()})
            buffer = line
        else:
            buffer += " " + line if buffer else line

    if buffer:
        segments.append({"text": buffer.strip()})

    return segments


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-dir", default=".")
    ap.add_argument("--output-prefix", default="output")
    args = ap.parse_args()

    srt_files = list_srt_files(args.output_dir, args.output_prefix)
    if not srt_files:
        print("❌ 找不到任何 SRT")
        sys.exit(1)

    generator = SummaryGenerator()

    all_segments = []
    for srt in srt_files:
        all_segments.extend(srt_to_segments(str(srt)))

    if not all_segments:
        print("⚠️ 沒有可用摘要內容，使用空摘要 fallback")
        all_segments = [{
            "text": (
                "本次會議未能取得足夠語音或文字資料，"
                "系統無法生成具體摘要。"
                "以下為系統自動產生之會議摘要占位內容。"
            )
        }]


    summary = generator.generate(
        segments=all_segments,
        people=None,
        keypoints=None,
        decisions=None,
        actions=None,
    )

    out_json = os.path.join(
        args.output_dir, f"{args.output_prefix}_summary_cache.json"
    )

    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(
            {"summary": summary.strip()},
            f,
            ensure_ascii=False,
            indent=2,
        )

    print(f"SUMMARY OK -> {out_json}")


if __name__ == "__main__":
    main()
