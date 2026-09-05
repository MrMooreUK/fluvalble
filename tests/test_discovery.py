"""Tests for Fluval Bluetooth discovery helpers."""

from unittest.mock import MagicMock

import pytest

from custom_components.fluvalble.core.discovery import (
    CONF_MODEL,
    CONF_PRODUCT_ID,
    CONF_SERVICE_DATA,
    CONF_SERVICE_UUIDS,
    detect_model,
    discovery_metadata,
    is_likely_fluval,
)
from custom_components.fluvalble.core.products import PRODUCTS


def _advertisement(service_uuids=None, service_data=None, manufacturer_data=None):
    adv = MagicMock()
    adv.service_uuids = service_uuids or []
    adv.service_data = service_data or {}
    adv.manufacturer_data = manufacturer_data or {}
    return adv


@pytest.mark.parametrize(
    "name",
    [
        "Fluval",
        "Fluval Pump",
        "AquaSky3.0_2F3176",
        "Plant 3.0_AABBCC",
        "Plant Nano_123",
        "PlantPro_AABBCC",
        "Plant Pro 4.0_AABBCC",
        "Marine 3.0_AABBCC",
        "Reef_1234",
    ],
)
def test_name_alone_never_qualifies_a_light(name):
    assert not is_likely_fluval(name)


def test_facebd_service_uuid_alone_is_not_product_identity():
    adv = _advertisement(service_uuids=["facebd00-7261-6262-6974-696f74626c65"])

    assert not is_likely_fluval(None, adv)


def test_classic_service_uuid_alone_is_not_fluval():
    adv = _advertisement(service_uuids=["00001000-0000-1000-8000-00805f9b34fb"])

    assert not is_likely_fluval(None, adv)


def test_classic_service_uuid_with_fluval_manufacturer_data_is_likely_fluval():
    adv = _advertisement(
        service_uuids=["00001000-0000-1000-8000-00805f9b34fb"],
        manufacturer_data={12592: b"480103"},
    )

    assert is_likely_fluval(None, adv)


def test_classic_service_uuid_rejects_unknown_product_payload():
    adv = _advertisement(
        service_uuids=["00001000-0000-1000-8000-00805f9b34fb"],
        manufacturer_data={12592: b"01unknown"},
    )

    assert not is_likely_fluval(None, adv)


def test_classic_service_uuid_accepts_all_apk_product_prefixes():
    service = ["00001000-0000-1000-8000-00805f9b34fb"]

    assert is_likely_fluval(None, _advertisement(service_uuids=service, manufacturer_data={12848: b"140103"}))
    assert is_likely_fluval(None, _advertisement(service_uuids=service, manufacturer_data={12599: b"810103"}))


def test_mesh_service_uuid_alone_is_not_fluval():
    """fff0 is common on many BLE mesh devices — must not prompt discovery alone."""
    adv = _advertisement(service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"])

    assert not is_likely_fluval(None, adv)
    assert not is_likely_fluval("Generic Mesh Light", adv)


def test_mesh_service_uuid_requires_apk_known_binary_product():
    service = ["0000fff0-0000-1000-8000-00805f9b34fb"]
    known = _advertisement(service_uuids=service, manufacturer_data={65535: b"\x00" * 8 + b"\x02\x21"})
    unknown = _advertisement(service_uuids=service, manufacturer_data={65535: b"\x00" * 8 + b"\xff\xfe"})

    assert is_likely_fluval(None, known)
    assert not is_likely_fluval(None, unknown)


def test_mesh_with_fluval_name_still_requires_apk_product_id():
    adv = _advertisement(service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"])

    assert not is_likely_fluval("Fluval Mesh_ABCD", adv)


@pytest.mark.parametrize("product_id", PRODUCTS)
def test_every_apk_product_qualifies_from_classic_advertisement(product_id):
    encoded = f"{product_id:04X}".encode("ascii")
    company_id = int.from_bytes(encoded[:2], "little")
    adv = _advertisement(manufacturer_data={company_id: encoded[2:] + b"0103"})

    assert is_likely_fluval("Misleading device name", adv)


@pytest.mark.parametrize("product_id", PRODUCTS)
def test_every_apk_product_qualifies_from_binary_advertisement(product_id):
    adv = _advertisement(manufacturer_data={65535: b"\x00" * 8 + product_id.to_bytes(2, "big")})

    assert is_likely_fluval("Misleading device name", adv)


def test_detect_model_plant_not_aquasky():
    assert detect_model("Plant 3.0_AABBCC", None) == "Plant 3.0 Bluetooth LED"


def test_detect_model_plant_nano():
    assert detect_model("Plant Nano_123", None) == "Plant Nano Bluetooth LED"


def test_detect_model_plant_pro_and_plant_4():
    assert detect_model("PlantPro_AABBCC", None) == "Fluval Plant PRO LED"
    assert detect_model("Plant Pro 4.0_AABBCC", None) == "Fluval Plant PRO LED"
    assert detect_model("Plant 4.0_AABBCC", None) == "Fluval Plant 4.0 LED"


def test_detect_model_from_aquasky_name():
    assert detect_model("AquaSky3.0_2F3176", None) == "AquaSky 3.0 Bluetooth LED"


def test_detect_model_aquasky_2():
    assert detect_model("AquaSky2.0_ABCD", None) == "AquaSky 2.0 Bluetooth LED"


def test_detect_model_uses_apk_product_id_before_local_name():
    # BLE splits ASCII "0148 0103" into company ID 0x3130 and payload
    # "48 0103". Product 0x0148 is Aquasky 750mm; 0103 is firmware.
    adv = _advertisement(manufacturer_data={12592: b"480103"})

    assert detect_model("AquaSky2.0_ABCD", adv) == "Aquasky 750mm"


def test_discovery_metadata_stores_protocol_context():
    adv = _advertisement(
        service_uuids=["facebd00-7261-6262-6974-696f74626c65"],
        service_data={"facebd00": b"\x01\x02"},
    )

    metadata = discovery_metadata("AquaSky3.0_2F3176", adv)

    assert metadata[CONF_MODEL] == "AquaSky 3.0 Bluetooth LED"
    assert metadata[CONF_SERVICE_UUIDS] == ["facebd00-7261-6262-6974-696f74626c65"]
    assert metadata[CONF_SERVICE_DATA] == {"facebd00": "0102"}


def test_discovery_metadata_stores_reconstructed_product_id():
    adv = _advertisement(manufacturer_data={12592: b"480103"})

    metadata = discovery_metadata("AquaSky2.0_ABCD", adv)

    assert metadata[CONF_PRODUCT_ID] == 328
    assert metadata[CONF_MODEL] == "Aquasky 750mm"
