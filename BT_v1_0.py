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
        except:
            pass


    def check_device_reachable_l2ping(self, mac, timeout=2):
        """
        使用 l2ping 檢測已配對設備是否在範圍內
        這對 Android 等不可發現設備也有效
        返回: (reachable: bool, rtt: float, rssi: int)
        """
        try:
            # l2ping -c 1 -t 2 MAC
            cmd = ["l2ping", "-c", "1", "-t", str(timeout), mac]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout + 1
            )
            
            if result.returncode == 0:
                # 解析輸出: "Ping: XX:XX:XX:XX:XX:XX from YY:YY:YY:YY:YY:YY (data size 44) ...
                # 1 sent, 1 received, 0% loss, rtt min/avg/max = 12.34/12.34/12.34 ms"
                rtt_match = re.search(r'rtt min/avg/max = ([\d.]+)/([\d.]+)/([\d.]+) ms', result.stdout)
                if rtt_match:
                    rtt_avg = float(rtt_match.group(2))
                    # RTT 可以粗略估計距離，但這裡主要用於檢測可達性
                    # RTT < 50ms 通常表示設備很近
                    return (True, rtt_avg, -127)  # RSSI 無法通過 l2ping 獲取
                return (True, 0.0, -127)
            else:
                return (False, 0.0, -127)
                
        except subprocess.TimeoutExpired:
            return (False, 0.0, -127)
        except FileNotFoundError:
            print("❌ l2ping not found. Install: sudo apt install bluez-tools")
            return (False, 0.0, -127)
        except Exception as e:
            return (False, 0.0, -127)


    def check_paired_devices_status(self, device_macs=None):
        """
        檢查已配對設備的狀態（使用 l2ping）
        device_macs: 要檢查的 MAC 地址列表，None 表示檢查所有已配對設備
        返回: {mac: {"reachable": bool, "rtt": float, "name": str}}
        """
        print(f"\n{'='*60}")
        print(f"📡 Checking paired devices status (using l2ping)...")
        print("💡 Works even if devices are not discoverable")
        print("="*60)
        
        # 獲取所有已配對設備
        objects = self.get_managed_objects()
        paired_devices = {}
        
        for path, ifaces in objects.items():
            if DEVICE_IFACE not in ifaces:
                continue
            
            props = ifaces[DEVICE_IFACE]
            addr = str(props.get('Address', ''))
            paired = bool(props.get('Paired', False))
            
            if paired and (device_macs is None or addr in device_macs):
                name = str(props.get('Name', props.get('Alias', 'Unknown')))
                paired_devices[addr] = {"name": name, "reachable": False, "rtt": 0.0}
        
        if not paired_devices:
            print("⚠️ No paired devices found")
            return {}
        
        print(f"Found {len(paired_devices)} paired devices, checking reachability...")
        
        # 對每個設備進行 l2ping 測試
        results = {}
        for mac, info in paired_devices.items():
            print(f"📍 Pinging {info['name']} ({mac})...", end=" ", flush=True)
            reachable, rtt, _ = self.check_device_reachable_l2ping(mac, timeout=3)
            
            if reachable:
                print(f"✅ ONLINE (RTT: {rtt:.1f}ms)")
                results[mac] = {
                    "name": info['name'],
                    "reachable": True,
                    "rtt": rtt,
                    "rssi": -127  # l2ping 無法獲取 RSSI
                }
            else:
                print(f"❌ OFFLINE")
                results[mac] = {
                    "name": info['name'],
                    "reachable": False,
                    "rtt": 0.0,
                    "rssi": -127
                }
        
        print(f"\n✅ Check complete: {sum(1 for r in results.values() if r['reachable'])}/{len(results)} devices reachable")
        return results


    def scan_devices(self, timeout=8, show_all=False):
        """掃描 BLE 設備（用於發現新設備）"""
        print(f"\n{'='*60}")
        print(f"🔍 Scanning BLE devices for {timeout} seconds...")
        print("="*60)

        self.ensure_discovery_stopped()

        objects = self.get_managed_objects()
        rssi_before_scan = {}
        for path, ifaces in objects.items():
            if DEVICE_IFACE in ifaces:
                addr = str(ifaces[DEVICE_IFACE].get('Address', ''))
                rssi = int(ifaces[DEVICE_IFACE].get('RSSI', -127))
                if addr and rssi != -127:
                    rssi_before_scan[addr] = rssi

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
        print(f"{'Idx':<4} {'Name':<15} {'MAC':<18} {'Bonded':<8}")
        print("-" * 50)
        for i, d in enumerate(self.whitelist):
            bonded = "✓" if self.manager.is_bonded(d["mac"]) else "✗"
            print(f"{i:<4} {d['name']:<15} {d['mac']:<18} {bonded:<8}")


    def add_from_scan(self):
        """從掃描結果添加設備到白名單"""
        devs = self.manager.scan_devices(timeout=8, show_all=True)
        
        if not devs:
            print("⚠️ No devices found.")
            return
        
        print("\nSelect index to add (-1 cancel):")
        for i, d in enumerate(devs):
            rssi_str = f"{d['rssi']:>4}" if d['rssi'] != -127 else " N/A"
            cache_flag = " [CACHED]" if d.get('is_cached', False) else ""
            print(f"{i:2d}: {d['name']:<20} ({d['mac']}) RSSI={rssi_str} dBm{cache_flag}")

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

        self.whitelist.append(
            {
                "name": alias,
                "mac": d["mac"],
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
        """監控白名單設備 - 使用 l2ping 檢測已配對設備"""
        if not self.whitelist:
            print("📋 Whitelist empty")
            return
        
        print("\n=== Proximity monitor (using l2ping) ===")
        print("💡 Works with ANY paired device (even non-discoverable Android)")
        print("⚠️ Note: Devices must be PAIRED first!")
        print("Press Ctrl+C to stop\n")
        
        # 檢查所有白名單設備是否已配對
        whitelist_macs = [d["mac"] for d in self.whitelist]
        unpaired = [d for d in self.whitelist if not self.manager.is_bonded(d["mac"])]
        
        if unpaired:
            print("⚠️ Warning: Following devices are not paired:")
            for d in unpaired:
                print(f"   - {d['name']} ({d['mac']})")
            print("💡 Pair them first using option 1 (Scan & add device)\n")
        
        device_last_state = {}
        
        try:
            while True:
                # 使用 l2ping 檢查所有白名單設備
                results = self.manager.check_paired_devices_status(whitelist_macs)
                
                print(f"\n[{datetime.now().strftime('%H:%M:%S')}]")
                current_time = time.time()
                
                for d in self.whitelist:
                    mac = d["mac"]
                    
                    device_info = results.get(mac)
                    last_state = device_last_state.get(mac, {
                        "online": False,
                        "timestamp": 0
                    })
                    was_online = last_state["online"]
                    
                    if device_info is None or not device_info["reachable"]:
                        # 設備離線
                        if was_online:
                            status = "🔴 JUST LOST"
                            offline_since = current_time
                            print(f"{d['name']:<12} ({mac}): {status:<15}")
                        else:
                            status = "🔴 OFFLINE"
                            offline_since = last_state.get('timestamp', current_time)
                            offline_duration = current_time - offline_since
                            print(f"{d['name']:<12} ({mac}): {status:<15} [Offline {offline_duration:.0f}s]")
                        
                        device_last_state[mac] = {
                            "online": False,
                            "timestamp": offline_since
                        }
                    else:
                        # 設備在線
                        rtt = device_info.get('rtt', 0.0)
                        
                        if not was_online:
                            status = "🟢 RECONNECTED"
                        else:
                            status = "🟢 ONLINE"
                        
                        rtt_display = f" RTT:{rtt:.1f}ms" if rtt > 0 else ""
                        print(f"{d['name']:<12} ({mac}): {status:<15}{rtt_display}")
                        
                        device_last_state[mac] = {
                            "online": True,
                            "timestamp": current_time
                        }
                
                # 等待下次檢查（l2ping 較慢，建議間隔長一點）
                time.sleep(5)
                
        except KeyboardInterrupt:
            print("\n⏹️ Monitor stopped")



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
        print("   🔷 BlueZ Bluetooth Proximity Monitor")
        print("   (Works with Android - uses l2ping)")
        print("=" * 60)
        print("1. 📡 Scan & add device (must pair first!)")
        print("2. 📋 Show whitelist")
        print("3. 🔐 Show bonding info")
        print("4. 🗑️ Remove device")
        print("5. ▶️ Start proximity monitor (l2ping)")
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
        print("⚠️ This script requires root privileges")
        print("   Run with: sudo python3 script.py")
        sys.exit(1)
    
    if not Path("/var/run/dbus/system_bus_socket").exists():
        print("❌ D-Bus system socket not found. Is BlueZ running?")
        sys.exit(1)
    
    # 檢查 l2ping 是否可用
    try:
        subprocess.run(["which", "l2ping"], capture_output=True, check=True)
    except:
        print("❌ l2ping not found. Install: sudo apt install bluez-tools")
        sys.exit(1)
    
    # 設置 D-Bus 主循環
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    
    # 啟動 GLib main loop 在背景執行緒
    loop_thread = threading.Thread(target=run_main_loop, daemon=True)
    loop_thread.start()
    
    print("="*70)
    print(" BlueZ Bluetooth Proximity Monitor (l2ping mode)")
    print(f" Whitelist: {WHITELIST_FILE}")
    print(f" Bonding keys: {BONDING_KEYS_DIR}")
    print("\n 💡 Uses l2ping - works with Android even when not discoverable!")
    print(" ⚠️  Devices MUST be paired first!")
    print("="*70)
    
    # 執行主選單
    main_menu()
