#!/usr/bin/env python3
"""
藍芽檔案接收 Agent - 修正版
從 Android 手機接收檔案到 Raspberry Pi
"""
import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib
import os
import sys

# 設定檔案儲存路徑
SAVE_PATH = os.path.expanduser("/home/cgu-csie/meeting-assistence/bluetooth_received")

class BluetoothOBEXAgent(dbus.service.Object):
    """OBEX Agent 用於授權接收檔案"""
    
    def __init__(self, bus, path):
        super().__init__(bus, path)
        # 確保儲存目錄存在
        if not os.path.exists(SAVE_PATH):
            os.makedirs(SAVE_PATH)
            print(f"已創建目錄: {SAVE_PATH}")
        print(f"📁 檔案將儲存到: {SAVE_PATH}")
        print("等待傳輸...")

    @dbus.service.method("org.bluez.obex.Agent1", 
                         in_signature="o", out_signature="s")
    def AuthorizePush(self, transfer_path):
        """
        授權檔案推送請求
        transfer_path: 傳輸物件的 D-Bus 路徑
        回傳: 完整的檔案儲存路徑
        """
        print(f"\n📥 收到傳輸請求: {transfer_path}")
        
        try:
            # 取得傳輸物件的屬性
            transfer = dbus.Interface(
                self.connection.get_object("org.bluez.obex", transfer_path),
                "org.freedesktop.DBus.Properties"
            )
            
            # 獲取檔案資訊
            filename = str(transfer.Get("org.bluez.obex.Transfer1", "Name"))
            size = int(transfer.Get("org.bluez.obex.Transfer1", "Size"))
            
            print(f"📄 檔案名稱: {filename}")
            print(f"📊 檔案大小: {size} bytes ({size/1024:.2f} KB)")
            
            # 構建完整路徑
            full_path = os.path.join(SAVE_PATH, filename)
            
            # 如果檔案已存在，自動重命名
            if os.path.exists(full_path):
                base, ext = os.path.splitext(filename)
                counter = 1
                while os.path.exists(full_path):
                    new_filename = f"{base}_{counter}{ext}"
                    full_path = os.path.join(SAVE_PATH, new_filename)
                    counter += 1
                print(f"⚠️  檔案已存在，重命名為: {os.path.basename(full_path)}")
            
            print(f"✅ 授權接收，儲存到: {full_path}")
            return full_path
            
        except Exception as e:
            print(f"❌ 錯誤: {e}")
            # 即使出錯也回傳預設路徑
            return os.path.join(SAVE_PATH, "received_file")

    @dbus.service.method("org.bluez.obex.Agent1")
    def Cancel(self):
        """傳輸取消"""
        print("❌ 傳輸已取消")

    @dbus.service.method("org.bluez.obex.Agent1")
    def Release(self):
        """Agent 釋放"""
        print("🔓 Agent 已釋放")

def ensure_obexd_running():
    """確保 obexd 服務正在運行"""
    import subprocess
    
    # 檢查是否已運行
    result = subprocess.run(['pgrep', '-x', 'obexd'], 
                           capture_output=True, text=True)
    if result.returncode == 0:
        print("✓ obexd 已在運行")
        return True
    
    # 嘗試啟動
    print("正在啟動 obexd...")
    obexd_paths = [
        '/usr/lib/bluetooth/obexd',
        '/usr/libexec/bluetooth/obexd',
        '/usr/local/lib/bluetooth/obexd'
    ]
    
    for path in obexd_paths:
        if os.path.exists(path):
            try:
                subprocess.Popen([path], 
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
                import time
                time.sleep(1)
                print(f"✓ obexd 已從 {path} 啟動")
                return True
            except Exception as e:
                print(f"✗ 從 {path} 啟動失敗: {e}")
    
    print("⚠️  警告: 無法啟動 obexd，請手動執行:")
    print("   /usr/lib/bluetooth/obexd &")
    return False

def register_agent(bus):
    """註冊 OBEX Agent 到 BlueZ"""
    agent_path = "/org/bluez/obex_agent"
    
    # 創建 Agent 物件
    agent = BluetoothOBEXAgent(bus, agent_path)
    
    try:
        # 取得 AgentManager
        manager_obj = bus.get_object("org.bluez.obex", "/org/bluez/obex")
        manager = dbus.Interface(manager_obj, "org.bluez.obex.AgentManager1")
        
        # 註冊 Agent
        manager.RegisterAgent(agent_path)
        print(f"✓ Agent 已註冊: {agent_path}")
        print("\n" + "="*50)
        print("🎉 接收服務已啟動！")
        print("="*50)
        print("現在可以從 Android 手機傳送檔案了。")
        print("按 Ctrl+C 停止服務。")
        print("="*50 + "\n")
        
        return agent
        
    except dbus.exceptions.DBusException as e:
        print(f"❌ 註冊 Agent 失敗: {e}")
        print("\n可能的原因:")
        print("1. obexd 未運行")
        print("2. Agent 已被其他程式註冊")
        print("3. D-Bus 權限問題")
        sys.exit(1)

def main():
    """主程式"""
    print("="*50)
    print("藍芽檔案接收服務")
    print("="*50)
    
    # 確保 obexd 運行
    ensure_obexd_running()
    
    # 設定 D-Bus 主循環
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    
    # 連接到 Session Bus
    bus = dbus.SessionBus()
    
    # 註冊 Agent
    agent = register_agent(bus)
    
    # 啟動主循環
    loop = GLib.MainLoop()
    
    try:
        loop.run()
    except KeyboardInterrupt:
        print("\n\n👋 停止接收服務...")

if __name__ == '__main__':
    main()
