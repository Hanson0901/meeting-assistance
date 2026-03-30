#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import argparse
import time
from pathlib import Path

project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

from extractors.summary_generator import SummaryGenerator


def pkda_to_segments(pkda_data: dict):
    segments = []

    if pkda_data.get("people"):
        segments.append({"text": f"與會人員:\n{pkda_data['people']}"})

    if pkda_data.get("keypoints"):
        segments.append({"text": f"會議重點:\n{pkda_data['keypoints']}"})

    if pkda_data.get("decisions"):
        segments.append({"text": f"決策事項:\n{pkda_data['decisions']}"})

    if pkda_data.get("actions_text"):
        segments.append({"text": f"行動項目:\n{pkda_data['actions_text']}"})

    return segments


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-dir", default=".")
    ap.add_argument("--output-prefix", default="output")
    args = ap.parse_args()

    script_start = time.time()

    # ===== 載入模型 =====
    print("[run_summary_conda] 正在初始化 SummaryGenerator（載入模型）...")
    generator = SummaryGenerator()

    # ===== 模型載入結束 =====
    model_loaded_time = time.time()
    model_load_time = model_loaded_time - script_start

    # ===== 讀取 cache =====
    cache_json = os.path.join(
        args.output_dir,
        f"{args.output_prefix}_cache.json"
    )

    print(f"[run_summary_conda] 讀取 cache: {cache_json}\n")

    if not os.path.exists(cache_json):
        print(f"[run_summary_conda]找不到 cache 檔案: {cache_json}")
        sys.exit(1)

    with open(cache_json, "r", encoding="utf-8") as f:
        cache_data = json.load(f)

    people = cache_data.get("people", "") or "(無人物資訊)"
    keypoints = cache_data.get("keypoints", "") or "(無重點資訊)"
    decisions = cache_data.get("decisions", "") or "(無決策資訊)"
    actions = cache_data.get("actions_text", "") or "(無行動項目)"

    segments = pkda_to_segments(cache_data)

    if not segments:
        print(f"[run_summary_conda] cache 內容為空，跳過摘要生成\n")
        sys.exit(0)

    print(f"[run_summary_conda] 生成 {len(segments)} 個資訊區塊進行濃縮摘要\n")

    # ===== 生成開始 =====
    generation_start = time.time()

    result = generator.generate(
        segments=segments,
        people=people,
        keypoints=keypoints,
        decisions=decisions,
        actions=actions,
    )

    # ===== 生成結束 =====
    generation_end = time.time()
    generation_time = generation_end - generation_start

    # ===== 輸出 JSON =====
    out_json = os.path.join(
        args.output_dir,
        f"{args.output_prefix}_summary_cache.json"
    )

    title_value = None
    summary_value = None

    if isinstance(result, dict):

        raw_title = result.get("title")
        raw_summary = result.get("summary")

        if raw_title:
            t = str(raw_title).strip()
            if t and "無法生成標題" not in t:
                title_value = t

        if raw_summary:
            s = str(raw_summary).strip()
            if s and "無法生成摘要" not in s:
                summary_value = s

    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(
            {
                "title": title_value,
                "summary": summary_value
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    script_time = time.time() - script_start

    print(f"[run_summary_conda] SUMMARY OK -> {out_json}")
    print("\n[run_summary_conda] 計時統計:")
    print("[run_summary_conda]=" * 60)
    print(f"[run_summary_conda]  模型載入時間: {model_load_time:.2f} 秒")
    print(f"[run_summary_conda]  推導時間: {generation_time:.2f} 秒")
    print(f"[run_summary_conda]  總耗時: {script_time:.2f} 秒")
    print("[run_summary_conda]=" * 60 + "\n")


if __name__ == "__main__":
    main()