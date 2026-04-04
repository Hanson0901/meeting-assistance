# bluetooth/bt_bridge.py
import subprocess
import threading
import time
import re
from typing import Callable, Optional

STATUS_RE = re.compile(
    r"^(?P<name>.+?)\s+\((?P<mac>([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2})\):\s+(?P<status>.+)$"
)

def start_bt_v1_2_and_monitor(
    script_path: str,
    sudo: bool,
    on_enter: Callable[[str, str], None],
    on_leave: Callable[[str, str], None],
    auto_start_monitor: bool = True,
    cwd: Optional[str] = None,
):
    """
    啟動 BT_v1_2.py（黑盒）並解析 stdout 來觸發 enter/leave。
    - on_enter(name, mac): 看到 RECONNECTED/NEAR/ONLINE 時從離線變在線
    - on_leave(name, mac): 看到 JUST LOST/OFFLINE 時從在線變離線
    """
    cmd = ["python3", script_path]
    if sudo:
        cmd = ["sudo", "-n"] + cmd

    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        universal_newlines=True,
    )

    # 如果 BT_v1_2.py 會顯示 menu，需要自動送 "5\n" 開始 monitor
    if auto_start_monitor and proc.stdin:
        def _kick():
            time.sleep(1.0)
            try:
                proc.stdin.write("5\n")
                proc.stdin.flush()
            except:
                pass
        threading.Thread(target=_kick, daemon=True).start()

    online_state = {}  # mac -> bool

    def reader():
        if not proc.stdout:
            return
        for line in proc.stdout:
            s = line.strip()
            if not s:
                continue

            # 只要你想 debug，取消下一行註解就能看到原始輸出
            # print("[BT]", s)

            m = STATUS_RE.match(s)
            if not m:
                continue

            name = m.group("name").strip()
            mac = m.group("mac").upper()
            status = m.group("status")

            # 根據 BT_v1_2.py 會印的狀態文字判斷
            # 進入：RECONNECTED / NEAR / ONLINE
            enter_hit = ("RECONNECTED" in status) or ("NEAR" in status) or ("ONLINE" in status and "OFFLINE" not in status)
            # 離開：JUST LOST / OFFLINE
            leave_hit = ("JUST LOST" in status) or ("OFFLINE" in status)

            was = online_state.get(mac, False)

            if enter_hit and not was:
                online_state[mac] = True
                on_enter(name, mac)

            elif leave_hit and was:
                online_state[mac] = False
                on_leave(name, mac)

    threading.Thread(target=reader, daemon=True).start()
    return proc
