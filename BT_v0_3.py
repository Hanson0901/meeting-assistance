#!/usr/bin/env python3
import asyncio
import json
import os
import sys
from datetime import datetime
from bleak import BleakScanner, BleakClient

WHITELIST_FILE = "whitelist.json"
NEAR_THRESHOLD = -70

def load_whitelist():
    if not os.path.exists(WHITELIST_FILE):
        return []
    try:
        with open(WHITELIST_FILE, "r") as f:
            data = json.load(f)
        return data.get("devices", [])
    except (json.JSONDecodeError, IOError) as e:
        print(f"  Error loading whitelist: {e}", file=sys.stderr)
        return []

def save_whitelist(devices):
    try:
        with open(WHITELIST_FILE, "w") as f:
            json.dump({
                "devices": devices,
                "last_updated": datetime.now().isoformat(),
                "note": "MAC addresses are post-bonding resolved addresses"
            }, f, indent=2)
        print(f"  Whitelist saved")
    except IOError as e:
        print(f"  Error saving whitelist: {e}", file=sys.stderr)

async def scan_devices(timeout=15.0):
    print(f" Scanning for {timeout} seconds...")
    try:
        devices = await BleakScanner.discover(timeout=timeout, return_adv=True)
        results = []
        
        for address, (device, adv_data) in devices.items():
            rssi = adv_data.rssi if adv_data else None
            
            # 檢查是否已 bonding（BlueZ 會標記）
            is_bonded = False
            if adv_data:
                # 如果有特定服務，可能已經 bonding 過
                service_uuids = adv_data.service_uuids or []
                is_bonded = len(service_uuids) > 0
            
            device_name = device.name or "Unknown"
            print(f"  {device_name:<20} ({address}) RSSI={rssi:>4} dBm [Bonded: {is_bonded}]")
            
            results.append({
                "name": device_name,
                "mac": address,
                "rssi": rssi,
                "bonded": is_bonded,
                "logical_id": None  # 之後可從 GATT 讀取
            })
        
        return results
    except Exception as e:
        print(f" Scan error: {e}", file=sys.stderr)
        return []

async def read_logical_id(mac):
    """嘗試從裝置讀取邏輯 ID（需要自訂 GATT characteristic）"""
    try:
        async with BleakClient(mac, timeout=5.0) as client:
            if client.is_connected:
                # 這裡假設有一個 UUID 為 "00002a00-0000-1000-8000-00805f9b34fb" 的 characteristic
                # 實際上你需要根據自己的裝置修改
                data = await client.read_gatt_char("00002a00-0000-1000-8000-00805f9b34fb")
                return data.decode('utf-8').strip()
    except:
        return None

async def cli_add_from_scan():
    devices = await scan_devices()
    if not devices:
        return

    # 顯示裝置列表
    for i, dev in enumerate(devices):
        status = "🔒" if dev["bonded"] else "🔓"
        print(f"[{i:2d}] {status} {dev['name']:<20} ({dev['mac']}) RSSI={dev['rssi']:>4} dBm")

    # 選擇裝置
    try:
        idx = int(input("\nSelect index to add to whitelist (or -1 to cancel): "))
        if idx < 0 or idx >= len(devices):
            print("  Canceled.")
            return
    except ValueError:
        print("  Invalid input. Canceled.")
        return

    dev = devices[idx]
    wl = load_whitelist()
    
    # 檢查是否已存在（用 MAC 檢查）
    if any(d["mac"].lower() == dev["mac"].lower() for d in wl):
        print(f"  Device {dev['mac']} already in whitelist.")
        return

    # 輸入別名
    default_name = dev["name"] if dev["name"] != "Unknown" else "Device"
    alias = input(f"Input alias for {dev['mac']} (default={default_name}): ").strip()
    if not alias:
        alias = default_name

    # 嘗試讀取邏輯 ID（如果裝置支援）
    logical_id = None
    if dev["bonded"]:
        print("🔍 Attempting to read logical ID from device...")
        logical_id = await read_logical_id(dev["mac"])
        if logical_id:
            print(f"  Found logical ID: {logical_id}")

    # 添加到白名單
    wl.append({
        "name": alias,
        "mac": dev["mac"],
        "logical_id": logical_id,
        "bonded": dev["bonded"],
        "rssi_threshold": NEAR_THRESHOLD,
        "added_at": datetime.now().isoformat()
    })
    save_whitelist(wl)
    print(f" Added '{alias}' ({dev['mac']}) to whitelist.")

def cli_show_whitelist():
    wl = load_whitelist()
    if not wl:
        print(" Whitelist is empty.")
        return

    print(f"\n  Whitelist ({len(wl)} devices):")
    print(f"{'Index':<6} {'Name':<15} {'MAC':<18} {'Logical ID':<12} {'Bonded':<8} {'RSSI Thr.':<10}")
    print("-" * 80)
    
    for i, dev in enumerate(wl):
        bonded = "✓" if dev.get("bonded", False) else "✗"
        logical_id = dev.get("logical_id", "N/A") or "N/A"
        threshold = dev.get("rssi_threshold", NEAR_THRESHOLD)
        print(f"[{i:3d}]  {dev['name']:<15} {dev['mac']:<18} {logical_id:<12} {bonded:<8} {threshold:<10}")

async def proximity_monitor_loop():
    wl = load_whitelist()
    if not wl:
        print(" Whitelist is empty, add devices first.")
        return

    print("\n" + "="*60)
    print(" Starting proximity monitoring...")
    print("  Note: MAC addresses are resolved by BlueZ if bonded")
    print("="*60)

    try:
        while True:
            devices = await BleakScanner.discover(timeout=3.0, return_adv=True)
            rssi_map = {addr: adv.rssi for addr, (dev, adv) in devices.items() if adv}

            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Scan complete")
            
            for dev in wl:
                mac = dev["mac"]
                threshold = dev.get("rssi_threshold", NEAR_THRESHOLD)
                rssi = rssi_map.get(mac)
                
                # 顯示邏輯 ID（如果有的話）
                identifier = dev.get("logical_id") or mac
                
                if rssi is None:
                    status = "🔴 LOST"
                elif rssi > threshold:
                    status = "🟢 NEAR"
                else:
                    status = "🔵 FAR"
                
                print(f"{dev['name']:<12} ({identifier:<8}): {status:<10} RSSI={rssi or 'N/A':>4} dBm")

            await asyncio.sleep(2)
            
    except KeyboardInterrupt:
        print("\n\n  Monitoring stopped.")

def main_menu():
    while True:
        print("\n" + "="*60)
        print("    BLE Proximity Tool (MAC Randomization Aware)")
        print("="*60)
        print("1.   Scan & add device")
        print("2.   Manually add device")
        print("3.   Show whitelist")
        print("4.   Remove device")
        print("5.   Start monitor")
        print("0.   Exit")
        print("="*60)
        
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
            print(" Goodbye!")
            break
        else:
            print(" Invalid choice.")

if __name__ == "__main__":
    print("🔧 BLE Proximity Tool with Bonding Support")
    print(f" Whitelist: {WHITELIST_FILE}")
    print(f" Bonding keys stored in: /var/lib/bluetooth/")
    print("="*60)
    
    main_menu()
