#!/usr/bin/env python3
import sys
import json
import os
import time
import binascii
from pathlib import Path
from datetime import datetime
from gi.repository import GLib
import pydbus

# BlueZ D-Bus 介面定義
BLUEZ_SERVICE = 'org.bluez'
ADAPTER_IFACE = 'org.bluez.Adapter1'
DEVICE_IFACE = 'org.bluez.Device1'
AGENT_MGR_IFACE = 'org.bluez.AgentManager1'
PROP_IFACE = 'org.freedesktop.DBus.Properties'
OBJECT_MGR_IFACE = 'org.freedesktop.DBus.ObjectManager'

# 設定檔路徑
WHITELIST_FILE = "whitelist_dbus.json"
BONDING_KEYS_DIR = Path("/var/lib/bluetooth")

class BlueZBondingManager:
    """直接操作 BlueZ D-Bus API 的 bonding 管理器"""
    
    def __init__(self):
        self.bus = pydbus.SystemBus()
        self.adapter = None
        self.devices_cache = {}
        
    def get_adapter(self):
        """取得預設藍牙適配器"""
        try:
            adapter_path = '/org/bluez/hci0'
            self.adapter = self.bus.get(BLUEZ_SERVICE, adapter_path)[ADAPTER_IFACE]
            return self.adapter
        except Exception as e:
            print(f" Failed to get adapter: {e}")
            return None
    
    def get_managed_objects(self):
        """取得所有 BlueZ 管理的物件"""
        try:
            obj_mgr = self.bus.get(BLUEZ_SERVICE, '/')[OBJECT_MGR_IFACE]
            return obj_mgr.GetManagedObjects()
        except Exception as e:
            print(f" Failed to get managed objects: {e}")
            return {}
    
    def scan_devices(self, timeout=10):
        """掃描 BLE 裝置"""
        print(f"\n{'='*70}")
        print(f"🔍 Starting BLE scan for {timeout} seconds...")
        print("="*70)
        
        try:
            # 開始掃描
            self.adapter.StartDiscovery()
            print("📡 Discovery started...")
            
            # 等待掃描完成
            time.sleep(timeout)
            
            # 停止掃描
            self.adapter.StopDiscovery()
            print(" Discovery stopped")
            
            # 取得掃描結果
            objects = self.get_managed_objects()
            devices = []
            
            for path, interfaces in objects.items():
                if DEVICE_IFACE in interfaces:
                    props = interfaces[DEVICE_IFACE]
                    address = props.get('Address', '')
                    name = props.get('Alias', props.get('Name', 'Unknown'))
                    rssi = props.get('RSSI', -127)
                    paired = props.get('Paired', False)
                    connected = props.get('Connected', False)
                    trusted = props.get('Trusted', False)
                    
                    # 檢查是否為 LE 裝置
                    uuids = props.get('UUIDs', [])
                    is_le = len(uuids) > 0
                    
                    if is_le and rssi != -127:  # 只顯示有 RSSI 的 LE 裝置
                        # 檢查 bonding 狀態
                        bonded = self.is_bonded(address)
                        
                        devices.append({
                            'path': path,
                            'mac': address,
                            'name': name,
                            'rssi': rssi,
                            'paired': paired,
                            'bonded': bonded,
                            'connected': connected,
                            'trusted': trusted,
                            'uuids': uuids
                        })
                        
                        # 顯示裝置資訊
                        bond_icon = "🔒" if bonded else "🔓"
                        conn_icon = "🔗" if connected else "⛓️"
                        print(f"{bond_icon}{conn_icon} {name:<20} ({address}) "
                              f"RSSI={rssi:>4} dBm [Paired: {paired}] [Trusted: {trusted}]")
            
            print(f"\n Found {len(devices)} BLE devices")
            return devices
            
        except Exception as e:
            print(f" Scan failed: {e}")
            return []
    
    def is_bonded(self, mac_address):
        """檢查裝置是否已 bonding"""
        try:
            adapter_addr = self.adapter.Address
            device_path = BONDING_KEYS_DIR / adapter_addr.replace(':', '') / mac_address.replace(':', '')
            info_file = device_path / "info"
            return info_file.exists()
        except:
            return False
    
    def get_bonding_info(self, mac_address):
        """讀取 bonding 金鑰資訊"""
        try:
            adapter_addr = self.adapter.Address
            device_path = BONDING_KEYS_DIR / adapter_addr.replace(':', '') / mac_address.replace(':', '')
            info_file = device_path / "info"
            
            if not info_file.exists():
                return None
            
            info = {}
            current_section = None
            
            with open(info_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('[') and line.endswith(']'):
                        current_section = line[1:-1]
                        info[current_section] = {}
                    elif '=' in line and current_section:
                        key, value = line.split('=', 1)
                        info[current_section][key.strip()] = value.strip()
            
            return info
        except Exception as e:
            print(f" Failed to read bonding info: {e}")
            return None
    
    def pair_device(self, device_path):
        """配對裝置（會建立 bonding）"""
        try:
            device = self.bus.get(BLUEZ_SERVICE, device_path)[DEVICE_IFACE]
            
            if device.Paired:
                print(f" Already paired")
                return True
            
            print(f" Starting pairing...")
            device.Pair()
            
            # 等待配對完成
            timeout = 30
            while timeout > 0 and not device.Paired:
                time.sleep(1)
                timeout -= 1
            
            if device.Paired:
                print(f" Pairing successful")
                
                # 設定為信任
                device.Trusted = True
                print(f" Device trusted")
                
                # 等待 bonding 資訊寫入
                time.sleep(2)
                
                return True
            else:
                print(f" Pairing timeout")
                return False
                
        except Exception as e:
            print(f" Pairing failed: {e}")
            return False
    
    def connect_device(self, device_path):
        """連接裝置"""
        try:
            device = self.bus.get(BLUEZ_SERVICE, device_path)[DEVICE_IFACE]
            
            if device.Connected:
                print(f" Already connected")
                return True
            
            print(f" Connecting...")
            device.Connect()
            
            timeout = 10
            while timeout > 0 and not device.Connected:
                time.sleep(1)
                timeout -= 1
            
            if device.Connected:
                print(f" Connected")
                return True
            else:
                print(f" Connection timeout")
                return False
                
        except Exception as e:
            print(f" Connection failed: {e}")
            return False
    
    def remove_device(self, device_path):
        """移除裝置（刪除 bonding）"""
        try:
            self.adapter.RemoveDevice(device_path)
            print(f" Device removed (bonding info deleted)")
            return True
        except Exception as e:
            print(f" Failed to remove device: {e}")
            return False

class BLEProximityApp:
    """BLE 接近偵測應用程式"""
    
    def __init__(self):
        self.manager = BlueZBondingManager()
        self.whitelist = self.load_whitelist()
        
        if not self.manager.get_adapter():
            print(" Bluetooth adapter not available")
            sys.exit(1)
    
    def load_whitelist(self):
        """載入白名單"""
        if not os.path.exists(WHITELIST_FILE):
            return []
        try:
            with open(WHITELIST_FILE, "r") as f:
                data = json.load(f)
            return data.get("devices", [])
        except Exception as e:
            print(f" Error loading whitelist: {e}")
            return []
    
    def save_whitelist(self):
        """儲存白名單"""
        try:
            with open(WHITELIST_FILE, "w") as f:
                json.dump({
                    "devices": self.whitelist,
                    "last_updated": datetime.now().isoformat(),
                    "note": "Bonding keys stored in /var/lib/bluetooth"
                }, f, indent=2)
            print(f" Whitelist saved to {WHITELIST_FILE}")
        except Exception as e:
            print(f" Error saving whitelist: {e}")
    
    def add_device_from_scan(self):
        """從掃描添加裝置"""
        devices = self.manager.scan_devices(timeout=10)
        if not devices:
            return
        
        print(f"\n{'='*70}")
        print("Select device to add:")
        print("="*70)
        
        for i, dev in enumerate(devices):
            print(f"[{i:2d}] {dev['name']:<20} ({dev['mac']}) RSSI={dev['rssi']:>4} dBm "
                  f"[Bonded: {dev['bonded']}]")
        
        try:
            idx = int(input("\nSelect index (or -1 to cancel): "))
            if idx < 0 or idx >= len(devices):
                print(" Canceled")
                return
            
            dev = devices[idx]
            
            # 如果未 bonding，詢問是否要配對
            if not dev["bonded"]:
                pair = input("Device not bonded. Pair now? [y/N]: ").lower() == 'y'
                if pair:
                    if not self.manager.pair_device(dev["path"]):
                        print(" Pairing failed, device not added")
                        return
            
            # 添加到白名單
            alias = input(f"Input alias (default={dev['name']}): ").strip()
            if not alias:
                alias = dev["name"]
            
            threshold = input(f"RSSI threshold (default={NEAR_THRESHOLD}): ").strip()
            threshold = int(threshold) if threshold else NEAR_THRESHOLD
            
            self.whitelist.append({
                "name": alias,
                "mac": dev["mac"],
                "rssi_threshold": threshold,
                "added_at": datetime.now().isoformat()
            })
            self.save_whitelist()
            print(f" Device added to whitelist")
            
        except (ValueError, IndexError):
            print(" Invalid input")
    
    def remove_device(self):
        """移除裝置"""
        if not self.whitelist:
            print(" Whitelist is empty")
            return
        
        self.display_whitelist()
        
        try:
            idx = int(input("\nEnter index to remove (or -1 to cancel): "))
            if idx < 0 or idx >= len(self.whitelist):
                print(" Canceled")
                return
            
            dev = self.whitelist[idx]
            
            # 從 BlueZ 移除（刪除 bonding）
            objects = self.manager.get_managed_objects()
            for path, interfaces in objects.items():
                if DEVICE_IFACE in interfaces:
                    if interfaces[DEVICE_IFACE].get('Address') == dev["mac"]:
                        self.manager.remove_device(path)
                        break
            
            # 從白名單移除
            removed = self.whitelist.pop(idx)
            self.save_whitelist()
            print(f" Removed '{removed['name']}' ({removed['mac']})")
            
        except (ValueError, IndexError):
            print(" Invalid input")
    
    def display_whitelist(self):
        """顯示白名單"""
        if not self.whitelist:
            print(" Whitelist is empty")
            return
        
        print(f"\n Whitelist ({len(self.whitelist)} devices):")
        print(f"{'Index':<6} {'Name':<15} {'MAC':<18} {'Bonded':<8} {'RSSI Thr.':<10}")
        print("-" * 65)
        
        for i, dev in enumerate(self.whitelist):
            bonded = "✓" if self.manager.is_bonded(dev["mac"]) else "✗"
            threshold = dev.get("rssi_threshold", NEAR_THRESHOLD)
            print(f"[{i:3d}]  {dev['name']:<15} {dev['mac']:<18} {bonded:<8} {threshold:<10}")
    
    def show_bonding_info(self):
        """顯示 bonding 詳細資訊"""
        if not self.whitelist:
            print(" Whitelist is empty")
            return
        
        self.display_whitelist()
        
        try:
            idx = int(input("\nEnter index to view bonding info (or -1 to cancel): "))
            if idx < 0 or idx >= len(self.whitelist):
                print(" Canceled")
                return
            
            dev = self.whitelist[idx]
            info = self.manager.get_bonding_info(dev["mac"])
            
            if not info:
                print(" No bonding information found")
                return
            
            print(f"\n🔐 Bonding info for {dev['name']} ({dev['mac']}):")
            print("="*70)
            
            for section, keys in info.items():
                print(f"\n[{section}]")
                for key, value in keys.items():
                    # 如果是金鑰，顯示前 16 字元
                    if 'Key' in key and len(value) > 32:
                        value = value[:32] + "..."
                    print(f"  {key:<25} = {value}")
            
        except (ValueError, IndexError):
            print(" Invalid input")
    
    def monitor_proximity(self):
        """監控接近狀態"""
        if not self.whitelist:
            print(" Whitelist is empty")
            return
        
        print("\n" + "="*70)
        print(" Starting proximity monitoring...")
        print("  Press Ctrl+C to stop")
        print("="*70)
        
        try:
            while True:
                # 掃描裝置
                devices = self.manager.scan_devices(timeout=3)
                rssi_map = {dev["mac"]: dev["rssi"] for dev in devices}
                
                print(f"\n[{datetime.now().strftime('%H:%M:%S')}]")
                print("-" * 50)
                
                for dev in self.whitelist:
                    mac = dev["mac"]
                    threshold = dev.get("rssi_threshold", NEAR_THRESHOLD)
                    rssi = rssi_map.get(mac)
                    
                    if rssi is None:
                        status = "🔴 LOST"
                    elif rssi > threshold:
                        status = "🟢 NEAR"
                    else:
                        status = "🔵 FAR"
                    
                    print(f"{dev['name']:<12} ({mac}): {status:<10} RSSI={rssi or 'N/A':>4} dBm")
                
                time.sleep(2)
                
        except KeyboardInterrupt:
            print("\n\n Monitoring stopped")

def main_menu():
    """主選單"""
    app = BLEProximityApp()
    
    while True:
        print("\n" + "="*70)
        print("    BlueZ D-Bus BLE Bonding Manager")
        print("="*70)
        print("1.  Scan & add device")
        print("2.  Show whitelist")
        print("3.  Show bonding info")
        print("4.  Remove device")
        print("5.  Start proximity monitor")
        print("0.  Exit")
        print("="*70)
        
        choice = input("Select: ").strip()
        
        if choice == "1":
            app.add_device_from_scan()
        elif choice == "2":
            app.display_whitelist()
        elif choice == "3":
            app.show_bonding_info()
        elif choice == "4":
            app.remove_device()
        elif choice == "5":
            app.monitor_proximity()
        elif choice == "0":
            print(" Goodbye!")
            break
        else:
            print(" Invalid choice")

if __name__ == "__main__":
    # 檢查執行環境
    if os.geteuid() != 0:
        print("  Warning: Running without root may have limited access to bonding keys")
        print("   Consider running with sudo for full functionality")
        print("="*70)
    
    # 檢查 BlueZ 是否運行
    if not Path("/var/run/dbus/system_bus_socket").exists():
        print
