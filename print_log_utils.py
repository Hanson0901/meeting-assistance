#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import builtins
import datetime
import os
import threading

_ORIGINAL_PRINT = builtins.print
_PRINT_PATCHED = False


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
