#!/usr/bin/env python3
import sys
import json
import os
import time
import threading
import subprocess
import re
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


    def is_discovering(self):
        """檢查是否正在掃描"""
        try:
            return bool(self.adapter_props.Get(ADAPTER_IFACE, "Discovering"))
        except Exception as e:
            return False


    def ensure_discovery_stopped(self):
        """確保掃描已停止"""
        try:
            if self.is_discovering():
                self.adapter.StopDiscovery()
                time.sleep(0.5)
                
                retry = 3
                while retry > 0 and self.is_discovering():
                    time.sleep(0.3)
                    retry -= 1
        except dbus.exceptions.DBusException as e:
            if "org.bluez.Error.NotReady" not in str(e) and "org.bluez.Error.Failed" not in str(e):
                pass
        except Exception:
            pass


    def scan_classic_devices(self, timeout=10):
        """
        掃描 Bluetooth Classic 設備並獲取 RSSI
        這對 Android 手機更有效，因為 Classic 不會自動關閉
        """
        print(f"\n{'='*60}")
        print(f"📻 Scanning Bluetooth Classic devices for {timeout} seconds...")
        print("="*60)
        
        devices = {}
        
        try:
            # 檢查 hcitool 是否可用
            check = subprocess.run(
                ["which", "hcitool"],
                capture_output=True,
                text=True
            )
            if check.returncode != 0:
                print("❌ hcitool not found. Install: sudo apt install bluez")
                return []
            
            # 使用 hcitool 進行 inquiry 掃描
            print("📡 Starting Bluetooth Classic inquiry (this may take a while)...")
            cmd = ["hcitool", "inq"]
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True
            )
            
            # 設定超時
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
            
            if stderr and "Device not available" in stderr:
                print("❌ Bluetooth adapter not available for Classic scan")
                return []
            
            # 解析結果
            # 格式: \tXX:XX:XX:XX:XX:XX\tclock offset: 0x####\tclass: 0x######
            for line in stdout.splitlines():
                match = re.search(r'([0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2})', line)
                if match:
                    addr = match.group(1).upper()
                    devices[addr] = {"mac": addr, "name": "Unknown", "rssi": -127}
            
            if not devices:
                print("💡 No Classic devices found in range")
                return []
            
            # 對每個找到的設備獲取 RSSI 和名稱
            print(f"\n⏱️ Found {len(devices)} Classic devices, reading details...")
            for addr in list(devices.keys()):
                try:
                    # 獲取名稱
                    name_cmd = ["hcitool", "name", addr]
                    name_result = subprocess.run(
                        name_cmd,
                        capture_output=True,
                        text=True,
                        timeout=3
                    )
                    name = name_result.stdout.strip()
                    if name:
                        devices[addr]["name"] = name
                    
                    # 獲取 RSSI (需要先建立連線，某些設備可能失敗)
                    # 注意：RSSI 對未配對設備可能無法獲取
                    rssi_cmd = ["hcitool", "rssi", addr]
                    rssi_result = subprocess.run(
                        rssi_cmd,
                        capture_output=True,
                        text=True,
                        timeout=3
                    )
                    
                    # 解析 RSSI: "RSSI return value: -45"
                    rssi_match = re.search(r'RSSI return value: (-?\d+)', rssi_result.stdout)
                    if rssi_match:
                        devices[addr]["rssi"] = int(rssi_match.group(1))
                    
                    rssi_str = f"{devices[addr]['rssi']:>4}" if devices[addr]['rssi'] != -127 else " N/A"
                    print(f"📱 {devices[addr]['name']:<20} ({addr}) RSSI={rssi_str} dBm")
                    
                except subprocess.TimeoutExpired:
                    print(f"⏱️ Timeout reading {addr}")
                except Exception as e:
                    print(f"⚠️ Error reading {addr}: {e}")
            
            return list(devices.values())
            
        except FileNotFoundError:
            print("❌ hcitool not found. Install: sudo apt install bluez")
            return []
        except Exception as e:
            print(f"❌ Classic scan failed: {e}")
            return []


    def scan_devices(self, timeout=8, show_all=False):
        """
        掃描 BLE 設備 - 檢測 RSSI 是否實時更新
        """
        print(f"\n{'='*60}")
        print(f"🔍 Scanning BLE devices for {timeout} seconds...")
        print("="*60)

        # 確保之前的掃描已停止
        self.ensure_discovery_stopped()

        # 記錄掃描前的 RSSI 值
        objects = self.get_managed_objects()
        rssi_before_scan = {}
        for path, ifaces in objects.items():
            if DEVICE_IFACE in ifaces:
                addr = str(ifaces[DEVICE_IFACE].get('Address', ''))
                rssi = int(ifaces[DEVICE_IFACE].get('RSSI', -127))
                if addr and rssi != -127:
                    rssi_before_scan[addr] = rssi

        # 啟動掃描
        try:
            self.adapter.StartDiscovery()
            time.sleep(0.3)
        except dbus.exceptions.DBusException as e:
            if "org.bluez.Error.InProgress" in str(e):
                self.ensure_discovery_stopped()
                time.sleep(0.5)
                try:
                    self.adapter.StartDiscovery()
                except Exception as e2:
                    print(f"❌ Failed to start discovery: {e2}")
                    return []
            else:
                print(f"❌ Failed to start discovery: {e}")
                return []
        except Exception as e:
            print(f"❌ Failed to start discovery: {e}")
            return []

        # 掃描期間持續輪詢設備
        device_rssi_map = {}
        device_rssi_history = {}
        scan_iterations = int(timeout / 0.5)
        
        try:
            for i in range(scan_iterations):
                time.sleep(0.5)
                
                objects = self.get_managed_objects()
                for path, ifaces in objects.items():
                    if DEVICE_IFACE not in ifaces:
                        continue
                    
                    props = self.get_device_properties(path)
                    if not props:
                        continue
                    
                    addr = str(props.get('Address', ''))
                    rssi = int(props.get('RSSI', -127))
                    
                    if addr and rssi != -127:
                        if addr not in device_rssi_history:
                            device_rssi_history[addr] = []
                        device_rssi_history[addr].append(rssi)
                        
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
                
                if (i + 1) % 4 == 0:
                    print(f"⏱️ Scanning... {len(device_rssi_map)} devices found")
        
        except KeyboardInterrupt:
            print("\n⚠️ Scan interrupted")
        finally:
            self.ensure_discovery_stopped()

        # 分析 RSSI 是否有變化
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
            
            if addr in device_rssi_map:
                rssi = device_rssi_map[addr]['rssi']
            else:
                rssi = int(props.get('RSSI', -127))
            
            # 判斷設備是否真的在線
            is_actually_online = False
            if addr in device_rssi_history:
                rssi_history = device_rssi_history[addr]
                rssi_before = rssi_before_scan.get(addr, None)
                
                has_variation = len(set(rssi_history)) > 1
                changed_from_before = (rssi_before is None) or (rssi != rssi_before)
                multiple_readings = len(rssi_history) >= 2
                
                is_actually_online = has_variation or (changed_from_before and multiple_readings)
            
            if connected:
                is_actually_online = True
            
            is_cached = (rssi != -127) and not is_actually_online and not connected
            
            if not show_all:
                if rssi == -127:
                    continue
                if not is_actually_online:
                    continue

            bonded = self.is_bonded(addr)
            devices.append({
                "path": path,
                "mac": addr,
                "name": name,
                "rssi": rssi,
                "paired": paired,
                "bonded": bonded,
                "connected": connected,
                "trusted": trusted,
                "uuids": uuids,
                "is_cached": is_cached,
                "is_actually_online": is_actually_online,
                "type": "BLE"
            })

            bond_icon = "🔒" if bonded else "🔓"
            conn_icon = "🔗" if connected else "⛓️"
            rssi_str = f"{rssi:>4}" if rssi != -127 else " N/A"
            cache_flag = " [CACHED]" if is_cached else ""
            print(f"{bond_icon}{conn_icon} {name:<20} ({addr}) RSSI={rssi_str} dBm{cache_flag}")

        print(f"\n✅ Found {len(devices)} BLE devices")
        return devices


    def scan_hybrid(self, timeout=10):
        """
        混合掃描：同時掃描 BLE 和 Bluetooth Classic
        適用於 Android 等會自動關閉 BLE 的設備
        """
        print(f"\n{'='*60}")
        print(f"🔍 Hybrid scan: BLE + Bluetooth Classic")
        print("💡 Works even if Android stops BLE advertising")
        print("="*60)
        
        # BLE 掃描（較快，優先）
        ble_timeout = min(5, timeout // 2)
        print(f"\n[1/2] BLE scan ({ble_timeout}s)...")
        ble_devices = self.scan_devices(timeout=ble_timeout, show_all=False)
        
        # Classic 掃描（較慢但更可靠）
        classic_timeout = timeout - ble_timeout
        print(f"\n[2/2] Classic scan ({classic_timeout}s)...")
        classic_devices = self.scan_classic_devices(timeout=classic_timeout)
        
        # 合併結果
        all_devices = {}
        
        # 先加入 BLE 設備（RSSI 更即時）
        for d in ble_devices:
            all_devices[d["mac"]] = d
            all_devices[d["mac"]]["type"] = "BLE"
        
        # 再加入 Classic 設備
        for d in classic_devices:
            mac = d["mac"]
            if mac not in all_devices:
                # 純 Classic 設備
                bonded = self.is_bonded(mac)
                all_devices[mac] = {
                    "path": None,
                    "mac": mac,
                    "name": d["name"],
                    "rssi": d["rssi"],
                    "paired": False,
                    "bonded": bonded,
                    "connected": False,
                    "trusted": False,
                    "uuids": [],
                    "is_cached": False,
                    "is_actually_online": True,
                    "type": "Classic"
                }
            else:
                # 設備同時支援 BLE 和 Classic
                all_devices[mac]["type"] = "BLE+Classic"
                # 如果 Classic 有 RSSI 而 BLE 沒有，使用 Classic 的
                if all_devices[mac]["rssi"] == -127 and d["rssi"] != -127:
                    all_devices[mac]["rssi"] = d["rssi"]
        
        print(f"\n{'='*60}")
        print(f"✅ Hybrid scan complete:")
        print(f"   BLE only: {sum(1 for d in all_devices.values() if d['type'] == 'BLE')}")
        print(f"   Classic only: {sum(1 for d in all_devices.values() if d['type'] == 'Classic')}")
        print(f"   BLE+Classic: {sum(1 for d in all_devices.values() if d['type'] == 'BLE+Classic')}")
        print(f"   Total: {len(all_devices)} devices")
        print("="*60)
        
        return list(all_devices.values())


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
        """從掃描結果添加設備到白名單"""
        print("\nSelect scan type:")
        print("1. BLE only (fast)")
        print("2. Bluetooth Classic only (for Android)")
        print("3. Hybrid: BLE + Classic (recommended)")
        
        scan_choice = input("Choice [3]: ").strip() or "3"
        
        if scan_choice == "1":
            devs = self.manager.scan_devices(timeout=8, show_all=True)
        elif scan_choice == "2":
            classic_devs = self.manager.scan_classic_devices(timeout=10)
            # 轉換為統一格式
            devs = []
            for d in classic_devs:
                bonded = self.manager.is_bonded(d["mac"])
                devs.append({
                    "path": None,
                    "mac": d["mac"],
                    "name": d["name"],
                    "rssi": d["rssi"],
                    "paired": False,
                    "bonded": bonded,
                    "connected": False,
                    "trusted": False,
                    "uuids": [],
                    "is_cached": False,
                    "is_actually_online": True,
                    "type": "Classic"
                })
        else:  # 3 or default
            devs = self.manager.scan_hybrid(timeout=12)
        
        if not devs:
            print("⚠️ No devices found.")
            return
        
        print("\nSelect index to add (-1 cancel):")
        for i, d in enumerate(devs):
            rssi_str = f"{d['rssi']:>4}" if d['rssi'] != -127 else " N/A"
            cache_flag = " [CACHED]" if d.get('is_cached', False) else ""
            dev_type = f"[{d.get('type', 'Unknown')}]"
            print(f"{i:2d}: {d['name']:<20} ({d['mac']}) RSSI={rssi_str} dBm {dev_type}{cache_flag}")

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

        if not d["bonded"] and d.get("path"):
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
        """監控白名單設備 - 支援 BLE 和 Classic 混合掃描"""
        if not self.whitelist:
            print("📋 Whitelist empty")
            return
        
        print("\n=== Proximity monitor ===")
        print("Select monitoring mode:")
        print("1. BLE only (fast, but Android may stop advertising)")
        print("2. Hybrid: BLE + Classic (recommended, works with Android)")
        
        mode = input("Choice [2]: ").strip() or "2"
        use_hybrid = (mode == "2")
        
        if use_hybrid:
            print("\n💡 Hybrid mode: Works even if Android stops BLE advertising")
        else:
            print("\n💡 BLE only mode: May miss Android devices when screen is off")
        
        print("Press Ctrl+C to stop\n")
        
        device_last_state = {}
        
        try:
            while True:
                # 選擇掃描方式
                if use_hybrid:
                    devs = self.manager.scan_hybrid(timeout=8)
                else:
                    devs = self.manager.scan_devices(timeout=3, show_all=False)
                
                # 只信任真正在線的設備
                active_devices = {
                    d["mac"]: d for d in devs 
                    if (d.get("is_actually_online", False) or 
                        d.get("connected", False) or 
                        d.get("type") in ["Classic", "BLE+Classic"])
                }
                
                print(f"\n[{datetime.now().strftime('%H:%M:%S')}]")
                current_time = time.time()
                
                for d in self.whitelist:
                    mac = d["mac"]
                    thr = d.get("rssi_threshold", NEAR_THRESHOLD)
                    
                    device_info = active_devices.get(mac)
                    last_state = device_last_state.get(mac, {
                        "online": False, 
                        "rssi": None, 
                        "timestamp": 0
                    })
                    was_online = last_state["online"]
                    
                    if device_info is None:
                        # 設備離線
                        if was_online:
                            status = "🔴 JUST LOST"
                            rssi_display = f"(was {last_state['rssi']})" if last_state['rssi'] else "N/A"
                            offline_since = current_time
                            print(f"{d['name']:<12} ({mac}): {status:<15} RSSI={rssi_display}")
                        else:
                            status = "🔴 OFFLINE"
                            rssi_display = "N/A"
                            offline_since = last_state.get('timestamp', current_time)
                            offline_duration = current_time - offline_since
                            print(f"{d['name']:<12} ({mac}): {status:<15} RSSI={rssi_display} [Offline {offline_duration:.0f}s]")
                        
                        device_last_state[mac] = {
                            "online": False, 
                            "rssi": last_state.get("rssi"),
                            "timestamp": offline_since
                        }
                    else:
                        # 設備在線
                        rssi = device_info.get('rssi', -127)
                        device_type = device_info.get('type', 'Unknown')
                        
                        if not was_online:
                            status = "🟢 RECONNECTED"
                        elif rssi > thr:
                            status = "🟢 NEAR"
                        else:
                            status = "🔵 FAR"
                        
                        type_flag = f" [{device_type}]"
                        rssi_display = str(rssi) if rssi != -127 else "N/A"
                        print(f"{d['name']:<12} ({mac}): {status:<15} RSSI={rssi_display}{type_flag}")
                        
                        device_last_state[mac] = {
                            "online": True, 
                            "rssi": rssi,
                            "timestamp": current_time
                        }
                
                time.sleep(2)
                
        except KeyboardInterrupt:
            print("\n⏹️ Monitor stopped")
        finally:
            print("🛑 Cleaning up...")
            self.manager.ensure_discovery_stopped()



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
        print("   🔷 BlueZ D-Bus BLE + Classic Bonding Tool")
        print("   (Auto-Accept Mode + Hybrid Scan)")
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
        print("⚠️ Warning: Running without root may have limited access")
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
    print(" BlueZ BLE + Bluetooth Classic Bonding Manager")
    print(f" Whitelist: {WHITELIST_FILE}")
    print(f" Bonding keys: {BONDING_KEYS_DIR}")
    print("\n 💡 Hybrid mode works with Android (even when BLE stops)")
    print("="*70)
    
    # 執行主選單
    main_menu()
