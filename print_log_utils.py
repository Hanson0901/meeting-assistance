#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import builtins
import datetime
import glob
import os
import threading
from collections import deque
from typing import List, Optional, Tuple

_ORIGINAL_PRINT = builtins.print
_PRINT_PATCHED = False
_LOG_CALLBACK = None  # 日誌回調函數


def set_log_callback(callback):
    """設置日誌回調函數
    
    回調函數簽名: callback(message: str, prefix: str, timestamp: str)
    """
    global _LOG_CALLBACK
    _LOG_CALLBACK = callback


def setup_print_logging(default_log_path: str = None, process_name: str = "", announce: bool = True):
    """Patch builtins.print so all print output is also appended to a log file."""
    global _PRINT_PATCHED

    if _PRINT_PATCHED:
        return os.environ.get("MEETING_LOG_FILE", default_log_path)

    log_path = os.environ.get("MEETING_LOG_FILE") or default_log_path
    if not log_path:
        return None

    log_path = os.path.abspath(log_path)
    os.environ["MEETING_LOG_FILE"] = log_path

    log_dir = os.path.dirname(log_path) or "."
    os.makedirs(log_dir, exist_ok=True)

    lock = threading.Lock()

    def _logged_print(*args, **kwargs):
        _ORIGINAL_PRINT(*args, **kwargs)

        sep = kwargs.get("sep", " ")
        end = kwargs.get("end", "\n")
        message = sep.join(str(a) for a in args) + end
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        prefix = f"[{timestamp}]"
        if process_name:
            prefix += f"[{process_name}]"

        # 調用日誌回調函數
        if _LOG_CALLBACK:
            try:
                _LOG_CALLBACK(message.rstrip('\n'), prefix, timestamp, process_name)
            except Exception:
                pass

        try:
            with lock:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(f"{prefix} {message}")
        except Exception:
            pass

    builtins.print = _logged_print
    _PRINT_PATCHED = True

    if announce:
        _ORIGINAL_PRINT(f"[print_log_utils] log file: {log_path}")

    return log_path


# ==========================================
# 歷史 Session 日誌讀取工具
# ==========================================
# 下方工具函數主要用於Web介面查看歷史 session 的執行日誌
# (web_output/<session_id>/{prefix}_run.log)，讓使用者可以在網頁上
# 正確、完整地看到每個步驟（包含透過 sudo 執行的 conda worker）
# 寫入的完整執行紀錄。


def find_session_log_file(output_dir: str, output_prefix: str = "output") -> Optional[str]:
    """尋找某個 session 輸出目錄下實際使用中的執行日誌檔案。

    優先回傳固定名稱 "{prefix}_run.log"（目前版本的標準命名，
    同一 session 的所有步驟都寫入這一份檔案）。若不存在，
    則向下相容：尋找舊版本帶時間戳的 "{prefix}_run_*.log"，
    並回傳最新修改的一份。找不到任何日誌檔則回傳 None。
    """
    if not output_dir or not os.path.isdir(output_dir):
        return None

    fixed_path = os.path.join(output_dir, f"{output_prefix}_run.log")
    if os.path.exists(fixed_path):
        return fixed_path

    candidates = glob.glob(os.path.join(output_dir, f"{output_prefix}_run_*.log"))
    if not candidates:
        return None

    candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return candidates[0]


def read_log_tail(log_path: Optional[str], max_lines: int = 500) -> Tuple[List[str], int]:
    """有效地讀取日誌檔案的最後 N 行，避免將整個大檔案載入記憶體。

    Args:
        log_path: 日誌檔案路徑，若為 None 或不存在則回傳空列表。
        max_lines: 最大回傳行數。傳入 <= 0 表示回傳整個檔案內容。

    Returns:
        (lines, total_lines): lines 為字串列表（不含換行符），
        total_lines 為檔案實際總行數。
    """
    if not log_path or not os.path.exists(log_path):
        return [], 0

    total_lines = 0
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            if max_lines is None or max_lines <= 0:
                lines = [line.rstrip("\n") for line in f]
                total_lines = len(lines)
                return lines, total_lines

            buf = deque(maxlen=max_lines)
            for line in f:
                buf.append(line.rstrip("\n"))
                total_lines += 1
            return list(buf), total_lines
    except Exception:
        return [], 0


def classify_log_line(line: str) -> str:
    """根據日誌行內容判斷顯示等級（與前端 app.js 的分類規則保持一致）。

    回傳值：'error' | 'warning' | 'success' | 'step' | 'debug' | 'info'
    """
    if not line:
        return "info"
    if "[ERROR]" in line or "\u274c" in line or "\u7570\u5e38" in line:
        return "error"
    if "[WARN]" in line or "\u26a0" in line:
        return "warning"
    if "\u2713" in line or "[SUCCESS]" in line:
        return "success"
    if "[STEP]" in line or "\u5df2\u958b\u59cb" in line or "\u5b8c\u6210" in line:
        return "step"
    if "[DEBUG]" in line:
        return "debug"
    return "info"
