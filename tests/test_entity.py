"""Tests for Fluval entity unique IDs."""

from types import SimpleNamespace

from custom_components.fluvalble.core.entity import FluvalEntity


def test_unique_id_and_identifiers_are_uppercase():
    device = SimpleNamespace(
        mac="aa:bb:cc:dd:ee:ff",
        model_name="AquaSky",
        name="Test",
        entity_name=lambda attr: attr,
        register_update=lambda *_args: None,
    )

    entity = FluvalEntity(device, "rssi")

    assert entity.unique_id == "AABBCCDDEEFF_rssi"
    assert entity.device_info["identifiers"] == {("fluvalble", "AA:BB:CC:DD:EE:FF")}
    assert ("bluetooth", "AA:BB:CC:DD:EE:FF") in entity.device_info["connections"]
