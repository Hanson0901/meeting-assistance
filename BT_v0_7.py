#!/usr/bin/env python3
import sys
import json
import os
import time
import threading
from pathlib import Path
from datetime import datetime
from gi.repository import GLib
import dbus
import dbus.service
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
AGENT_PATH = "/org/bluez/AutoAcceptAgent"


# ---------------- Auto-Accept Agent（自動接受所有配對） ---------------- #


class AutoAcceptAgent(dbus.service.Object):
    """自動接受配對的 Agent - 只顯示信息不需要輸入"""
    
    @dbus.service.method(AGENT_IFACE, in_signature="", out_signature="")
    def Release(self):
        print("\nℹ️ Agent released")

    @dbus.service.method(AGENT_IFACE, in_signature="o", out_signature="s")
    def RequestPinCode(self, device):
        pin = "0000"
        print(f"\n{'='*60}")
        print(f"🔐 Device {device} requests PIN code")
        print(f"✅ Auto-responding with PIN: {pin}")
        print("="*60)
        return pin

    @dbus.service.method(AGENT_IFACE, in_signature="os", out_signature="")
    def DisplayPinCode(self, device, pincode):
        print(f"\n{'='*60}")
        print(f"📱 Device {device}")
        print(f"🔐 PIN Code to enter on remote device: {pincode}")
        print("="*60)

    @dbus.service.method(AGENT_IFACE, in_signature="o", out_signature="u")
    def RequestPasskey(self, device):
        passkey = 0
        print(f"\n{'='*60}")
        print(f"🔐 Device {device} requests passkey")
        print(f"✅ Auto-responding with passkey: {passkey:06d}")
        print("="*60)
        return dbus.UInt32(passkey)

    @dbus.service.method(AGENT_IFACE, in_signature="ouq", out_signature="")
    def DisplayPasskey(self, device, passkey, entered):
        print(f"\n{'='*60}")
        print(f"📱 Device {device}")
        print(f"🔐 Passkey to enter on remote device: {passkey:06d}")
        print(f"   Progress: {entered} digits entered")
        print("="*60)

    @dbus.service.method(AGENT_IFACE, in_signature="ou", out_signature="")
    def RequestConfirmation(self, device, passkey):
        print(f"\n{'='*60}")
        print(f"🔐 Pairing confirmation for {device}")
        print(f"   Passkey: {passkey:06d}")
        print(f"✅ Auto-confirmed")
        print("="*60)

    @dbus.service.method(AGENT_IFACE, in_signature="os", out_signature="")
    def AuthorizeService(self, device, uuid):
        print(f"\n{'='*60}")
        print(f"🔐 Service authorization for {device}")
        print(f"   UUID: {uuid}")
        print(f"✅ Auto-authorized")
        print("="*60)

    @dbus.service.method(AGENT_IFACE, in_signature="", out_signature="")
    def Cancel(self):
        print("\n⚠️ Pairing canceled by remote device or BlueZ")


# ---------------- BlueZ Bonding / 掃描 / 連線管理 ---------------- #


class BlueZBondingManager:
    def __init__(self):
        self.bus = dbus.SystemBus()
        self.adapter = None
        self.adapter_props = None
        self.agent = None

    def get_adapter(self):
        try:
            adapter_path = "/org/bluez/hci0"
            adapter_obj = self.bus.get_object(BLUEZ_SERVICE, adapter_path)
            self.adapter = dbus.Interface(adapter_obj, ADAPTER_IFACE)
            self.adapter_props = dbus.Interface(adapter_obj, PROP_IFACE)
            
            # 確保藍牙已開啟
            powered = self.adapter_props.Get(ADAPTER_IFACE, "Powered")
            if not powered:
                print("⚡ Powering on Bluetooth adapter...")
                self.adapter_props.Set(ADAPTER_IFACE, "Powered", dbus.Boolean(True))
                time.sleep(1)
            
            return self.adapter
        except Exception as e:
            print(f"❌ Failed to get adapter hci0: {e}")
            print("💡 Try: sudo hciconfig hci0 up")
            return None

    def setup_agent(self):
        try:
            self.agent = AutoAcceptAgent(self.bus, AGENT_PATH)
            manager_obj = self.bus.get_object(BLUEZ_SERVICE, "/org/bluez")
            manager = dbus.Interface(manager_obj, AGENT_MGR_IFACE)
            manager.RegisterAgent(AGENT_PATH, "NoInputNoOutput")
            manager.RequestDefaultAgent(AGENT_PATH)
            
            print(f"✅ Agent registered at {AGENT_PATH}")
            print("ℹ️ Auto-accept mode: All pairing requests will be automatically accepted\n")
            return True
        except Exception as e:
            print(f"⚠️ Failed to setup agent: {e}")
            return False

    def get_managed_objects(self):
        try:
            obj_mgr_obj = self.bus.get_object(BLUEZ_SERVICE, "/")
            obj_mgr = dbus.Interface(obj_mgr_obj, OBJECT_MGR_IFACE)
            return obj_mgr.GetManagedObjects()
        except Exception as e:
            print(f"❌ GetManagedObjects failed: {e}")
            return {}

    def get_device_properties(self, path):
        """獲取單個設備的所有屬性"""
        try:
            dev_obj = self.bus.get_object(BLUEZ_SERVICE, path)
            dev_props = dbus.Interface(dev_obj, PROP_IFACE)
            return dev_props.GetAll(DEVICE_IFACE)
        except Exception as e:
            return None

    def scan_devices(self, timeout=8, show_all=False):
        """
        掃描設備 - 使用主動輪詢方式獲取 RSSI
        show_all=False: 只顯示有效 RSSI 的設備（實時在線）
        show_all=True: 顯示所有設備（包含緩存）
        """
        print(f"\n{'='*60}")
        print(f"🔍 Scanning BLE devices for {timeout} seconds...")
        print("="*60)

        # 啟動掃描
        try:
            self.adapter.StartDiscovery()
        except Exception as e:
            print(f"❌ Failed to start discovery: {e}")
            return []

        # 掃描期間持續輪詢設備
        device_rssi_map = {}  # MAC -> 最高 RSSI
        scan_iterations = int(timeout / 0.5)  # 每 0.5 秒輪詢一次
        
        for i in range(scan_iterations):
            time.sleep(0.5)
            
            # 獲取當前所有設備
            objects = self.get_managed_objects()
            for path, ifaces in objects.items():
                if DEVICE_IFACE not in ifaces:
                    continue
                
                # 主動獲取最新屬性（包括 RSSI）
                props = self.get_device_properties(path)
                if not props:
                    continue
                
                addr = str(props.get('Address', ''))
                rssi = int(props.get('RSSI', -127))
                
                # 保存最高的 RSSI 值
                if addr and rssi != -127:
                    if addr not in device_rssi_map or rssi > device_rssi_map[addr]['rssi']:
                        device_rssi_map[addr] = {
                            'path': path,
                            'rssi': rssi,
                            'name': str(props.get('Name', props.get('Alias', 'Unknown'))),
                            'paired': bool(props.get('Paired', False)),
                            'connected': bool(props.get('Connected', False)),
                            'trusted': bool(props.get('Trusted', False)),
                            'uuids': list(props.get('UUIDs', []))
                        }
            
            # 顯示進度
            if (i + 1) % 4 == 0:
                print(f"⏱️ Scanning... {len(device_rssi_map)} devices found with valid RSSI")

        # 停止掃描
        try:
            self.adapter.StopDiscovery()
        except:
            pass

        # 最後再掃描一次所有設備（包括沒有 RSSI 的）
        objects = self.get_managed_objects()
        devices = []
        
        for path, ifaces in objects.items():
            if DEVICE_IFACE not in ifaces:
                continue
            
            props = ifaces[DEVICE_IFACE]
            addr = str(props.get('Address', ''))
            name = str(props.get('Name', props.get('Alias', 'Unknown')))
            paired = bool(props.get('Paired', False))
            connected = bool(props.get('Connected', False))
            trusted = bool(props.get('Trusted', False))
            uuids = list(props.get('UUIDs', []))
            
            # 使用輪詢期間記錄的 RSSI
            if addr in device_rssi_map:
                rssi = device_rssi_map[addr]['rssi']
            else:
                rssi = int(props.get('RSSI', -127))
            
            # 根據 show_all 參數決定是否過濾
            if not show_all:
                if rssi == -127:
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
            rssi_str = f"{rssi:>4}" if rssi != -127 else " N/A"
            print(f"{bond_icon}{conn_icon} {name:<20} ({addr}) RSSI={rssi_str} dBm [Paired:{paired} Trusted:{trusted}]")

        print(f"\n✅ Found {len(devices)} BLE devices")
        
        if len(devices) == 0 and not show_all:
            print("💡 No devices with valid RSSI found. Make sure:")
            print("   - BLE devices are nearby and powered on")
            print("   - Devices are advertising (discoverable mode)")
            print("   - For phones: Open Bluetooth settings and stay on that page")
            print("   - Try: sudo hciconfig hci0 reset")
        
        return devices

    def is_bonded(self, mac):
        try:
            adapter_addr = self.adapter_props.Get(ADAPTER_IFACE, "Address")
            dev_dir = BONDING_KEYS_DIR / adapter_addr.replace(":", "") / mac.replace(":", "")
            return (dev_dir / "info").exists()
        except Exception:
            return False

    def get_bonding_info(self, mac):
        try:
            adapter_addr = self.adapter_props.Get(ADAPTER_IFACE, "Address")
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
            dev_obj = self.bus.get_object(BLUEZ_SERVICE, dev_path)
            dev = dbus.Interface(dev_obj, DEVICE_IFACE)
            dev_props = dbus.Interface(dev_obj, PROP_IFACE)
            
            if dev_props.Get(DEVICE_IFACE, "Paired"):
                print("✅ Already paired")
                return True

            if not self.agent:
                self.setup_agent()

            print("\n" + "="*60)
            print("🔐 Starting auto-pairing process...")
            print("ℹ️ Pairing will be automatically accepted")
            print("="*60)
            
            dev.Pair()

            timeout = 30
            while timeout > 0:
                time.sleep(1)
                try:
                    if dev_props.Get(DEVICE_IFACE, "Paired"):
                        break
                except:
                    pass
                timeout -= 1

            if dev_props.Get(DEVICE_IFACE, "Paired"):
                print("\n" + "="*60)
                print("✅ Pairing successful!")
                print("="*60)
                dev_props.Set(DEVICE_IFACE, "Trusted", dbus.Boolean(True))
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
        devs = self.manager.scan_devices(timeout=8, show_all=True)
        if not devs:
            print("⚠️ No devices found. Make sure BLE devices are nearby and advertising.")
            return
        
        print("\nSelect index to add (-1 cancel):")
        for i, d in enumerate(devs):
            rssi_str = f"{d['rssi']:>4}" if d['rssi'] != -127 else " N/A"
            print(f"{i:2d}: {d['name']:<20} ({d['mac']}) RSSI={rssi_str} dBm Bonded={d['bonded']}")

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
            do_pair = input("Not bonded, auto-pair now? [y/N]: ").strip().lower() == "y"
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
        print("💡 Only showing devices with valid RSSI (actively advertising)")
        try:
            while True:
                devs = self.manager.scan_devices(timeout=3, show_all=False)
                rssi_map = {d["mac"]: d["rssi"] for d in devs if d["rssi"] != -127}
                
                print(f"\n[{datetime.now().strftime('%H:%M:%S')}]")
                found_any = False
                for d in self.whitelist:
                    mac = d["mac"]
                    thr = d.get("rssi_threshold", NEAR_THRESHOLD)
                    rssi = rssi_map.get(mac)
                    
                    if rssi is None:
                        status = "🔴 LOST"
                        rssi_display = "N/A"
                    elif rssi > thr:
                        status = "🟢 NEAR"
                        rssi_display = str(rssi)
                        found_any = True
                    else:
                        status = "🔵 FAR"
                        rssi_display = str(rssi)
                        found_any = True
                    
                    print(f"{d['name']:<12} ({mac}): {status:<8} RSSI={rssi_display}")
                
                if not found_any:
                    print("⚠️ No whitelisted devices in range")
                
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
        print("   (Auto-Accept Mode)")
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
        print("⚠️ Warning: Running without root may have limited access to bonding keys")
        print("   Consider running with sudo for full functionality")
        print("="*70)
    
    if not Path("/var/run/dbus/system_bus_socket").exists():
        print("❌ D-Bus system socket not found. Is BlueZ running?")
        sys.exit(1)
    
    # 設置 D-Bus 主循環
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    
    # 啟動 GLib main loop 在背景執行緒
    loop_thread = threading.Thread(target=run_main_loop, daemon=True)
    loop_thread.start()
    
    print("="*70)
    print(" BlueZ D-Bus BLE Bonding Manager (Auto-Accept Mode)")
    print(f" Whitelist: {WHITELIST_FILE}")
    print(f" Bonding keys: {BONDING_KEYS_DIR}")
    print("="*70)
    
    # 執行主選單
    main_menu()
