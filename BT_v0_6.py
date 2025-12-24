#!/usr/bin/env python3
import sys
import json
import os
import time
import threading
from pathlib import Path
from datetime import datetime
from gi.repository import GLib
import pydbus
import dbus.mainloop.glib


# BlueZ D-Bus 介面定義
BLUEZ_SERVICE = 'org.bluez'
ADAPTER_IFACE = 'org.bluez.Adapter1'
DEVICE_IFACE = 'org.bluez.Device1'
AGENT_IFACE = 'org.bluez.Agent1'
AGENT_MGR_IFACE = 'org.bluez.AgentManager1'
PROP_IFACE = 'org.freedesktop.DBus.Properties'
OBJECT_MGR_IFACE = 'org.freedesktop.DBus.ObjectManager'


# 設定檔路徑
WHITELIST_FILE = "whitelist_dbus.json"
BONDING_KEYS_DIR = Path("/var/lib/bluetooth")
NEAR_THRESHOLD = -70  # dBm


# 全域鎖，用於同步終端輸入
terminal_lock = threading.Lock()


# ---------------- Agent 實作（處理 PIN / Passkey / Numeric Comparison） ---------------- #


class SimpleAgent:
    """實作 org.bluez.Agent1 介面，處理配對互動"""
    def __init__(self, bus, path="/test/agent", capability="KeyboardDisplay"):
        self.bus = bus
        self.path = path
        self.capability = capability
        # 註冊 Agent 物件
        bus.register_object(path, self._introspection_xml(), self)
        # 向 BlueZ 註冊
        mgr = self.bus.get(BLUEZ_SERVICE, "/org/bluez")[AGENT_MGR_IFACE]
        mgr.RegisterAgent(self.path, self.capability)
        mgr.RequestDefaultAgent(self.path)
        print(f"✅ Agent registered at {self.path} with capability={self.capability}")


    def _introspection_xml(self):
        return f"""
        <node>
          <interface name="{AGENT_IFACE}">
            <method name="Release"/>
            <method name="RequestPinCode"><arg name="device" direction="in" type="o"/><arg name="pincode" direction="out" type="s"/></method>
            <method name="DisplayPinCode"><arg name="device" direction="in" type="o"/><arg name="pincode" direction="in" type="s"/></method>
            <method name="RequestPasskey"><arg name="device" direction="in" type="o"/><arg name="passkey" direction="out" type="u"/></method>
            <method name="DisplayPasskey"><arg name="device" direction="in" type="o"/><arg name="passkey" direction="in" type="u"/><arg name="entered" direction="in" type="q"/></method>
            <method name="RequestConfirmation"><arg name="device" direction="in" type="o"/><arg name="passkey" direction="in" type="u"/></method>
            <method name="AuthorizeService"><arg name="device" direction="in" type="o"/><arg name="uuid" direction="in" type="s"/></method>
            <method name="Cancel"/>
          </interface>
        </node>
        """


    def Release(self):
        print("\nℹ️ Agent released")


    def RequestPinCode(self, device):
        with terminal_lock:
            print(f"\n{'='*60}")
            print(f"🔐 Device {device} requests PIN code")
            print("="*60)
            pin = input("Enter PIN code: ").strip()
            print(f"✅ PIN entered: {pin}")
            return pin


    def DisplayPinCode(self, device, pincode):
        with terminal_lock:
            print(f"\n{'='*60}")
            print(f"🔐 DisplayPinCode for {device}")
            print(f"   PIN: {pincode}")
            print("="*60)
            print("⚠️ Please enter this PIN on the remote device")


    def RequestPasskey(self, device):
        with terminal_lock:
            print(f"\n{'='*60}")
            print(f"🔐 Device {device} requests passkey")
            print("="*60)
            pk = input("Enter passkey (0-999999): ").strip()
            try:
                val = int(pk)
                print(f"✅ Passkey entered: {val:06d}")
                return val
            except ValueError:
                print("❌ Invalid passkey, using 0")
                return 0


    def DisplayPasskey(self, device, passkey, entered):
        with terminal_lock:
            print(f"\n{'='*60}")
            print(f"🔐 DisplayPasskey for {device}")
            print(f"   Passkey: {passkey:06d} (entered={entered})")
            print("="*60)


    def RequestConfirmation(self, device, passkey):
        with terminal_lock:
            print(f"\n{'='*60}")
            print(f"🔐 Confirm pairing with {device}")
            print(f"   Passkey: {passkey:06d}")
            print("="*60)
            resp = input("Confirm? (yes/no): ").strip().lower()
            if resp != "yes":
                print("❌ Pairing rejected")
                raise Exception("Pairing rejected by user")
            print("✅ Pairing confirmed")


    def AuthorizeService(self, device, uuid):
        with terminal_lock:
            print(f"\n{'='*60}")
            print(f"🔐 Authorize service for {device}")
            print(f"   UUID: {uuid}")
            print("="*60)
            resp = input("Authorize? (yes/no): ").strip().lower()
            result = resp == "yes"
            print(f"{'✅' if result else '❌'} Authorization {'granted' if result else 'denied'}")
            return result


    def Cancel(self):
        print("\n⚠️ Pairing canceled by remote device or BlueZ")


# ---------------- BlueZ Bonding / 掃描 / 連線管理 ---------------- #


class BlueZBondingManager:
    def __init__(self):
        self.bus = pydbus.SystemBus()
        self.adapter = None
        self.agent = None


    def get_adapter(self):
        try:
            adapter_path = "/org/bluez/hci0"
            self.adapter = self.bus.get(BLUEZ_SERVICE, adapter_path)[ADAPTER_IFACE]
            return self.adapter
        except Exception as e:
            print(f"❌ Failed to get adapter hci0: {e}")
            return None


    def setup_agent(self):
        try:
            self.agent = SimpleAgent(self.bus, "/test/agent", capability="KeyboardDisplay")
            return True
        except Exception as e:
            print(f"⚠️ Failed to setup agent: {e}")
            return False


    def get_managed_objects(self):
        try:
            obj_mgr = self.bus.get(BLUEZ_SERVICE, "/")[OBJECT_MGR_IFACE]
            return obj_mgr.GetManagedObjects()
        except Exception as e:
            print(f"❌ GetManagedObjects failed: {e}")
            return {}


    def scan_devices(self, timeout=8):
        print(f"\n{'='*60}")
        print(f"🔍 Scanning BLE devices for {timeout} seconds...")
        print("="*60)

        try:
            self.adapter.StartDiscovery()
            time.sleep(timeout)
            self.adapter.StopDiscovery()
        except Exception as e:
            print(f"❌ Discovery error: {e}")
            return []

        objects = self.get_managed_objects()
        devices = []

        for path, ifaces in objects.items():
            if DEVICE_IFACE not in ifaces:
                continue
            props = ifaces[DEVICE_IFACE]
            addr = props.get("Address", "")
            name = props.get("Alias", props.get("Name", "Unknown"))
            rssi = props.get("RSSI", -127)
            paired = props.get("Paired", False)
            connected = props.get("Connected", False)
            trusted = props.get("Trusted", False)
            uuids = props.get("UUIDs", [])

            if not uuids or rssi == -127:
                continue

            bonded = self.is_bonded(addr)
            devices.append(
                {
                    "path": path,
                    "mac": addr,
                    "name": name,
                    "rssi": rssi,
                    "paired": paired,
                    "bonded": bonded,
                    "connected": connected,
                    "trusted": trusted,
                    "uuids": uuids,
                }
            )

            bond_icon = "🔒" if bonded else "🔓"
            conn_icon = "🔗" if connected else "⛓️"
            print(f"{bond_icon}{conn_icon} {name:<20} ({addr}) RSSI={rssi:>4} dBm [Paired:{paired} Trusted:{trusted}]")

        print(f"\n✅ Found {len(devices)} BLE devices")
        return devices


    def is_bonded(self, mac):
        try:
            adapter_addr = self.adapter.Address
            dev_dir = BONDING_KEYS_DIR / adapter_addr.replace(":", "") / mac.replace(":", "")
            return (dev_dir / "info").exists()
        except Exception:
            return False


    def get_bonding_info(self, mac):
        try:
            adapter_addr = self.adapter.Address
            dev_dir = BONDING_KEYS_DIR / adapter_addr.replace(":", "") / mac.replace(":", "")
            info_file = dev_dir / "info"
            if not info_file.exists():
                return None

            info = {}
            section = None
            with info_file.open() as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith("[") and line.endswith("]"):
                        section = line[1:-1]
                        info[section] = {}
                    elif "=" in line and section:
                        k, v = line.split("=", 1)
                        info[section][k.strip()] = v.strip()
            return info
        except Exception as e:
            print(f"❌ read bonding info error: {e}")
            return None


    def pair_device(self, dev_path):
        try:
            dev = self.bus.get(BLUEZ_SERVICE, dev_path)[DEVICE_IFACE]
            if dev.Paired:
                print("✅ Already paired")
                return True

            if not self.agent:
                self.setup_agent()

            print("\n" + "="*60)
            print("🔐 Starting pairing process...")
            print("⚠️ Watch this terminal for PIN/Passkey confirmation")
            print("="*60)
            
            dev.Pair()

            # 等待配對完成
            timeout = 30
            while timeout > 0 and not dev.Paired:
                time.sleep(1)
                timeout -= 1

            if dev.Paired:
                print("\n" + "="*60)
                print("✅ Pairing successful!")
                print("="*60)
                dev.Trusted = True
                print("✅ Device set as trusted")
                time.sleep(1)
                return True
            else:
                print("\n" + "="*60)
                print("❌ Pairing timeout")
                print("="*60)
                return False

        except Exception as e:
            print(f"\n❌ Pairing failed: {e}")
            return False


    def remove_device(self, dev_path):
        try:
            self.adapter.RemoveDevice(dev_path)
            print("🗑️ Device removed (bond + cache)")
            return True
        except Exception as e:
            print(f"❌ RemoveDevice failed: {e}")
            return False


# ---------------- 應用層：白名單 + 接近偵測 ---------------- #


class BLEProximityApp:
    def __init__(self):
        self.manager = BlueZBondingManager()
        if not self.manager.get_adapter():
            print("❌ No Bluetooth adapter hci0")
            sys.exit(1)
        self.manager.setup_agent()
        self.whitelist = self.load_whitelist()


    def load_whitelist(self):
        if not os.path.exists(WHITELIST_FILE):
            return []
        try:
            with open(WHITELIST_FILE) as f:
                data = json.load(f)
            return data.get("devices", [])
        except Exception as e:
            print(f"❌ load whitelist error: {e}")
            return []


    def save_whitelist(self):
        try:
            with open(WHITELIST_FILE, "w") as f:
                json.dump(
                    {
                        "devices": self.whitelist,
                        "last_updated": datetime.now().isoformat(),
                        "note": "Bonding keys in /var/lib/bluetooth",
                    },
                    f,
                    indent=2,
                )
            print(f"✅ Whitelist saved -> {WHITELIST_FILE}")
        except Exception as e:
            print(f"❌ save whitelist error: {e}")


    def show_whitelist(self):
        if not self.whitelist:
            print("📋 Whitelist empty")
            return
        print(f"\n📋 Whitelist ({len(self.whitelist)}):")
        print(f"{'Idx':<4} {'Name':<15} {'MAC':<18} {'Bonded':<8} {'RSSI Thr.':<10}")
        print("-" * 60)
        for i, d in enumerate(self.whitelist):
            bonded = "✓" if self.manager.is_bonded(d["mac"]) else "✗"
            thr = d.get("rssi_threshold", NEAR_THRESHOLD)
            print(f"{i:<4} {d['name']:<15} {d['mac']:<18} {bonded:<8} {thr:<10}")


    def add_from_scan(self):
        devs = self.manager.scan_devices(timeout=8)
        if not devs:
            return
        print("\nSelect index to add (-1 cancel):")
        for i, d in enumerate(devs):
            print(f"{i:2d}: {d['name']:<20} ({d['mac']}) RSSI={d['rssi']:>4} dBm Bonded={d['bonded']}")

        try:
            idx = int(input("Index: ").strip())
        except ValueError:
            print("❌ invalid input")
            return
        if idx < 0 or idx >= len(devs):
            print("⏹️ canceled")
            return

        d = devs[idx]
        if any(x["mac"].lower() == d["mac"].lower() for x in self.whitelist):
            print("⚠️ already in whitelist")
            return

        if not d["bonded"]:
            do_pair = input("Not bonded, pair now? [y/N]: ").strip().lower() == "y"
            if do_pair:
                if not self.manager.pair_device(d["path"]):
                    print("❌ pairing failed, not added")
                    return

        alias = input(f"Alias (default={d['name']}): ").strip() or d["name"]
        thr_s = input(f"RSSI threshold (default={NEAR_THRESHOLD}): ").strip()
        try:
            thr = int(thr_s) if thr_s else NEAR_THRESHOLD
        except ValueError:
            thr = NEAR_THRESHOLD

        self.whitelist.append(
            {
                "name": alias,
                "mac": d["mac"],
                "rssi_threshold": thr,
                "added_at": datetime.now().isoformat(),
            }
        )
        self.save_whitelist()


    def remove_device(self):
        if not self.whitelist:
            print("📋 Whitelist empty")
            return
        self.show_whitelist()
        try:
            idx = int(input("Index to remove (-1 cancel): ").strip())
        except ValueError:
            print("❌ invalid input")
            return
        if idx < 0 or idx >= len(self.whitelist):
            print("⏹️ canceled")
            return

        dev = self.whitelist[idx]
        objs = self.manager.get_managed_objects()
        for path, ifaces in objs.items():
            if DEVICE_IFACE in ifaces and ifaces[DEVICE_IFACE].get("Address") == dev["mac"]:
                self.manager.remove_device(path)
                break
        self.whitelist.pop(idx)
        self.save_whitelist()


    def show_bonding_info(self):
        if not self.whitelist:
            print("📋 Whitelist empty")
            return
        self.show_whitelist()
        try:
            idx = int(input("Index to show bonding (-1 cancel): ").strip())
        except ValueError:
            print("❌ invalid")
            return
        if idx < 0 or idx >= len(self.whitelist):
            print("⏹️ canceled")
            return
        dev = self.whitelist[idx]
        info = self.manager.get_bonding_info(dev["mac"])
        if not info:
            print("❌ no bonding info")
            return
        print(f"\n🔐 Bonding info for {dev['name']} ({dev['mac']}):")
        for sec, kv in info.items():
            print(f"[{sec}]")
            for k, v in kv.items():
                if "Key" in k and len(v) > 32:
                    v = v[:32] + "..."
                print(f"  {k:<20}= {v}")
            print()


    def monitor(self):
        if not self.whitelist:
            print("📋 Whitelist empty")
            return
        print("\n=== Proximity monitor (Ctrl+C to stop) ===")
        try:
            while True:
                devs = self.manager.scan_devices(timeout=3)
                rssi_map = {d["mac"]: d["rssi"] for d in devs}
                print(f"\n[{datetime.now().strftime('%H:%M:%S')}]")
                for d in self.whitelist:
                    mac = d["mac"]
                    thr = d.get("rssi_threshold", NEAR_THRESHOLD)
                    rssi = rssi_map.get(mac)
                    if rssi is None:
                        status = "🔴 LOST"
                    elif rssi > thr:
                        status = "🟢 NEAR"
                    else:
                        status = "🔵 FAR"
                    print(f"{d['name']:<12} ({mac}): {status:<8} RSSI={rssi or 'N/A'}")
                time.sleep(2)
        except KeyboardInterrupt:
            print("\n⏹️ monitor stopped")


# ---------------- 主程式 ---------------- #


def run_main_loop():
    """在背景執行緒中執行 GLib main loop"""
    loop = GLib.MainLoop()
    loop.run()


def main_menu():
    """主選單"""
    app = BLEProximityApp()
    while True:
        print("\n" + "=" * 60)
        print("   🔷 BlueZ D-Bus BLE Bonding + Proximity Tool")
        print("=" * 60)
        print("1. 📡 Scan & add device")
        print("2. 📋 Show whitelist")
        print("3. 🔐 Show bonding info")
        print("4. 🗑️ Remove device")
        print("5. ▶️ Start proximity monitor")
        print("0. ❌ Exit")
        print("=" * 60)
        choice = input("Select: ").strip()
        if choice == "1":
            app.add_from_scan()
        elif choice == "2":
            app.show_whitelist()
        elif choice == "3":
            app.show_bonding_info()
        elif choice == "4":
            app.remove_device()
        elif choice == "5":
            app.monitor()
        elif choice == "0":
            break
        else:
            print("❌ Invalid choice")


if __name__ == "__main__":
    if os.geteuid() != 0:
        print("  Warning: Running without root may have limited access to bonding keys")
        print("   Consider running with sudo for full functionality")
        print("="*70)
    
    if not Path("/var/run/dbus/system_bus_socket").exists():
        print(" D-Bus system socket not found. Is BlueZ running?")
        sys.exit(1)
    
    try:
        import pydbus
        from gi.repository import GLib
    except ImportError as e:
        print(f" Import error: {e}")
        print("Install dependencies: pip install pydbus PyGObject")
        sys.exit(1)
    
    # 設置 D-Bus 主循環
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    
    # 啟動 GLib main loop 在背景執行緒
    loop_thread = threading.Thread(target=run_main_loop, daemon=True)
    loop_thread.start()
    
    print(" BlueZ D-Bus BLE Bonding Manager")
    print(f" Whitelist: {WHITELIST_FILE}")
    print(f" Bonding keys: {BONDING_KEYS_DIR}")
    print("="*70)
    
    # 執行主選單
    main_menu()
