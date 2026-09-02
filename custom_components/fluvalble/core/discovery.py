"""Bluetooth discovery helpers for Fluval BLE lights."""

from __future__ import annotations

import re
from typing import Any

from bleak import AdvertisementData

from .products import product_from_id, product_id_from_manufacturer_data

# Classic fixtures encode the first two ASCII product-ID characters in the
# manufacturer/company field: ``01``, ``02``, or the APK's ``71`` legacy
# remaps. Current binary advertisements use raw FFFF or FF01 company bytes.
FLUVAL_MANUFACTURER_IDS = frozenset({12592, 12599, 12848, 511, 65535})

CLASSIC_FLUVAL_SERVICE_UUIDS = frozenset(
    {
        "00001000-0000-1000-8000-00805f9b34fb",
        "00001002-0000-1000-8000-00805f9b34fb",
    }
)

FACEBD_FLUVAL_SERVICE_UUIDS = frozenset(
    {
        "facebd00-7261-6262-6974-696f74626c65",
        "facebd00-0000-1000-8000-00805f9b34fb",
    }
)

SPP_FLUVAL_SERVICE_UUIDS = frozenset({"0000fff0-0000-1000-8000-00805f9b34fb"})

# Exact Fluval GATT service UUIDs. FFF0 remains product-gated below because it
# is common on unrelated BLE devices and must never qualify on its own.
FLUVAL_SERVICE_UUIDS = CLASSIC_FLUVAL_SERVICE_UUIDS | FACEBD_FLUVAL_SERVICE_UUIDS | SPP_FLUVAL_SERVICE_UUIDS

# Name tokens that are Fluval-branded on their own.
_FLUVAL_BRAND_NAMES = ("fluval", "aquasky")

# Plant/Marine/Reef Fluval advertisements look like "Plant 3.0_AABB", not
# arbitrary "plant sensor" / "marine radio" devices. Require a Fluval-style
# suffix (version, Nano, or underscore/hyphen serial).
_SERIES_NAME_RE = re.compile(
    r"^(plant|marine|reef)"
    r"(?:"
    r"\s*nano|"
    r"\s*(?:pro|[234](?:\.0)?)|"
    r"[_\-]"
    r").+",
    re.IGNORECASE,
)

CONF_MODEL = "model"
CONF_SERVICE_UUIDS = "service_uuids"
CONF_SERVICE_DATA = "service_data"
CONF_MANUFACTURER_DATA = "manufacturer_data"
CONF_PRODUCT_ID = "product_id"


def _data_as_hex(data: bytes | bytearray) -> str:
    """Return compact hex for storing BLE payloads in config entries."""
    return bytes(data).hex()


def _advertised_protocol_keys(advertisement: AdvertisementData) -> list[str]:
    """Return service UUIDs plus service-data UUID keys in lowercase."""
    return [str(key).lower() for key in (list(advertisement.service_uuids) + list(advertisement.service_data))]


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


def has_fluval_manufacturer_data(advertisement: AdvertisementData | None) -> bool:
    """Return whether the advertisement exposes Fluval manufacturer data."""
    if advertisement is None:
        return False
    return bool(FLUVAL_MANUFACTURER_IDS.intersection(advertisement.manufacturer_data))


def has_fluval_service_uuid(advertisement: AdvertisementData | None) -> bool:
    """Return whether a known Fluval service UUID is advertised."""
    if advertisement is None:
        return False
    keys = _advertised_protocol_keys(advertisement)
    # FACEBD UUID variants all start with facebd and are specific enough to
    # identify current Fluval advertisements on their own.
    if any(key in FACEBD_FLUVAL_SERVICE_UUIDS or key.startswith("facebd") for key in keys):
        return True
    # Classic and FFF0 UUIDs are not unique to Fluval; require a manufacturer
    # payload that decodes to an APK-known product ID before prompting.
    if any(key in CLASSIC_FLUVAL_SERVICE_UUIDS | SPP_FLUVAL_SERVICE_UUIDS for key in keys):
        return (
            has_fluval_manufacturer_data(advertisement)
            and product_id_from_manufacturer_data(advertisement.manufacturer_data) is not None
        )
    return False


def name_looks_fluval(name: str | None) -> bool:
    """Return whether a BLE local name matches Fluval light naming."""
    lowered = (name or "").strip().lower()
    if not lowered or lowered == "unknown":
        return False
    if any(token in lowered for token in _FLUVAL_BRAND_NAMES):
        return True
    # Require Fluval-style series names (Plant 3.0_… / Marine_…), not bare "plant".
    if _SERIES_NAME_RE.match(lowered):
        return True
    return False


def is_likely_fluval(
    name: str | None,
    advertisement: AdvertisementData | None = None,
) -> bool:
    """Return whether an advertisement looks like a Fluval LED controller.

    Strict on purpose: Home Assistant discovery prompts fire for every
    matcher hit. Generic name substrings (plant/marine) and common UUIDs
    (fff0 mesh) must not qualify alone.
    """
    if name_looks_fluval(name):
        return True
    return has_fluval_service_uuid(advertisement)


def detect_model(name: str | None, advertisement: AdvertisementData | None) -> str:
    """Return the APK product model, falling back to name/protocol hints."""
    display_name = name or ""
    lowered = display_name.lower()
    facebd = has_facebd_advertisement(advertisement)

    if advertisement is not None:
        product_id = product_id_from_manufacturer_data(advertisement.manufacturer_data)
        product = product_from_id(product_id)
        if product is not None and product.model is not None:
            return product.model

    if "plant" in lowered and name_looks_fluval(display_name):
        if "pro" in lowered:
            return "Fluval Plant PRO LED"
        if "nano" in lowered:
            return "Plant Nano Bluetooth LED"
        if "4.0" in lowered or "4_" in lowered:
            return "Fluval Plant 4.0 LED"
        if "3.0" in lowered or "3_" in lowered:
            return "Plant 3.0 Bluetooth LED"
        return "Plant Bluetooth LED"

    if "marine" in lowered and name_looks_fluval(display_name):
        if "3.0" in lowered or "3_" in lowered:
            return "Marine 3.0 Bluetooth LED"
        return "Marine Bluetooth LED"

    if "reef" in lowered and name_looks_fluval(display_name):
        return "Reef Bluetooth LED"

    if "aquasky" in lowered:
        if facebd or "3.0" in lowered or "3_" in lowered:
            return "AquaSky 3.0 Bluetooth LED"
        if "2.0" in lowered or "2_" in lowered:
            return "AquaSky 2.0 Bluetooth LED"
        return "AquaSky Bluetooth LED"

    if "fluval" in lowered:
        return display_name

    if has_fluval_service_uuid(advertisement):
        if facebd:
            return "AquaSky 3.0 Bluetooth LED"
        if has_mesh_advertisement(advertisement) and name_looks_fluval(display_name):
            return "Fluval Mesh Bluetooth LED"
        return "Bluetooth LED"

    return "Unknown Bluetooth LED"


def discovery_metadata(name: str | None, advertisement: AdvertisementData) -> dict[str, Any]:
    """Build config-entry metadata from the latest BLE advertisement."""
    metadata = {
        CONF_MODEL: detect_model(name, advertisement),
        CONF_SERVICE_UUIDS: list(advertisement.service_uuids),
        CONF_SERVICE_DATA: {key: _data_as_hex(value) for key, value in advertisement.service_data.items()},
        CONF_MANUFACTURER_DATA: {
            str(key): _data_as_hex(value) for key, value in advertisement.manufacturer_data.items()
        },
    }
    if (product_id := product_id_from_manufacturer_data(advertisement.manufacturer_data)) is not None:
        metadata[CONF_PRODUCT_ID] = product_id
    return metadata
