#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, sys, argparse, json, time
from pathlib import Path

project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

from pkd_worker import run_pkd

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-dir", default=".")
    ap.add_argument("--output-prefix", default="output")
    ap.add_argument("--model-path", required=True)
    ap.add_argument("--interval-minutes", type=int, default=5)
    ap.add_argument("--overlap-seconds", type=int, default=60)
    args = ap.parse_args()

    script_start = time.time()
    
    data = run_pkd(
        output_dir=args.output_dir,
        output_prefix=args.output_prefix,
        model_path=args.model_path,
        interval_minutes=args.interval_minutes,
        overlap_seconds=args.overlap_seconds,
    )

    out_json = os.path.join(args.output_dir, f"{args.output_prefix}_pkd_cache.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    script_time = time.time() - script_start
    print(f"[run_pkd_conda] PKD OK -> {out_json}")
    print(f"[run_pkd_conda] 總耗時: {script_time:.2f} 秒\n")

if __name__ == "__main__":
    main()
