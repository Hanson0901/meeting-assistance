#!/usr/bin/env python3
import asyncio
import json
import os
import sys
import binascii
from datetime import datetime
from pathlib import Path

import pydbus
from gi.repository import GLib

# BlueZ D-Bus 介面定義
BLUEZ_SERVICE = 'org.bluez'
ADAPTER_IFACE = 'org.bluez.Adapter1'
DEVICE_IFACE = 'org.bluez.Device1'
AGENT_IFACE = 'org.bluez.Agent1'
AGENT_MGR_IFACE = 'org.bluez.AgentManager1'
PROP_IFACE = 'org.freedesktop.DBus.Properties'

# 設定檔路徑
WHITELIST_FILE = "whitelist.json"
BONDING_KEYS_DIR = Path("/var/lib/bluetooth")

class BlueZBondingManager:
    """直接操作 BlueZ D-Bus API 的 bonding 管理器"""
    
    def __init__(self):
        self.bus = pydbus.SystemBus()
        self.adapter = None
        self.agent_path = None
        self.devices = {}
        
    def get_adapter(self):
        """取得預設藍牙適配器"""
        try:
            # 先嘗試取得 hci0
            adapter_path = '/org/bluez/hci0'
            self.adapter = self.bus.get(BLUEZ_SERVICE, adapter_path)[ADAPTER_IFACE]
            return self.adapter
        except Exception as e:
            print(f" Failed to get adapter: {e}")
            return None
    
    def start_discovery(self, timeout=10):
        """開始掃描 BLE 裝置"""
        try:
            self.adapter.StartDiscovery()
            print(f" Discovery started for {timeout} seconds...")
            
            # 設定定時停止
            GLib.timeout_add_seconds(timeout, self.stop_discovery)
            return True
        except Exception as e:
            print(f" Failed to start discovery: {e}")
            return False
    
    def stop_discovery(self):
        """停止掃描"""
        try:
            self.adapter.StopDiscovery()
            print(" Discovery stopped")
            return False  # 返回 False 停止 GLib timeout
        except Exception as e:
            print(f" Failed to stop discovery: {e}")
            return False
    
    def get_managed_objects(self):
        """取得所有 BlueZ 管理的物件（裝置與服務）"""
        try:
            obj_mgr = self.bus.get(BLUEZ_SERVICE, '/')[pydbus.generic.INTERFACE_DBUS_OBJECT_MANAGER]
            return obj_mgr.GetManagedObjects()
        except Exception as e:
            print(f" Failed to get managed objects: {e}")
            return {}
    
    def scan_devices(self, timeout=10):
        """掃描並回傳裝置列表"""
        print(f"\n{'='*60}")
        print("🔍 Scanning for BLE devices...")
        print("="*60)
        
        # 開始掃描
        if not self.start_discovery(timeout):
            return []
        
        # 等待掃描完成
        loop = GLib.MainLoop()
        GLib.timeout_add_seconds(timeout, lambda: loop.quit())
        loop.run()
        
        # 取得掃描結果
        objects = self.get_managed_objects()
        devices = []
        
        for path, interfaces in objects.items():
            if DEVICE_IFACE in interfaces:
                dev_props = interfaces[DEVICE_IFACE]
                address = dev_props.get('Address', '')
                name = dev_props.get('Name', 'Unknown')
                rssi = dev_props.get('RSSI', 0)
                paired = dev_props.get('Paired', False)
                bonded = self.is_bonded(address)
                
                # 檢查是否為 LE 裝置
                uuids = dev_props.get('UUIDs', [])
                is_le = any('0000' in uuid for uuid in uuids)
                
                if is_le:  # 只顯示 BLE 裝置
                    devices.append({
                        'path': path,
                        'mac': address,
                        'name': name,
                        'rssi': rssi,
                        'paired': paired,
                        'bonded': bonded,
                        'uuids': uuids
                    })
                    
                    bond_status = "🔒" if bonded else "🔓"
                    print(f"{bond_status} {name:<20} ({address}) RSSI={rssi:>4} dBm "
                          f"[Paired: {paired}] [Bonded: {bonded}]")
        
        return devices
    
    def is_bonded(self, mac_address):
        """檢查裝置是否已 bonding"""
        try:
            # bonding 資訊儲存在 /var/lib/bluetooth/<adapter>/<device>/info
            adapter_addr = self.adapter.Address
            device_path = BONDING_KEYS_DIR / adapter_addr.replace(':', '') / mac_address.replace(':', '')
            info_file = device_path / "info"
            
            return info_file.exists()
        except:
            return False
    
    def get_bonding_info(self, mac_address):
        """讀取 bonding 資訊（LTK, IRK 等）"""
        try:
            adapter_addr = self.adapter.Address
            device_path = BONDING_KEYS_DIR / adapter_addr.replace(':', '') / mac_address.replace(':', '')
            info_file = device_path / "info"
            
            if not info_file.exists():
                return None
            
            info = {}
            with open(info_file, 'r') as f:
                current_section = None
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
        """配對裝置（會觸發 bonding）"""
        try:
            device = self.bus.get(BLUEZ_SERVICE, device_path)[DEVICE_IFACE]
            
            # 檢查是否已配對
            if device.Paired:
                print(f" Device already paired")
                return True
            
            print(f" Pairing with device...")
            device.Pair()
            
            # 等待配對完成
            timeout = 30
            while timeout > 0 and not device.Paired:
                asyncio.sleep(1)
                timeout -= 1
            
            if device.Paired:
                print(f" Pairing successful")
                
                # Trust 裝置
                device.Trusted = True
                print(f" Device trusted")
                
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
                print(f" Device already connected")
                return True
            
            print(f" Connecting to device...")
            device.Connect()
            
            timeout = 10
            while timeout > 0 and not device.Connected:
                asyncio.sleep(1)
                timeout -= 1
            
            if device.Connected:
                print(f" Connected successfully")
                return True
            else:
                print(f" Connection timeout")
                return False
                
        except Exception as e:
            print(f" Connection failed: {e}")
            return False
    
    def remove_device(self, device_path):
        """移除裝置（會刪除 bonding 資訊）"""
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
        
        # 確保 adapter 可用
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
            print(f" Whitelist saved")
        except Exception as e:
            print(f" Error saving whitelist: {e}")
    
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
    
    def add_device_from_scan(self):
        """從掃描結果添加裝置"""
        devices = self.manager.scan_devices(timeout=10)
        if not devices:
            return
        
        print(f"\n{'='*60}")
        print("Select device to add:")
        print("="*60)
        
        for i, dev in enumerate(devices):
            bonded = "🔒" if dev["bonded"] else "🔓"
            print(f"[{i:2d}] {bonded} {dev['name']:<20} ({dev['mac']}) RSSI={dev['rssi']:>4} dBm")
        
        try:
            idx = int(input("\nSelect index (or -1 to cancel): "))
            if idx < 0 or idx >= len(devices):
                print(" Canceled")
                return
            
            selected = devices[idx]
            
            # 如果未 bonding，詢問是否要配對
            if not selected["bonded"]:
                pair = input("Device not bonded. Pair now? [y/N]: ").lower() == 'y'
                if pair:
                    if not self.manager.pair_device(selected["path"]):
                        print(" Pairing failed, device not added")
                        return
            
            # 添加到白名單
            alias = input(f"Input alias (default={selected['name']}): ").strip()
            if not alias:
                alias = selected["name"]
            
            threshold = input(f"RSSI threshold (default={NEAR_THRESHOLD}): ").strip()
            threshold = int(threshold) if threshold else NEAR_THRESHOLD
            
            self.whitelist.append({
                "name": alias,
                "mac": selected["mac"],
                "rssi_threshold": threshold,
                "added_at": datetime.now().isoformat()
            })
            self.save_whitelist()
            print(f" Device added to whitelist")
            
        except (ValueError, IndexError):
            print(" Invalid input")
    
    def monitor_proximity(self):
        """監控接近狀態"""
        if not self.whitelist:
            print(" Whitelist is empty")
            return
        
        print("\n" + "="*60)
        print(" Starting proximity monitoring...")
        print("  Press Ctrl+C to stop")
        print("="*60)
        
        try:
            loop = GLib.MainLoop()
            
            # 設定定時掃描
            def scan_and_check():
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
                
                return True  # 繼續定時執行
            
            # 每 2 秒執行一次
            GLib.timeout_add_seconds(2, scan_and_check)
            
            # 開始事件迴圈
            loop.run()
            
        except KeyboardInterrupt:
            print("\n\n Monitoring stopped")
    
    def remove_device(self):
        """從白名單移除裝置"""
        self.display_whitelist()
        
        if not self.whitelist:
            return
        
        try:
            idx = int(input("\nEnter index to remove (or -1 to cancel): "))
            if idx < 0 or idx >= len(self.whitelist):
                print(" Canceled")
                return
            
            dev = self.whitelist[idx]
            
            # 同時從 BlueZ 移除（刪除 bonding）
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
    
    def show_bonding_info(self):
        """顯示 bonding 詳細資訊"""
        self.display_whitelist()
        
        if not self.whitelist:
            return
        
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
            
            print(f"\n Bonding info for {dev['name']} ({dev['mac']}):")
            print("="*60)
            
            for section, keys in info.items():
                print(f"\n[{section}]")
                for key, value in keys.items():
                    print(f"  {key:<20} = {value}")
            
        except (ValueError, IndexError):
            print("  Invalid input")

def main_menu():
    """主選單"""
    app = BLEProximityApp()
    
    while True:
        print("\n" + "="*60)
        print("    BlueZ D-Bus BLE Bonding Manager")
        print("="*60)
        print("1.  Scan & add device")
        print("2.  Show whitelist")
        print("3.  Show bonding info")
        print("4.  Remove device")
        print("5.  Start proximity monitor")
        print("0.  Exit")
        print("="*60)
        
        choice = input("Select: ").strip()
        
        if choice == "1":
            app.add_device_from_scan()
        elif choice == "2":
            app.display_whitelist()
        elif choice == "3":
            app.show_bond
