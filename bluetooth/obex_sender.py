import subprocess
import time
import re
from pathlib import Path
from typing import List, Tuple, Optional


class ObexPushError(RuntimeError):
    pass


MAC_RE = re.compile(r"^Device\s+(([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2})\s+(.+)$")


def _run(cmd: List[str], timeout: int = 10) -> str:
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=timeout)
    return p.stdout


def list_paired_devices() -> List[Tuple[str, str]]:
    """
    回傳 [(mac, name), ...]，來自 bluetoothctl paired-devices
    """
    out = _run(["bluetoothctl", "paired-devices"], timeout=10)
    devices = []
    for line in out.splitlines():
        line = line.strip()
        m = MAC_RE.match(line)
        if m:
            mac = m.group(1).upper()
            name = m.group(3).strip()
            devices.append((mac, name))
    return devices


def is_device_trusted(mac: str) -> bool:
    out = _run(["bluetoothctl", "info", mac], timeout=10)
    # BlueZ info 裡通常有 "Trusted: yes"
    for line in out.splitlines():
        if "Trusted:" in line:
            return "yes" in line.lower()
    return False


def is_device_connected(mac: str) -> bool:
    out = _run(["bluetoothctl", "info", mac], timeout=10)
    for line in out.splitlines():
        if "Connected:" in line:
            return "yes" in line.lower()
    return False


def obex_push_files(target_mac: str, files: List[str], timeout_sec: int = 60) -> None:
    """
    使用 obexctl 對 target_mac 做 OBEX Push 傳檔。
    """
    paths = []
    for f in files:
        p = Path(f).expanduser().resolve()
        if not p.exists():
            raise ObexPushError(f"file not found: {p}")
        paths.append(str(p))

    proc = subprocess.Popen(
        ["obexctl"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        universal_newlines=True,
    )
    if not proc.stdin:
        raise ObexPushError("failed to start obexctl")

    def send(line: str):
        proc.stdin.write(line + "\n")
        proc.stdin.flush()

    try:
        send(f"connect {target_mac}")
        time.sleep(1.0)

        for p in paths:
            send(f"push {p}")
            time.sleep(2.0)

        send("disconnect")
        send("quit")
        proc.wait(timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except Exception:
            pass
        raise ObexPushError("obexctl timeout")
    finally:
        try:
            if proc.poll() is None:
                proc.terminate()
        except Exception:
            pass


def auto_find_target_device(prefer_connected: bool = True, require_trusted: bool = True) -> Optional[Tuple[str, str]]:
    """
    自動挑一個「最可能的 user 裝置」：
    - 優先：已連線 (Connected: yes)
    - 其次：已信任 (Trusted: yes) 的已配對裝置
    """
    devices = list_paired_devices()
    if not devices:
        return None

    connected = []
    trusted = []
    others = []

    for mac, name in devices:
        try:
            conn = is_device_connected(mac)
        except Exception:
            conn = False
        try:
            tr = is_device_trusted(mac)
        except Exception:
            tr = False

        if conn:
            connected.append((mac, name))
        elif tr:
            trusted.append((mac, name))
        else:
            others.append((mac, name))

    if prefer_connected and connected:
        return connected[0]
    if require_trusted and trusted:
        return trusted[0]
    # 最後退一步：任一已配對裝置
    return trusted[0] if trusted else (others[0] if others else None)


def auto_push(files: List[str], max_try: int = 5) -> Tuple[str, str]:
    """
    不提供 MAC：自動找裝置並嘗試推送。
    會依序嘗試：
    1) Connected 裝置
    2) Trusted 裝置
    3) 其他 paired 裝置
    任一成功即回傳 (mac, name)
    """
    devices = list_paired_devices()
    if not devices:
        raise ObexPushError("no paired devices; please pair/trust your phone first")

    # 排序：Connected 優先，其次 Trusted，再來其他
    ranked = []
    for mac, name in devices:
        conn = False
        tr = False
        try:
            conn = is_device_connected(mac)
        except Exception:
            pass
        try:
            tr = is_device_trusted(mac)
        except Exception:
            pass
        score = (2 if conn else 0) + (1 if tr else 0)
        ranked.append((score, mac, name))

    ranked.sort(reverse=True, key=lambda x: x[0])

    tried = 0
    last_err = None

    for _, mac, name in ranked:
        tried += 1
        if tried > max_try:
            break
        try:
            obex_push_files(mac, files)
            return mac, name
        except Exception as e:
            last_err = e

    raise ObexPushError(f"auto push failed; tried {min(tried, max_try)} devices; last error={last_err}")
