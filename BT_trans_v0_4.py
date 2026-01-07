#!/usr/bin/env python3
import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib
import os

# 目標目錄
DEST_DIR = os.path.abspath(os.path.expanduser("~/bluetooth_received"))
if not os.path.exists(DEST_DIR):
    os.makedirs(DEST_DIR)

class Agent(dbus.service.Object):
    def __init__(self, bus, path):
        super().__init__(bus, path)
        print(f"Agent 準備就緒，儲存至: {DEST_DIR}")

    @dbus.service.method("org.bluez.obex.Agent1", in_signature="o", out_signature="s")
    def AuthorizePush(self, path):
        print(f"收到請求: {path}")
        # 直接回傳目錄路徑，讓 obexd 決定檔名
        # 注意：某些手機可能需要完整的檔名路徑，但先試試看目錄
        return DEST_DIR

    @dbus.service.method("org.bluez.obex.Agent1")
    def Cancel(self):
        print("已取消")

    @dbus.service.method("org.bluez.obex.Agent1")
    def Release(self):
        print("Agent 釋放")

def main():
    # 確保 obexd 運行
    os.system("systemctl --user start obex")
    
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SessionBus()
    agent = Agent(bus, "/com/test/agent")
    
    try:
        obj = bus.get_object("org.bluez.obex", "/org/bluez/obex")
        manager = dbus.Interface(obj, "org.bluez.obex.AgentManager1")
        manager.RegisterAgent("/com/test/agent")
        print("Agent 已註冊")
        
        loop = GLib.MainLoop()
        loop.run()
    except Exception as e:
        print(f"錯誤: {e}")

if __name__ == '__main__':
    main()
