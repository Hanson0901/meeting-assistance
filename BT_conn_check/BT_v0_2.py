#!/usr/bin/env python3
import asyncio
import json
import os
import sys
from bleak import BleakScanner, BleakClient

WHITELIST_FILE = "whitelist.json"
NEAR_THRESHOLD = -70  # dBm，需實測調整

def load_whitelist():
    """載入白名單"""
    if not os.path.exists(WHITELIST_FILE):
        return []
    try:
        with open(WHITELIST_FILE, "r") as f:
            data = json.load(f)
        return data.get("devices", [])
    except (json.JSONDecodeError, IOError) as e:
        print(f"Error loading whitelist: {e}", file=sys.stderr)
        return []

def save_whitelist(devices):
    """儲存白名單"""
    try:
        with open(WHITELIST_FILE, "w") as f:
            json.dump({"devices": devices}, f, indent=2)
        print(f"Whitelist saved to {WHITELIST_FILE}")
    except IOError as e:
        print(f"Error saving whitelist: {e}", file=sys.stderr)

async def scan_devices(timeout=5.0):
    """掃描 BLE 裝置，回傳裝置列表與 RSSI"""
    print(f"Scanning for {timeout} seconds...")
    try:
        # 使用 return_adv=True 取得 AdvertisementData
        devices = await BleakScanner.discover(timeout=timeout, return_adv=True)
        results = []
        
        for address, (device, adv_data) in devices.items():
            rssi = adv_data.rssi if adv_data else None
            
            # 判斷裝置是否可能支援配對
            can_pair = False
            if adv_data:
                # 檢查是否有通用存取服務或通用屬性服務
                service_uuids = adv_data.service_uuids or []
                can_pair = any(
                    uuid.startswith("00001800") or uuid.startswith("00001801")
                    for uuid in service_uuids
                )
            
            device_name = device.name or "Unknown"
            print(f"Found: {device_name} ({address}) RSSI={rssi} dBm, Pairable: {can_pair}")
            
            results.append({
                "name": device_name,
                "mac": address,
                "rssi": rssi,
                "pairable": can_pair
            })
        
        return results
    except Exception as e:
        print(f"Scan error: {e}", file=sys.stderr)
        return []

async def test_connection(mac, timeout=10.0):
    """測試是否可以連接到 BLE 裝置（不會自動配對）"""
    print(f"Testing connection to {mac}...")
    try:
        async with BleakClient(mac, timeout=timeout) as client:
            if client.is_connected:
                print(f"Successfully connected to {mac}")
                print(f"Device services: {len(client.services)} services found")
                return True
    except Exception as e:
        print(f"Connection test failed: {e}")
        return False

async def cli_add_from_scan():
    """從掃描結果添加裝置到白名單"""
    devices = await scan_devices()
    if not devices:
        print("No devices found.")
        return

    # 顯示裝置列表
    for i, dev in enumerate(devices):
        pair_info = "✓ Pairable" if dev["pairable"] else "✗ No pair"
        print(f"[{i:2d}] {dev['name']:<20} ({dev['mac']}) RSSI={dev['rssi']:>4} dBm [{pair_info}]")

    # 選擇裝置
    try:
        idx = int(input("\nSelect index to add to whitelist (or -1 to cancel): "))
        if idx < 0 or idx >= len(devices):
            print("Canceled.")
            return
    except ValueError:
        print("Invalid input. Canceled.")
        return

    dev = devices[idx]
    wl = load_whitelist()
    
    # 檢查是否已存在
    if any(d["mac"] == dev["mac"] for d in wl):
        print(f"Device {dev['mac']} already in whitelist.")
        return

    # 輸入別名
    default_name = dev["name"] if dev["name"] != "Unknown" else "Device"
    alias = input(f"Input alias for {dev['mac']} (default={default_name}): ").strip()
    if not alias:
        alias = default_name

    # 添加到白名單
    wl.append({
        "name": alias,
        "mac": dev["mac"],
        "pairable": dev["pairable"],
        "rssi_threshold": NEAR_THRESHOLD
    })
    save_whitelist(wl)
    print(f"Added '{alias}' ({dev['mac']}) to whitelist.")

    # 詢問是否測試連接
    if dev["pairable"]:
        test_conn = input("Test connection now? [y/N]: ").lower() == "y"
        if test_conn:
            await test_connection(dev["mac"])
    else:
        print("Note: This device may not support standard BLE pairing.")

def cli_add_manual():
    """手動輸入 MAC 地址添加裝置"""
    mac = input("Input device MAC (e.g. AA:BB:CC:DD:EE:FF): ").strip()
    if not mac or len(mac.split(':')) != 6:
        print("Invalid MAC address format.")
        return

    name = input("Input device name/alias: ").strip()
    if not name:
        name = "Manual Device"

    wl = load_whitelist()
    
    # 檢查是否已存在
    if any(d["mac"].lower() == mac.lower() for d in wl):
        print(f"Device {mac} already in whitelist.")
        return

    wl.append({
        "name": name,
        "mac": mac,
        "pairable": False,  # 手動添加的裝置預設為不可配對
        "rssi_threshold": NEAR_THRESHOLD
    })
    save_whitelist(wl)
    print(f"Added '{name}' ({mac}) to whitelist.")

def cli_show_whitelist():
    """顯示白名單"""
    wl = load_whitelist()
    if not wl:
        print("Whitelist is empty.")
        return

    print(f"\n{'Index':<6} {'Name':<20} {'MAC Address':<18} {'Pairable':<10} {'RSSI Thr.':<10}")
    print("-" * 70)
    for i, dev in enumerate(wl):
        pairable = "Yes" if dev.get("pairable", False) else "No"
        threshold = dev.get("rssi_threshold", NEAR_THRESHOLD)
        print(f"[{i:3d}]  {dev['name']:<20} {dev['mac']:<18} {pairable:<10} {threshold:<10}")

async def proximity_monitor_loop():
    """監控白名單裝置的接近狀態"""
    wl = load_whitelist()
    if not wl:
        print("Whitelist is empty, add devices first.")
        return

    print("\nStarting proximity monitoring. Press Ctrl+C to stop.")
    print(f"Near threshold: {NEAR_THRESHOLD} dBm")
    print("-" * 50)

    try:
        while True:
            # 掃描裝置
            devices = await BleakScanner.discover(timeout=3.0, return_adv=True)
            rssi_map = {addr: adv.rssi for addr, (dev, adv) in devices.items() if adv}

            # 檢查每個白名單裝置
            for dev in wl:
                mac = dev["mac"]
                threshold = dev.get("rssi_threshold", NEAR_THRESHOLD)
                rssi = rssi_map.get(mac)
                
                if rssi is None:
                    status = "🔴 NOT FOUND"
                    distance = "N/A"
                elif rssi > threshold:
                    status = "🟢 NEAR"
                    # 簡易距離估算（僅供參考）
                    distance = f"~{10 ** ((-69 - rssi) / 20):.1f}m"
                else:
                    status = "🔵 FAR"
                    distance = f"~{10 ** ((-69 - rssi) / 20):.1f}m"
                
                print(f"{dev['name']:<15} ({mac}): {status:<12} RSSI={rssi or 'N/A':>4} dBm {distance}")

            print("-" * 50)
            await asyncio.sleep(2)
            
    except KeyboardInterrupt:
        print("\nMonitoring stopped by user.")
    except Exception as e:
        print(f"\nMonitoring error: {e}", file=sys.stderr)

def cli_remove_device():
    """從白名單移除裝置"""
    wl = load_whitelist()
    if not wl:
        print("Whitelist is empty.")
        return

    cli_show_whitelist()
    
    try:
        idx = int(input("\nEnter index to remove (or -1 to cancel): "))
        if idx < 0 or idx >= len(wl):
            print("Canceled.")
            return
        
        removed = wl.pop(idx)
        save_whitelist(wl)
        print(f"Removed '{removed['name']}' ({removed['mac']}) from whitelist.")
    except (ValueError, IndexError):
        print("Invalid input.")

def main_menu():
    """主選單"""
    while True:
        print("\n" + "="*50)
        print("   Bluetooth Proximity Monitoring Tool")
        print("="*50)
        print("1. Scan & add device to whitelist")
        print("2. Manually add device (MAC)")
        print("3. Show whitelist")
        print("4. Remove device from whitelist")
        print("5. Start proximity monitor")
        print("0. Exit")
        print("="*50)
        
        choice = input("Select: ").strip()

        if choice == "1":
            asyncio.run(cli_add_from_scan())
        elif choice == "2":
            cli_add_manual()
        elif choice == "3":
            cli_show_whitelist()
        elif choice == "4":
            cli_remove_device()
        elif choice == "5":
            asyncio.run(proximity_monitor_loop())
        elif choice == "0":
            print("Goodbye!")
            break
        else:
            print("Invalid choice. Please try again.")

if __name__ == "__main__":
    # 檢查執行環境
    if os.geteuid() == 0:
        print("Warning: Running as root is not recommended for BLE scanning.")
    
    # 檢查藍牙服務
    try:
        import dbus
    except ImportError:
        print("Installing dbus-python for better BLE support...")
        os.system("pip install dbus-python")
    
    main_menu()
