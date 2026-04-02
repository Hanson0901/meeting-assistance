import os
import sys
import time  
from pathlib import Path

# 把專案根目錄加進 Python path
project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

import argparse
from speech.pipeline_mkv_read import RealtimeASR


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True)
    ap.add_argument("--outdir", default=".")
    ap.add_argument("--prefix", default="output")
    ap.add_argument("--recording-flag", default="")
    ap.add_argument("--alpha", type=float, default=0.0)
    ap.add_argument("--overlap", type=float, default=5.0)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    asr = RealtimeASR(
        audio_file=args.audio,
        output_dir=args.outdir,
        output_prefix=args.prefix,
        recording_flag_file=(args.recording_flag or None),
        prototype_alpha=args.alpha,
        buffer_overlap=args.overlap,
        verbose=args.verbose,
    )

    print("[run_asr] 開始 ASR 轉錄...\n")

    #  開始計時
    start_time = time.time()

    try:
        asr.start()

    except KeyboardInterrupt:
        print("\n[run_asr] 使用者中斷")

    #  結束計時
    end_time = time.time()
    elapsed = end_time - start_time

    print("\n[run_asr] ASR 結束")
    print(f"[run_asr] ASR 總耗時: {elapsed:.2f} 秒 ")


if __name__ == "__main__":
    main()