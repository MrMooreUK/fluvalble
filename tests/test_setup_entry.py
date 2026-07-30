"""Tests for config-entry setup helpers."""

from types import SimpleNamespace

from custom_components.fluvalble import _entry_device_config
from custom_components.fluvalble.core import LAMP_PROFILE_AQUASKY, LAMP_PROFILE_PLANT


def test_entry_device_config_merges_options_over_data():
    entry = SimpleNamespace(
        data={
            "mac": "AA:BB:CC:DD:EE:FF",
            "lamp_profile": LAMP_PROFILE_PLANT,
            "model": "Configured model",
        },
        options={
            "lamp_profile": LAMP_PROFILE_AQUASKY,
            "active_time": 120,
        },
    )

    config = _entry_device_config(entry)

    assert config["mac"] == "AA:BB:CC:DD:EE:FF"
    assert config["model"] == "Configured model"
    assert config["lamp_profile"] == LAMP_PROFILE_AQUASKY
    assert config["active_time"] == 120
