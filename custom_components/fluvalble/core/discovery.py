"""Bluetooth discovery helpers for Fluval BLE lights."""

from __future__ import annotations

from typing import Any

from bleak import AdvertisementData

FLUVAL_NAMES = ("fluval", "aquasky", "plant 3.0", "marine 3.0")
FLUVAL_MANUFACTURER_IDS: set[int] = set()
FLUVAL_SERVICE_PREFIXES = ("0000100", "facebd")

CONF_MODEL = "model"
CONF_SERVICE_UUIDS = "service_uuids"
CONF_SERVICE_DATA = "service_data"
CONF_MANUFACTURER_DATA = "manufacturer_data"


def _data_as_hex(data: bytes | bytearray) -> str:
    """Return compact hex for storing BLE payloads in config entries."""
    return bytes(data).hex()


def _advertised_protocol_keys(advertisement: AdvertisementData) -> list[str]:
    """Return service UUIDs plus service-data UUID keys in lowercase."""
    return [key.lower() for key in (list(advertisement.service_uuids) + list(advertisement.service_data))]


def is_likely_fluval(
    name: str | None,
    advertisement: AdvertisementData | None = None,
) -> bool:
    """Return whether an advertisement looks like a Fluval LED controller."""
    lowered = (name or "").lower()
    if any(candidate in lowered for candidate in FLUVAL_NAMES):
        return True

    if advertisement is None:
        return False

    if FLUVAL_MANUFACTURER_IDS.intersection(advertisement.manufacturer_data):
        return True

    service_uuids = _advertised_protocol_keys(advertisement)
    return any(uuid.startswith(prefix) for uuid in service_uuids for prefix in FLUVAL_SERVICE_PREFIXES)


def detect_model(name: str | None, advertisement: AdvertisementData | None) -> str:
    """Infer a friendly model name from the BLE advertisement."""
    display_name = name or ""
    lowered = display_name.lower()

    if "aquasky" in lowered:
        return "AquaSky Bluetooth LED"
    if "plant" in lowered:
        return "Plant Bluetooth LED"
    if "marine" in lowered:
        return "Marine Bluetooth LED"
    if "fluval" in lowered:
        return display_name

    if advertisement and any(
        uuid.lower().startswith(prefix)
        for uuid in _advertised_protocol_keys(advertisement)
        for prefix in FLUVAL_SERVICE_PREFIXES
    ):
        return "Bluetooth LED"
    if advertisement and FLUVAL_MANUFACTURER_IDS.intersection(advertisement.manufacturer_data):
        return "Bluetooth LED"

    return "Unknown Bluetooth LED"


def discovery_metadata(name: str | None, advertisement: AdvertisementData) -> dict[str, Any]:
    """Build config-entry metadata from the latest BLE advertisement."""
    return {
        CONF_MODEL: detect_model(name, advertisement),
        CONF_SERVICE_UUIDS: list(advertisement.service_uuids),
        CONF_SERVICE_DATA: {key: _data_as_hex(value) for key, value in advertisement.service_data.items()},
        CONF_MANUFACTURER_DATA: {
            str(key): _data_as_hex(value) for key, value in advertisement.manufacturer_data.items()
        },
    }
