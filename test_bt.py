#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
修正版藍牙模組 - 適用於無 GUI 環境
解決 "Unable to autolaunch a dbus-daemon without a $DISPLAY" 問題
"""

import os
import time
import subprocess
import atexit
import signal
import dbus
import dbus.service

# 全域變數
_OBEXD_PROC = None
_DBUS_DAEMON_PROC = None
_DBUS_DAEMON_PID = None


def _create_headless_session_bus():
    """
    在無 GUI 環境下創建 Session Bus
    """
    global _DBUS_DAEMON_PROC, _DBUS_DAEMON_PID
    
    # 如果已經有 session bus，直接返回
    if os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        print("✓ 使用現有 Session Bus")
        return True
    
    print("📡 在無 GUI 環境下創建 Session Bus...")
    
    # 創建臨時配置目錄
    runtime_dir = "/tmp/dbus-session-runtime"
    os.makedirs(runtime_dir, exist_ok=True)
    os.chmod(runtime_dir, 0o700)
    
    # 啟動 dbus-daemon（使用 --nofork 讓我們可以控制它）
    try:
        # 方法1: 使用 --print-address 獲取地址
        cmd = [
            "dbus-daemon",
            "--session",
            "--nofork",  # 不要 fork，讓我們控制進程
            "--print-address=1"
        ]
        
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=os.environ.copy()
        )
        
        # 讀取第一行（應該是 address）
        # 設置超時避免永久阻塞
        import select
        ready = select.select([proc.stdout], [], [], 5.0)
        if ready[0]:
            address = proc.stdout.readline().strip()
            if address and (address.startswith("unix:") or "tcp:" in address):
                os.environ["DBUS_SESSION_BUS_ADDRESS"] = address
                _DBUS_DAEMON_PROC = proc
                _DBUS_DAEMON_PID = proc.pid
                print(f"✓ Session Bus 已創建 (PID: {proc.pid})")
                print(f"  地址: {address}")
                time.sleep(0.5)
                return True
        
        # 如果上面失敗，終止進程
        proc.terminate()
        
    except Exception as e:
        print(f"方法1失敗: {e}")
    
    # 方法2: 使用 dbus-launch（更簡單）
    try:
        print("嘗試使用 dbus-launch...")
        result = subprocess.run(
            ["dbus-launch"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True
        )
        
        # 解析輸出
        for line in result.stdout.splitlines():
            if "DBUS_SESSION_BUS_ADDRESS=" in line:
                address = line.split("=", 1)[1].strip("'\"")
                os.environ["DBUS_SESSION_BUS_ADDRESS"] = address
                print(f"✓ 使用 dbus-launch 創建 Session Bus")
                print(f"  地址: {address}")
                return True
            if "DBUS_SESSION_BUS_PID=" in line:
                pid = line.split("=", 1)[1].strip("'\"")
                _DBUS_DAEMON_PID = int(pid)
        
        return True
        
    except Exception as e:
        print(f"方法2失敗: {e}")
    
    return False


def _start_obexd():
    """啟動 OBEX daemon"""
    global _OBEXD_PROC
    
    # 檢查是否已經在運行
    try:
        result = subprocess.run(["pgrep", "-x", "obexd"], capture_output=True)
        if result.returncode == 0:
            print("✓ obexd 已在運行")
            return True
    except Exception:
        pass
    
    # 找到 obexd 執行檔
    obexd_paths = [
        "/usr/libexec/bluetooth/obexd",
        "/usr/lib/bluetooth/obexd",
        "/usr/local/libexec/bluetooth/obexd",
    ]
    
    obexd_bin = None
    for path in obexd_paths:
        if os.path.exists(path):
            obexd_bin = path
            break
    
    if not obexd_bin:
        print("❌ 找不到 obexd 執行檔")
        print("請安裝: sudo apt install bluez-obexd")
        print(f"已檢查: {obexd_paths}")
        return False
    
    print(f"🚀 啟動 obexd: {obexd_bin}")
    
    # 確保環境變數正確
    env = os.environ.copy()
    if not env.get("DBUS_SESSION_BUS_ADDRESS"):
        print("❌ 沒有 DBUS_SESSION_BUS_ADDRESS")
        return False
    
    try:
        # 啟動 obexd（不使用 -n，讓它在背景運行）
        _OBEXD_PROC = subprocess.Popen(
            [obexd_bin, "-r", "/", "-a"],  # -a 自動接受所有連接
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE
        )
        
        # 等待它啟動
        time.sleep(2.0)
        
        # 檢查是否還在運行
        if _OBEXD_PROC.poll() is not None:
            stderr = _OBEXD_PROC.stderr.read().decode('utf-8', errors='ignore')
            print(f"❌ obexd 啟動後立即退出")
            if stderr:
                print(f"錯誤: {stderr}")
            return False
        
        print(f"✓ obexd 已啟動 (PID: {_OBEXD_PROC.pid})")
        return True
        
    except Exception as e:
        print(f"❌ 啟動 obexd 失敗: {e}")
        return False


def _cleanup():
    """清理函數"""
    global _OBEXD_PROC, _DBUS_DAEMON_PROC, _DBUS_DAEMON_PID
    
    # 停止 obexd
    if _OBEXD_PROC:
        try:
            if _OBEXD_PROC.poll() is None:
                _OBEXD_PROC.terminate()
                _OBEXD_PROC.wait(timeout=3)
                print("✓ obexd 已停止")
        except Exception as e:
            print(f"停止 obexd 時出錯: {e}")
    
    # 停止 dbus-daemon
    if _DBUS_DAEMON_PROC:
        try:
            if _DBUS_DAEMON_PROC.poll() is None:
                _DBUS_DAEMON_PROC.terminate()
                _DBUS_DAEMON_PROC.wait(timeout=3)
                print("✓ dbus-daemon 已停止")
        except Exception as e:
            print(f"停止 dbus-daemon 時出錯: {e}")
    
    if _DBUS_DAEMON_PID:
        try:
            subprocess.run(["kill", str(_DBUS_DAEMON_PID)], check=False)
        except Exception:
            pass


# 註冊清理函數
atexit.register(_cleanup)


def _verify_obex_service(bus, max_retries=5):
    """驗證 OBEX 服務是否可用"""
    for i in range(max_retries):
        try:
            obj = bus.get_object("org.bluez.obex", "/org/bluez/obex")
            obj.Introspect(dbus_interface="org.freedesktop.DBus.Introspectable")
            print(f"✅ OBEX 服務驗證成功")
            return True
        except dbus.exceptions.DBusException as e:
            if i < max_retries - 1:
                print(f"等待 OBEX 服務... ({i+1}/{max_retries})")
                time.sleep(1)
            else:
                print(f"❌ OBEX 服務驗證失敗: {e}")
                return False
    return False


def init_bluetooth_obex():
    """
    初始化藍牙 OBEX 環境
    
    Returns:
        dbus.Bus 或 None
    """
    print("=" * 60)
    print("初始化藍牙 OBEX 環境")
    print("=" * 60)
    
    # 步驟1: 創建 Session Bus
    if not _create_headless_session_bus():
        print("❌ 無法創建 Session Bus")
        return None
    
    # 步驟2: 啟動 obexd
    if not _start_obexd():
        print("❌ 無法啟動 obexd")
        return None
    
    # 步驟3: 連接到 Session Bus
    try:
        bus = dbus.SessionBus()
        print("✓ 已連接到 Session Bus")
    except Exception as e:
        print(f"❌ 連接 Session Bus 失敗: {e}")
        return None
    
    # 步驟4: 驗證 OBEX 服務
    if not _verify_obex_service(bus):
        print("❌ OBEX 服務不可用")
        return None
    
    print("=" * 60)
    print("✅ 藍牙 OBEX 環境初始化成功")
    print("=" * 60)
    return bus


# ==========================================
# 藍牙檔案傳送類別
# ==========================================
class ObexPushError(Exception):
    """OBEX 傳送錯誤"""
    pass


class BluetoothFileSender:
    """藍牙檔案傳送器"""
    
    def __init__(self):
        self.system_bus = dbus.SystemBus()
        self.session_bus = None
        
    def _ensure_obex_bus(self):
        """確保 OBEX bus 可用"""
        if self.session_bus is None:
            self.session_bus = init_bluetooth_obex()
            if self.session_bus is None:
                raise ObexPushError("無法初始化 OBEX 環境")
        return self.session_bus
        
    def get_paired_devices(self):
        """取得已配對的藍牙裝置"""
        try:
            manager = dbus.Interface(
                self.system_bus.get_object("org.bluez", "/"),
                "org.freedesktop.DBus.ObjectManager"
            )
            objects = manager.GetManagedObjects()
            
            devices = []
            for path, interfaces in objects.items():
                if "org.bluez.Device1" in interfaces:
                    props = interfaces["org.bluez.Device1"]
                    if props.get("Paired", False):
                        devices.append({
                            "path": path,
                            "mac": str(props.get("Address", "")),
                            "name": str(props.get("Name", "Unknown")),
                            "connected": bool(props.get("Connected", False))
                        })
            return devices
        except Exception as e:
            raise ObexPushError(f"無法取得配對裝置: {e}")
    
    def send_file(self, file_path: str, device_mac: str) -> bool:
        """傳送檔案"""
        try:
            bus = self._ensure_obex_bus()
            
            # OBEX Client
            client = dbus.Interface(
                bus.get_object("org.bluez.obex", "/org/bluez/obex"),
                "org.bluez.obex.Client1"
            )
            
            print(f"  建立連接到 {device_mac}...")
            session_path = client.CreateSession(
                device_mac,
                {"Target": "OPP"}
            )
            
            obj_push = dbus.Interface(
                bus.get_object("org.bluez.obex", session_path),
                "org.bluez.obex.ObjectPush1"
            )
            
            print(f"  正在傳送...")
            transfer_path, _ = obj_push.SendFile(file_path)
            
            # 監控傳輸狀態
            props = dbus.Interface(
                bus.get_object("org.bluez.obex", transfer_path),
                "org.freedesktop.DBus.Properties"
            )
            
            timeout = 60
            while timeout > 0:
                try:
                    status = str(props.Get("org.bluez.obex.Transfer1", "Status"))
                    transferred = props.Get("org.bluez.obex.Transfer1", "Transferred")
                    size = props.Get("org.bluez.obex.Transfer1", "Size")
                    
                    if status == "complete":
                        return True
                    if status == "error":
                        raise ObexPushError("傳送失敗")
                    
                    # 顯示進度
                    if size > 0:
                        progress = (transferred / size) * 100
                        print(f"  進度: {progress:.1f}%", end='\r')
                    
                    time.sleep(0.5)
                    timeout -= 0.5
                    
                except dbus.exceptions.DBusException as e:
                    if "does not exist" in str(e):
                        return True
                    raise
            
            raise ObexPushError("傳送逾時")
            
        except dbus.exceptions.DBusException as e:
            raise ObexPushError(f"D-Bus 錯誤: {e}")
    
    def auto_send_to_first_paired(self, files: list) -> tuple:
        """自動傳送到第一個配對裝置"""
        devices = self.get_paired_devices()
        
        if not devices:
            raise ObexPushError("沒有已配對的裝置")
        
        # 優先選擇已連線的
        target = None
        for dev in devices:
            if dev["connected"]:
                target = dev
                break
        
        if not target:
            target = devices[0]
        
        print(f"\n📱 目標裝置: {target['name']} ({target['mac']})")
        
        success_count = 0
        for file_path in files:
            if not os.path.exists(file_path):
                print(f"⚠️  檔案不存在: {file_path}")
                continue
            
            print(f"\n📤 傳送: {os.path.basename(file_path)}")
            try:
                self.send_file(file_path, target['mac'])
                print(f"✅ 完成")
                success_count += 1
                time.sleep(0.5)
            except ObexPushError as e:
                print(f"❌ 失敗: {e}")
        
        if success_count == 0:
            raise ObexPushError("所有檔案傳送都失敗")
        
        return target['mac'], target['name']


# ==========================================
# 測試代碼
# ==========================================
def test_bluetooth():
    """完整測試"""
    print("\n" + "=" * 60)
    print("藍牙檔案傳送測試")
    print("=" * 60 + "\n")
    
    try:
        sender = BluetoothFileSender()
        
        # 列出裝置
        print("📋 已配對裝置:")
        devices = sender.get_paired_devices()
        if not devices:
            print("❌ 沒有已配對的裝置")
            print("\n請先用藍牙配對一個裝置:")
            print("  bluetoothctl")
            print("  scan on")
            print("  pair XX:XX:XX:XX:XX:XX")
            return False
        
        for i, dev in enumerate(devices, 1):
            status = "🟢 已連線" if dev["connected"] else "⚪ 未連線"
            print(f"  {i}. {dev['name']} ({dev['mac']}) - {status}")
        
        # 創建測試檔案
        test_file = "/tmp/bluetooth_test.txt"
        with open(test_file, "w", encoding="utf-8") as f:
            f.write(f"藍牙傳送測試\n")
            f.write(f"時間: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"測試成功！\n")
        
        # 傳送
        mac, name = sender.auto_send_to_first_paired([test_file])
        print(f"\n🎉 測試成功！已傳送到 {name} ({mac})")
        return True
        
    except ObexPushError as e:
        print(f"\n❌ 藍牙錯誤: {e}")
        return False
    except Exception as e:
        print(f"\n❌ 未預期錯誤: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        # 清理
        print("\n正在清理...")
        _cleanup()


if __name__ == "__main__":
    if os.geteuid() != 0:
        print("⚠️  需要 root 權限")
        print("請使用: sudo python3 此檔案.py")
        exit(1)
    
    # 設置信號處理
    def signal_handler(sig, frame):
        print("\n\n收到中斷信號，正在清理...")
        _cleanup()
        exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    success = test_bluetooth()
    exit(0 if success else 1)