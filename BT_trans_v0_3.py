#!/usr/bin/env python3
"""
藍芽檔案接收 Agent - 簡化除錯版
"""
import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib
import os
import sys

# 使用家目錄的絕對路徑
SAVE_PATH = os.path.join(os.path.expanduser("~"), "bluetooth_received")

class BluetoothOBEXAgent(dbus.service.Object):
    
    def __init__(self, bus, path):
        super().__init__(bus, path)
        
        # 確保目錄存在並設定權限
        os.makedirs(SAVE_PATH, mode=0o755, exist_ok=True)
        
        print(f"=" * 60)
        print(f"儲存路徑: {SAVE_PATH}")
        print(f"絕對路徑: {os.path.abspath(SAVE_PATH)}")
        print(f"目錄權限: {oct(os.stat(SAVE_PATH).st_mode)[-3:]}")
        print(f"=" * 60)
        print("等待傳輸...\n")

    @dbus.service.method("org.bluez.obex.Agent1", 
                         in_signature="o", out_signature="s")
    def AuthorizePush(self, transfer_path):
        """授權檔案推送"""
        print(f"\n{'='*60}")
        print(f"📥 收到傳輸請求")
        print(f"傳輸路徑: {transfer_path}")
        
        try:
            # 取得傳輸物件
            obj = self.connection.get_object("org.bluez.obex", transfer_path)
            props = dbus.Interface(obj, "org.freedesktop.DBus.Properties")
            
            # 獲取檔案資訊
            filename = str(props.Get("org.bluez.obex.Transfer1", "Name"))
            size = int(props.Get("org.bluez.obex.Transfer1", "Size"))
            
            print(f"檔案名稱: {filename}")
            print(f"檔案大小: {size} bytes")
            
            # 構建完整路徑（確保使用絕對路徑）
            full_path = os.path.join(SAVE_PATH, filename)
            full_path = os.path.abspath(full_path)
            
            # 檢查路徑安全性
            if not full_path.startswith(os.path.abspath(SAVE_PATH)):
                print(f"❌ 安全性錯誤: 非法路徑")
                return ""
            
            # 處理重複檔名
            if os.path.exists(full_path):
                base, ext = os.path.splitext(filename)
                counter = 1
                while os.path.exists(full_path):
                    new_name = f"{base}_{counter}{ext}"
                    full_path = os.path.abspath(os.path.join(SAVE_PATH, new_name))
                    counter += 1
                print(f"重命名為: {os.path.basename(full_path)}")
            
            # 驗證父目錄可寫
            if not os.access(SAVE_PATH, os.W_OK):
                print(f"❌ 錯誤: 目錄不可寫")
                print(f"   執行: chmod 755 {SAVE_PATH}")
                return ""
            
            print(f"✅ 授權接收")
            print(f"完整路徑: {full_path}")
            print(f"{'='*60}\n")
            
            # 必須返回完整的絕對路徑
            return dbus.String(full_path)
            
        except Exception as e:
            print(f"❌ 異常: {e}")
            import traceback
            traceback.print_exc()
            return ""

    @dbus.service.method("org.bluez.obex.Agent1")
    def Cancel(self):
        print("❌ 傳輸已取消\n")

    @dbus.service.method("org.bluez.obex.Agent1")
    def Release(self):
        print("🔓 Agent 已釋放\n")

def cleanup_and_start_obexd():
    """清理並重新啟動 obexd"""
    import subprocess
    
    print("清理舊的 obexd 程序...")
    subprocess.run(['pkill', '-9', 'obexd'], capture_output=True)
    
    import time
    time.sleep(1)
    
    # 嘗試不同路徑
    obexd_paths = [
        '/usr/lib/bluetooth/obexd',
        '/usr/libexec/bluetooth/obexd',
        '/usr/local/libexec/bluetooth/obexd'
    ]
    
    for path in obexd_paths:
        if os.path.exists(path):
            print(f"嘗試啟動: {path}")
            try:
                # 不使用 -d (除錯模式可能導致問題)
                proc = subprocess.Popen([path], 
                                       stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE)
                time.sleep(2)
                
                # 驗證是否啟動
                result = subprocess.run(['pgrep', '-x', 'obexd'], 
                                       capture_output=True)
                if result.returncode == 0:
                    print(f"✓ obexd 已啟動 (PID: {result.stdout.decode().strip()})")
                    return True
            except Exception as e:
                print(f"✗ 啟動失敗: {e}")
    
    print("❌ 無法啟動 obexd")
    return False

def main():
    print("\n" + "="*60)
    print("藍芽檔案接收服務 - 除錯版")
    print("="*60 + "\n")
    
    # 確保目錄存在
    os.makedirs(SAVE_PATH, mode=0o755, exist_ok=True)
    
    # 重新啟動 obexd
    if not cleanup_and_start_obexd():
        print("\n請手動啟動 obexd:")
        print("  /usr/lib/bluetooth/obexd &")
        print("\n或安裝 obexd:")
        print("  sudo apt-get install bluez")
        sys.exit(1)
    
    # 設定 D-Bus
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SessionBus()
    
    # 註冊 Agent
    agent_path = "/org/bluez/obex_agent"
    agent = BluetoothOBEXAgent(bus, agent_path)
    
    try:
        manager = dbus.Interface(
            bus.get_object("org.bluez.obex", "/org/bluez/obex"),
            "org.bluez.obex.AgentManager1"
        )
        
        # 嘗試取消註冊舊的 agent
        try:
            manager.UnregisterAgent(agent_path)
        except:
            pass
        
        import time
        time.sleep(0.5)
        
        # 註冊新 agent
        manager.RegisterAgent(agent_path)
        print("✓ Agent 已註冊\n")
        
    except Exception as e:
        print(f"❌ 註冊失敗: {e}")
        sys.exit(1)
    
    print("🎉 服務已啟動，等待連接...")
    print("從手機傳送檔案進行測試\n")
    
    # 啟動主循環
    loop = GLib.MainLoop()
    try:
        loop.run()
    except KeyboardInterrupt:
        print("\n\n停止服務...")

if __name__ == '__main__':
    main()
