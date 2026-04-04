import pydbus

bus = pydbus.SessionBus()
obex_client = bus.get("org.bluez.obex", "/org/bluez/obex")