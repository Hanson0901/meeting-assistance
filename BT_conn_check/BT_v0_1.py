#!/usr/bin/env python3
import asyncio
import json
import os
import subprocess
from bleak import BleakScanner

WHITELIST_FILE = "whitelist.json"
NEAR_THRESHOLD = -70  # dBm，需實測調整

def load_whitelist():
    if not os.path.exists(WHITELIST_FILE):
        return []
    with open(WHITELIST_FILE, "r") as f:
        data = json.load(f)
    return data.get("devices", [])

def save_whitelist(devices):
    with open(WHITELIST_FILE, "w") as f:
        json.dump({"devices": devices}, f, indent=2)

async def scan_devices(timeout=5.0):
    print(f"Scanning for {timeout} seconds...")
    # 修正：使用 return_adv=True 並從 AdvertisementData 取得 RSSI
    devices = await BleakScanner.discover(timeout=timeout, return_adv=True)
    results = []
    for address, (device, adv_data) in devices.items():
        rssi = adv_data.rssi if adv_data else None
        print(f"Found: {device.name} ({address}) RSSI={rssi} dBm")
        results.append({"name": device.name, "mac": address, "rssi": rssi})
    return results

def pair_device_with_bluetoothctl(mac):
    cmds = [
        ["bluetoothctl", "pair", mac],
        ["bluetoothctl", "trust", mac],
        ["bluetoothctl", "connect", mac],
    ]
    for cmd in cmds:
        print("Running:", " ".join(cmd))
        subprocess.run(cmd, check=False)

async def cli_add_from_scan():
    devices = await scan_devices()
    if not devices:
        print("No devices found.")
        return

    for i, dev in enumerate(devices):
        print(f"[{i}] {dev['name']} ({dev['mac']}) RSSI={dev['rssi']} dBm")

    idx = int(input("Select index to add to whitelist (or -1 to cancel): "))
    if idx < 0 or idx >= len(devices):
        print("Canceled.")
        return

    dev = devices[idx]
    wl = load_whitelist()
    alias = input(f"Input alias for {dev['mac']} (default={dev['name']}): ") or dev["name"]
    wl.append({"name": alias, "mac": dev["mac"]})
    save_whitelist(wl)
    print(f"Added {alias} ({dev['mac']}) to whitelist.")

    do_pair = input("Pair this device now? [y/N]: ").lower() == "y"
    if do_pair:
        pair_device_with_bluetoothctl(dev["mac"])

def cli_add_manual():
    mac = input("Input device MAC (e.g. AA:BB:CC:DD:EE:FF): ").strip()
    name = input("Input device name/alias: ").strip()
    wl = load_whitelist()
    wl.append({"name": name, "mac": mac})
    save_whitelist(wl)
    print(f"Added {name} ({mac}) to whitelist.")

def cli_show_whitelist():
    wl = load_whitelist()
    if not wl:
        print("Whitelist is empty.")
        return
    for i, dev in enumerate(wl):
        print(f"[{i}] {dev['name']} ({dev['mac']})")

async def proximity_monitor_loop():
    wl = load_whitelist()
    if not wl:
        print("Whitelist is empty, add devices first.")
        return

    print("Start proximity monitoring. Press Ctrl+C to stop.")
    try:
        while True:
            # 修正：使用 return_adv=True
            devices = await BleakScanner.discover(timeout=3.0, return_adv=True)
            rssi_map = {addr: adv.rssi for addr, (dev, adv) in devices.items() if adv}

            for dev in wl:
                mac = dev["mac"]
                rssi = rssi_map.get(mac)
                if rssi is None:
                    status = "NOT FOUND"
                elif rssi > NEAR_THRESHOLD:
                    status = f"NEAR (RSSI={rssi} dBm)"
                else:
                    status = f"FAR (RSSI={rssi} dBm)"
                print(f"{dev['name']} ({mac}): {status}")
            print("-" * 40)
            await asyncio.sleep(2)
    except KeyboardInterrupt:
        print("Stopped.")

def main_menu():
    while True:
        print("\n=== Bluetooth Proximity Tool ===")
        print("1. Scan & add device to whitelist")
        print("2. Manually add device (MAC)")
        print("3. Show whitelist")
        print("4. Start proximity monitor")
        print("0. Exit")
        choice = input("Select: ").strip()

        if choice == "1":
            asyncio.run(cli_add_from_scan())
        elif choice == "2":
            cli_add_manual()
        elif choice == "3":
            cli_show_whitelist()
        elif choice == "4":
            asyncio.run(proximity_monitor_loop())
        elif choice == "0":
            break
        else:
            print("Invalid choice.")

if __name__ == "__main__":
    main_menu()
