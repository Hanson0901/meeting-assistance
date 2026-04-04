#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import argparse
import time
from pathlib import Path

# 專案根目錄
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

from print_log_utils import setup_print_logging
from extractors.actions_extractor import ActionsExtractor


def list_srt_files(output_dir: str, output_prefix: str):
    return sorted(Path(output_dir).glob(f"{output_prefix}_*.srt"))


def srt_to_text(srt_path: str) -> str:
    lines = []
    encodings = ["utf-8", "utf-8-sig", "cp950", "gbk"]

    for enc in encodings:
        try:
            with open(srt_path, "r", encoding=enc) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.isdigit() or "-->" in line:
                        continue
                    lines.append(line)
            break
        except Exception:
            continue

    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-dir", default=".")
    ap.add_argument("--output-prefix", default="output")
    args = ap.parse_args()

    setup_print_logging(
        default_log_path=os.path.join(args.output_dir, f"{args.output_prefix}_run.log"),
        process_name="run_actions_conda",
    )

    script_start = time.perf_counter()

    srt_files = list_srt_files(args.output_dir, args.output_prefix)
    if not srt_files:
        print("[run_actions_conda] 找不到任何 SRT")
        sys.exit(1)

    # ===== 模型載入 =====
    extractor = ActionsExtractor()

    # ===== 模型載入結束 =====
    model_loaded_time = time.perf_counter()

    all_actions = []
    segments = []

    # ===== 生成開始 =====
    generation_start = time.perf_counter()

    for srt in srt_files:

        text = srt_to_text(str(srt)).strip()
        if not text:
            continue

        segment = {"text": text}
        segments.append(segment)

        result = extractor.extract([segment])

        if result and result.strip() != "本段無具體行動項目":
            for line in result.splitlines():
                line = line.strip()
                if line and line not in all_actions:
                    all_actions.append(line)

        if hasattr(extractor, "aggressive_memory_cleanup"):
            extractor.aggressive_memory_cleanup()

    # ===== 生成結束 (寫入 cache 前) =====
    generation_end = time.perf_counter()

    out_json = os.path.join(
        args.output_dir, f"{args.output_prefix}_actions_cache.json"
    )

    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(
            {
                "segments": segments,
                "actions_lines": all_actions,
                "actions_text": "\n".join(all_actions)
                if all_actions
                else "本段無具體行動項目",
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    script_time = time.perf_counter() - script_start
    generation_time = generation_end - generation_start
    model_load_time = model_loaded_time - script_start

    print(f"[run_actions_conda] ACTIONS OK -> {out_json}")
    print(f"[run_actions_conda] 模型載入時間: {model_load_time:.2f} 秒")
    print(f"[run_actions_conda] 生成時間: {generation_time:.2f} 秒")
    print(f"[run_actions_conda] run_actions_conda 總耗時: {script_time:.2f} 秒\n")


if __name__ == "__main__":
    main()