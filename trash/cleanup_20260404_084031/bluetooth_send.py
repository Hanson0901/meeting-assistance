#!/usr/bin/env python3
import sys
from meeting_v1_integrated import BluetoothFileSender, ObexPushError

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: bluetooth_send.py file1 [file2 ...]")
        sys.exit(1)

    files = sys.argv[1:]
    sender = BluetoothFileSender()

    try:
        mac, name = sender.auto_send_to_first_paired(files)
        print(f"OK: sent to {name} ({mac})")
    except ObexPushError as e:
        print(f"ERROR: {e}")
        sys.exit(2)
