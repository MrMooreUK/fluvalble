"""Bluetooth discovery helpers for Fluval BLE lights."""

from __future__ import annotations

from typing import Any

from bleak import AdvertisementData

FLUVAL_NAMES = ("fluval", "aquasky", "plant", "marine", "reef")
FLUVAL_MANUFACTURER_IDS: set[int] = set()
FLUVAL_SERVICE_PREFIXES = ("0000100", "facebd", "0000fff0")

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


def has_facebd_advertisement(advertisement: AdvertisementData | None) -> bool:
    """Return whether the advertisement exposes a FACEBD service."""
    if advertisement is None:
        return False
    return any(uuid.startswith("facebd") for uuid in _advertised_protocol_keys(advertisement))


def has_mesh_advertisement(advertisement: AdvertisementData | None) -> bool:
    """Return whether the advertisement exposes the mesh fff0 service."""
    if advertisement is None:
        return False
    return any(uuid.startswith("0000fff0") for uuid in _advertised_protocol_keys(advertisement))


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
    facebd = has_facebd_advertisement(advertisement)

    if "plant" in lowered:
        if "nano" in lowered:
            return "Plant Nano Bluetooth LED"
        if "3.0" in lowered or "3_" in lowered:
            return "Plant 3.0 Bluetooth LED"
        return "Plant Bluetooth LED"

    if "marine" in lowered:
        if "3.0" in lowered or "3_" in lowered:
            return "Marine 3.0 Bluetooth LED"
        return "Marine Bluetooth LED"

    if "reef" in lowered:
        return "Reef Bluetooth LED"

    if "aquasky" in lowered:
        if facebd or "3.0" in lowered or "3_" in lowered:
            return "AquaSky 3.0 Bluetooth LED"
        if "2.0" in lowered or "2_" in lowered:
            return "AquaSky 2.0 Bluetooth LED"
        return "AquaSky Bluetooth LED"

    if "fluval" in lowered:
        return display_name

    if advertisement and any(
        uuid.startswith(prefix)
        for uuid in _advertised_protocol_keys(advertisement)
        for prefix in FLUVAL_SERVICE_PREFIXES
    ):
        if facebd:
            return "AquaSky 3.0 Bluetooth LED"
        if has_mesh_advertisement(advertisement):
            return "Fluval Mesh Bluetooth LED"
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
