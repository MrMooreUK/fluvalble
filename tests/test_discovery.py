"""Tests for Fluval Bluetooth discovery helpers."""

from unittest.mock import MagicMock

from custom_components.fluvalble.core.discovery import (
    CONF_MODEL,
    CONF_SERVICE_DATA,
    CONF_SERVICE_UUIDS,
    detect_model,
    discovery_metadata,
    is_likely_fluval,
)


def _advertisement(service_uuids=None, service_data=None, manufacturer_data=None):
    adv = MagicMock()
    adv.service_uuids = service_uuids or []
    adv.service_data = service_data or {}
    adv.manufacturer_data = manufacturer_data or {}
    return adv


def test_aquasky_name_is_likely_fluval():
    assert is_likely_fluval("AquaSky3.0_2F3176")


def test_facebd_service_uuid_is_likely_fluval():
    adv = _advertisement(service_uuids=["facebd00-7261-6262-6974-696f74626c65"])

    assert is_likely_fluval(None, adv)


def test_detect_model_from_aquasky_name():
    assert detect_model("AquaSky3.0_2F3176", None) == "AquaSky Bluetooth LED"


def test_discovery_metadata_stores_protocol_context():
    adv = _advertisement(
        service_uuids=["facebd00-7261-6262-6974-696f74626c65"],
        service_data={"facebd00": b"\x01\x02"},
    )

    metadata = discovery_metadata("AquaSky3.0_2F3176", adv)

    assert metadata[CONF_MODEL] == "AquaSky Bluetooth LED"
    assert metadata[CONF_SERVICE_UUIDS] == ["facebd00-7261-6262-6974-696f74626c65"]
    assert metadata[CONF_SERVICE_DATA] == {"facebd00": "0102"}
