"""A single Fluval BLE connected LED device."""

from collections.abc import Callable
from datetime import UTC, datetime
import logging
from typing import TypedDict

from bleak import AdvertisementData, BLEDevice

from .client import Client

_LOGGER = logging.getLogger(__name__)

NUMBERS = ["channel_1", "channel_2", "channel_3", "channel_4", "channel_5"]
SELECTS = ["mode"]
MODES = ["manual", "automatic", "professional"]


class Attribute(TypedDict, total=False):
    """Attributes used by enitites like binary_sensor and number."""

    options: list[str]
    default: str

    min: int
    max: int
    step: int
    value: int

    is_on: bool
    extra: dict


class Device:
    """Fluval BLE LED device class."""

    def __init__(
        self, name: str, device: BLEDevice, advertisement: AdvertisementData
    ) -> None:
        """Initialize the device."""
        self.name = name
        self.client = Client(device, self.set_connected, self.decode_update_packet)
        self.connected = False
        self.conn_info = {"mac": device.address}
        self.updates_connect: list = []
        self.updates_component: list = []
        self.values = {}
        self.update_ble(advertisement)
        self.values["channel_1"] = 0
        self.values["channel_2"] = 0
        self.values["channel_3"] = 0
        self.values["channel_4"] = 0
        self.values["channel_5"] = 0
        self.values["mode"] = "manual"
        self.values["led_on_off"] = False

    @property
    def mac(self) -> str:
        """Expose the MAC address of the device."""
        return self.client.device.address

    def update_ble(self, advertisement: AdvertisementData) -> None:
        """Update BLE metadata."""
        self.conn_info["last_seen"] = datetime.now(UTC)
        self.conn_info["rssi"] = advertisement.rssi

        for handler in self.updates_connect:
            handler()

    def set_connected(self, connected: bool):
        """Set the connection status."""
        self.connected = connected

        for handler in self.updates_connect:
            handler()

    def numbers(self) -> list[str]:
        """List of numbers provided by the device."""
        return list(NUMBERS)

    def selects(self) -> list[str]:
        """List of select boxes provided by the device."""
        return list(SELECTS)

    def attribute(self, attr: str) -> Attribute:
        """Provide attributes to the entities like switches, numbers etc."""
        _LOGGER.debug("XXX -> attr: %s", attr)
        if attr == "connection":
            return Attribute(is_on=self.connected, extra=self.conn_info)
        if attr.startswith("channel_"):
            return Attribute(min=0, max=1000, step=50, value=self.values[attr])
        if attr == "mode":
            return Attribute(options=MODES, default=self.values[attr])
        if attr == "led_on_off":
            return Attribute(is_on=self.values[attr])

    def register_update(self, attr: str, handler: Callable):
        """Register handlers for updates."""
        if attr == "connection":
            self.updates_connect.append(handler)
        else:
            self.updates_component.append(handler)

    def set_value(self, attr: str, value: int) -> None:
        """Set values received by entities such as numbers and switches."""
        _LOGGER.debug("Value %s changed to %s ", attr, str(value))
        self.values[attr] = value

    def select_option(self, attr: str, option: str) -> None:
        """Set option for select entities (e.g. mode)."""
        _LOGGER.debug("Option %s changed to %s", attr, option)
        self.values[attr] = option
        # TODO: send BLE command to set mode when protocol is known
        if attr == "mode" and option in MODES:
            mode_byte = MODES.index(option)
            # Build and send mode-change packet via self.client when format is known
            _LOGGER.debug("Mode byte would be %s", mode_byte)

    def set_led_power(self, on: bool) -> None:
        """Send BLE command to turn the LED on or off (CMD_SWITCH 0x03)."""
        # Protocol: 0x68 header, 0x03 = CMD_SWITCH, 0x00 off / 0x01 on; CRC added by client
        cmd = bytearray([0x68, 0x03, 0x01 if on else 0x00])
        self.client.send(cmd)
        self.values["led_on_off"] = on
        for handler in self.updates_component:
            handler()

    def decode_update_packet(self, data: bytearray):
        """Decode the received Fluval packet and sort into values."""
        if data[2] == 0x00:
            self.values["mode"] = MODES[0]
        elif data[2] == 0x01:
            self.values["mode"] = MODES[1]
        elif data[2] == 0x02:
            self.values["mode"] = MODES[2]

        self.values["led_on_off"] = data[3] > 0x00

        if self.values["mode"] == "manual":
            self.values["channel_1"] = (data[6] << 8) | (data[5] & 0xFF)
            self.values["channel_2"] = (data[8] << 8) | (data[7] & 0xFF)
            self.values["channel_3"] = (data[10] << 8) | (data[9] & 0xFF)
            self.values["channel_4"] = (data[12] << 8) | (data[11] & 0xFF)
        else:
            self.values["channel_1"] = 0
            self.values["channel_2"] = 0
            self.values["channel_3"] = 0
            self.values["channel_4"] = 0

        _LOGGER.debug(
            "led: "
            + str(self.values["led_on_off"])
            + " mode: "
            + str(self.values["mode"])
            + " channels: "
            + str(self.values["channel_1"])
            + " / "
            + str(self.values["channel_2"])
            + " / "
            + str(self.values["channel_3"])
            + " / "
            + str(self.values["channel_4"])
        )

        for handler in self.updates_component:
            handler()
