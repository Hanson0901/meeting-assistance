#!/usr/bin/env python3
#此為傳送檔案的版本

import dbus
import time
from gi.repository import GLib
from dbus.mainloop.glib import DBusGMainLoop

# D-Bus 服務與介面常數
OBEX_SERVICE = "org.bluez.obex"
OBEX_CLIENT_INTERFACE = "org.bluez.obex.Client1"
OBEX_SESSION_INTERFACE = "org.bluez.obex.Session1"
OBEX_TRANSFER_INTERFACE = "org.bluez.obex.Transfer1"

class BluetoothFileTransfer:
    def __init__(self):
        """初始化藍芽文件傳輸客戶端"""
        DBusGMainLoop(set_as_default=True)
        self.session_bus = dbus.SessionBus()
        self.client = None
        self.session_path = None
        
    def get_obex_client(self):
        """取得 OBEX 客戶端介面"""
        try:
            obj = self.session_bus.get_object(OBEX_SERVICE, "/org/bluez/obex")
            self.client = dbus.Interface(obj, OBEX_CLIENT_INTERFACE)
            return self.client
        except dbus.DBusException as e:
            print(f"無法連接到 OBEX 服務: {e}")
            print("請確認 obexd 服務已啟動: systemctl --user start obex")
            return None
    
    def create_session(self, device_address, target="OPP"):
        """
        建立 OBEX 會話
        
        Args:
            device_address: 目標裝置的藍芽 MAC 地址 (格式: XX:XX:XX:XX:XX:XX)
            target: 傳輸類型 ("OPP" = Object Push Profile, "FTP" = File Transfer Profile)
        """
        if not self.client:
            self.get_obex_client()
        
        try:
            args = {"Target": dbus.String(target)}
            self.session_path = self.client.CreateSession(device_address, args)
            print(f"會話已建立: {self.session_path}")
            return self.session_path
        except dbus.DBusException as e:
            print(f"建立會話失敗: {e}")
            return None
    
    def send_file(self, file_path):
        """
        傳送檔案
        
        Args:
            file_path: 要傳送的檔案完整路徑
        """
        if not self.session_path:
            print("錯誤: 尚未建立會話")
            return False
        
        try:
            session_obj = self.session_bus.get_object(OBEX_SERVICE, self.session_path)
            session = dbus.Interface(session_obj, "org.bluez.obex.ObjectPush1")
            
            # 傳送檔案並取得傳輸物件路徑和屬性
            transfer_path, properties = session.SendFile(file_path)
            print(f"開始傳輸: {file_path}")
            print(f"傳輸物件: {transfer_path}")
            
            # 監控傳輸狀態
            self.monitor_transfer(transfer_path)
            return True
            
        except dbus.DBusException as e:
            print(f"傳送檔案失敗: {e}")
            return False
    
    def monitor_transfer(self, transfer_path):
        """監控文件傳輸狀態"""
        transfer_obj = self.session_bus.get_object(OBEX_SERVICE, transfer_path)
        props = dbus.Interface(transfer_obj, "org.freedesktop.DBus.Properties")
        
        print("監控傳輸進度...")
        while True:
            try:
                status = props.Get(OBEX_TRANSFER_INTERFACE, "Status")
                transferred = props.Get(OBEX_TRANSFER_INTERFACE, "Transferred")
                size = props.Get(OBEX_TRANSFER_INTERFACE, "Size")
                
                if size > 0:
                    progress = (transferred / size) * 100
                    print(f"狀態: {status} | 進度: {progress:.1f}% ({transferred}/{size} bytes)")
                
                if status == "complete":
                    print("✓ 傳輸完成!")
                    break
                elif status == "error":
                    print("✗ 傳輸失敗!")
                    break
                    
                time.sleep(0.5)
            except dbus.DBusException:
                break
    
    def remove_session(self):
        """移除 OBEX 會話"""
        if self.session_path and self.client:
            try:
                self.client.RemoveSession(self.session_path)
                print("會話已移除")
            except dbus.DBusException as e:
                print(f"移除會話失敗: {e}")

def main():
    """主程式範例"""
    # 使用範例
    target_device = "C8:16:DA:A0:5C:C2"  # 替換為目標裝置的藍芽 MAC 地址
    file_to_send = "/home/cgu-csie/meeting-assistence/meeting_record/project_test_1.csv"  # 替換為要傳送的檔案路徑
    
    transfer = BluetoothFileTransfer()
    
    # 取得 OBEX 客戶端
    if not transfer.get_obex_client():
        return
    
    # 建立會話
    if not transfer.create_session(target_device):
        return
    
    # 傳送檔案
    transfer.send_file(file_to_send)
    
    # 清理會話
    transfer.remove_session()

if __name__ == "__main__":
    main()
