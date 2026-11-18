"""Native Wi-Fi fixture using the existing APK-backed light state machine."""

from typing import Any

from .device import Device
from .mqtt_client import CONF_WIFI_MAC, MqttClient, NATIVE_MQTT_PRODUCT_ID


class MqttDevice(Device):
    """AquaSky 3 product 532, with no Bluetooth discovery or GATT traffic."""

    def __init__(self, name: str, *, hass: Any, config_data: dict[str, Any]) -> None:
        super().__init__(name, hass=hass, config_data={**config_data, "product_id": NATIVE_MQTT_PRODUCT_ID})
        self.facebd = True
        self.client = MqttClient(
            hass,
            config_data[CONF_WIFI_MAC],
            self.set_connected,
            self.decode_update_packet,
            self._initial_state_complete,
        )
        self.conn_info["transport"] = "local_mqtt"
        self.conn_info["wifi_mac"] = config_data[CONF_WIFI_MAC]

    def attribute(self, attr):
        if attr == "connection":
            return {"is_on": self.connected, "extra": {"transport": "local_mqtt"}}
        return super().attribute(attr)

    def set_connected(self, connected: bool):
        """MQTT availability is live readback, not a BLE advertising grace timer."""
        self.connected = connected
        if connected:
            self.touch_seen(notify=False)
        else:
            self._clock_synced = False
            self._clock_sync_started = False
        for handler in self.updates_connect:
            handler()
        for handler in self.updates_component:
            handler()

    async def _async_ensure_client(self) -> bool:
        return self.client is not None

    def _uses_wifi_protocol(self) -> bool:
        return True

    def sensors(self) -> list[str]:
        # MQTT does not provide a Bluetooth RSSI or Bluetooth proxy source.
        return ["last_seen"]

    def is_reachable(self) -> bool:
        return self.connected
