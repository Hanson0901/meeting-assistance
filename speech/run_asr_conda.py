#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
from pathlib import Path

# 把專案根目錄加進 Python path，讓 `import speech...` 一定成功
project_root = Path(__file__).resolve().parents[1]   # .../meeting-assistence
sys.path.insert(0, str(project_root))

import argparse
from speech.pipeline_mkv_read import RealtimeASR

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True)
    ap.add_argument("--outdir", default=".")
    ap.add_argument("--prefix", default="output")
    ap.add_argument("--alpha", type=float, default=0.0)
    ap.add_argument("--overlap", type=float, default=5.0)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    asr = RealtimeASR(
        audio_file=args.audio,
        output_dir=args.outdir,
        output_prefix=args.prefix,
        prototype_alpha=args.alpha,
        buffer_overlap=args.overlap,
        verbose=args.verbose,
    )
    asr.start()

if __name__ == "__main__":
    main()
