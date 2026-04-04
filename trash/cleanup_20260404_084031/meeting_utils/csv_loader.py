#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import csv


class CSVLoader:
    """CSV 測資載入器（自動處理 BOM）"""

    @staticmethod
    def load(csv_path, text_column="原文"):
        segments = []

        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            # ↑↑↑ 關鍵：utf-8-sig 會自動去掉 \ufeff
            reader = csv.DictReader(f)

            if text_column not in reader.fieldnames:
                raise ValueError(
                    f"CSV 欄位錯誤，找不到 '{text_column}'，實際欄位：{reader.fieldnames}"
                )

            for row in reader:
                text = row[text_column].strip()
                if text:
                    segments.append({"text": text})

        return segments
