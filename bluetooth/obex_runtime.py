# bluetooth/obex_runtime.py
import os
import time
import atexit
import subprocess
from dataclasses import dataclass
from typing import Optional

import dbus

@dataclass
class ObexRuntime:
    session_address: str
    session_pid: Optional[int]
    obexd_proc: subprocess.Popen

    def stop(self):
        # stop obexd
        try:
            if self.obexd_proc and self.obexd_proc.poll() is None:
                self.obexd_proc.terminate()
        except Exception:
            pass
        # stop session dbus-daemon
        try:
            if self.session_pid:
                subprocess.run(["kill", str(self.session_pid)], check=False)
        except Exception:
            pass

_RUNTIME: Optional[ObexRuntime] = None

class ObexError(RuntimeError):
    pass

def ensure_obex_session(root_dir: str = "/", wait_sec: float = 0.8) -> dbus.SessionBus:
    """
    強制建立 session bus + 啟動 obexd，回傳可用的 dbus.SessionBus。
    這個做法不依賴 DISPLAY，headless 可用。
    """
    global _RUNTIME

    # 已經建立過就直接回傳
    if _RUNTIME is not None:
        return dbus.SessionBus()

    # 1) 若本來就有 session bus，就用現成的
    if os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        # 嘗試直接啟 obexd（掛在既有 session bus）
        obexd = _start_obexd(env=os.environ.copy(), root_dir=root_dir)
        _RUNTIME = ObexRuntime(
            session_address=os.environ["DBUS_SESSION_BUS_ADDRESS"],
            session_pid=None,
            obexd_proc=obexd
        )
        atexit.register(_RUNTIME.stop)
        _wait_for_obex(bus=dbus.SessionBus(), wait_sec=wait_sec)
        return dbus.SessionBus()

    # 2) 沒有 session bus：自己起 dbus-daemon --session
    p = subprocess.run(
        ["dbus-daemon", "--session", "--fork", "--print-address=1", "--print-pid=1"],
        check=True,
        capture_output=True,
        text=True
    )
    lines = [ln.strip() for ln in p.stdout.splitlines() if ln.strip()]
    address = None
    pid = None
    for ln in lines:
        if ln.startswith("unix:") or ln.startswith("tcp:"):
            address = ln
        elif ln.isdigit():
            pid = int(ln)

    if not address:
        raise ObexError(f"dbus-daemon 未回傳 session address。stdout={p.stdout!r} stderr={p.stderr!r}")

    env = os.environ.copy()
    env["DBUS_SESSION_BUS_ADDRESS"] = address
    os.environ["DBUS_SESSION_BUS_ADDRESS"] = address  # 讓本 process 後續也吃得到

    obexd = _start_obexd(env=env, root_dir=root_dir)

    _RUNTIME = ObexRuntime(session_address=address, session_pid=pid, obexd_proc=obexd)
    atexit.register(_RUNTIME.stop)

    bus = dbus.SessionBus()
    _wait_for_obex(bus=bus, wait_sec=wait_sec)
    return bus

def _start_obexd(env: dict, root_dir: str) -> subprocess.Popen:
    # -n: foreground（我們用 Popen 背景跑），-r: root
    return subprocess.Popen(
        ["/usr/libexec/bluetooth/obexd", "-n", "-r", root_dir],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

def _wait_for_obex(bus: dbus.SessionBus, wait_sec: float):
    t0 = time.time()
    last_err = None
    while time.time() - t0 < wait_sec:
        try:
            bus.get_object("org.bluez.obex", "/org/bluez/obex")
            return
        except Exception as e:
            last_err = e
            time.sleep(0.1)
    raise ObexError(f"org.bluez.obex 未在 session bus 上就緒（timeout {wait_sec}s）。最後錯誤：{last_err}")
