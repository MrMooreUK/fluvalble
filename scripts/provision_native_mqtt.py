"""Explicit native AquaSky 3 Wi-Fi setup; never run during HA setup.

Run in an environment with bleak installed. Passwords are prompted, not command
line arguments or saved files. No vendor cloud credentials are used.
"""

import argparse
import asyncio
from datetime import datetime
from getpass import getpass
import importlib.util
from pathlib import Path


def load_frames():
    """Load the pure frame builder without importing Home Assistant."""
    path = Path(__file__).resolve().parents[1] / "custom_components/fluvalble/core/mqtt_provisioning.py"
    spec = importlib.util.spec_from_file_location("mqtt_provisioning", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def provision(args, wifi: bytes, broker: bytes) -> None:
    from bleak import BleakClient

    frames = load_frames()
    notifications: asyncio.Queue[bytes] = asyncio.Queue(maxsize=32)
    buffer = bytearray()

    def notified(_sender, data):
        if len(buffer) + len(data) > 4096:
            buffer.clear()
            return
        buffer.extend(data)
        while b";;" in buffer:
            end = buffer.index(b";;") + 2
            report = bytes(buffer[:end])
            del buffer[:end]
            if not notifications.full():
                notifications.put_nowait(report)

    async def wait_for(kind: str) -> None:
        async with asyncio.timeout(60):
            while True:
                report = (await notifications.get()).decode("ascii", errors="replace")
                # Never print raw responses: firmware may echo credentials.
                if "err:" in report:
                    raise RuntimeError("Fixture reported a provisioning error; credentials are not logged")
                if mac := frames.provisioning_wifi_mac(report):
                    print(f"Fixture reported Wi-Fi identity: {mac}")
                if kind == "wifi" and report.startswith("ip:"):
                    return
                if kind == "mqtt" and "mqtt:connected;;" in report:
                    return

    async with BleakClient(args.ble_address, timeout=20) as client:
        await client.start_notify(frames.PROVISION_UUID, notified)
        characteristic = client.services.get_characteristic(frames.PROVISION_UUID)
        if characteristic is None:
            raise RuntimeError("Native Wi-Fi provisioning characteristic not found")

        async def write(frame):
            # APK sends ATT-sized chunks with a 5 ms gap.
            for offset in range(0, len(frame), 20):
                await client.write_gatt_char(
                    characteristic,
                    frame[offset : offset + 20],
                    response="write-without-response" not in characteristic.properties,
                )
                await asyncio.sleep(0.005)

        await write(wifi)
        await wait_for("wifi")
        await write(broker)
        await wait_for("mqtt")
        print("Fixture reported connection to the selected broker. Verify its uplink topic before adding it to HA.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ble-address", required=True)
    parser.add_argument("--ssid", required=True)
    parser.add_argument("--broker", required=True)
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--username", default="")
    parser.add_argument("--confirm-broker-change", action="store_true")
    args = parser.parse_args()
    if not args.confirm_broker_change:
        parser.error(
            "This replaces saved Wi-Fi/broker settings and may disconnect Fluval Connect. Explicit confirmation required."
        )
    print("Experimental: product 532 / official v10 firmware only. No firmware is flashed.")
    frames = load_frames()
    offset = datetime.now().astimezone().utcoffset()
    wifi = frames.wifi_frame(args.ssid, getpass("Wi-Fi password: "), int(offset.total_seconds() // 60) if offset else 0)
    broker = frames.broker_frame(
        args.broker, args.port, args.client_id, args.username, getpass("Local MQTT password: ")
    )
    asyncio.run(provision(args, wifi, broker))


if __name__ == "__main__":
    main()
