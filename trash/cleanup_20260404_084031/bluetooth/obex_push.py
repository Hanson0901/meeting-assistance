# bluetooth/obex_push.py
import os
import dbus

from .obex_runtime import ensure_obex_session, ObexError

class ObexPushError(RuntimeError):
    pass

def push_file(file_path: str, device_mac: str, root_dir: str = "/") -> bool:
    """
    透過 OBEX Object Push 傳送檔案到手機（使用 session bus 版本）
    """
    file_path = os.path.abspath(file_path)
    if not os.path.exists(file_path):
        raise ObexPushError(f"file not found: {file_path}")

    try:
        bus = ensure_obex_session(root_dir=root_dir)
        print("🔎 OBEX bus type:", type(bus))
        print("🔎 DBUS_SESSION_BUS_ADDRESS =", os.environ.get("DBUS_SESSION_BUS_ADDRESS"))
        client = dbus.Interface(
            bus.get_object("org.bluez.obex", "/org/bluez/obex"),
            "org.bluez.obex.Client1"
        )

        # 建立 OPP session（Target=OPP）
        session_path = client.CreateSession(device_mac, {"Target": "OPP"})
        session = dbus.Interface(
            bus.get_object("org.bluez.obex", session_path),
            "org.bluez.obex.ObjectPush1"
        )

        session.SendFile(file_path)
        return True

    except ObexError as e:
        raise ObexPushError(f"OBEX runtime not ready: {e}") from e
    except dbus.DBusException as e:
        raise ObexPushError(f"DBus error: {e.get_dbus_message()}") from e
    except Exception as e:
        raise ObexPushError(f"Unexpected error: {e}") from e
