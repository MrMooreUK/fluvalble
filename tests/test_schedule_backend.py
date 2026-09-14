"""Tests for light actions and fixture-owned schedule readback."""

import asyncio
import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
import voluptuous as vol
from custom_components.fluvalble import (
    DOMAIN,
    FluvalRuntimeData,
    SERVICE_RECALL_MANUAL_PRESET,
    SERVICE_SAVE_MANUAL_PRESET,
    SERVICE_SET_CHANNELS,
    _register_services,
    _validate_manual_preset_slot,
    _native_schedule_readback,
    _normalize_effect_schedule,
    _async_schedule_payload,
)
from custom_components.fluvalble.core.device import Device


class _FakeHass:
    def __init__(self, device=None):
        runtime = FluvalRuntimeData(device=device)
        self.data = {DOMAIN: {"entry_1": runtime}}
        self.services = _FakeServices()


class _FakeServices:
    def __init__(self):
        self.handlers = {}
        self.schemas = {}

    def async_register(self, domain, service, handler, schema=None):
        self.handlers[(domain, service)] = handler
        self.schemas[(domain, service)] = schema


def _make_device(*, product_id=None):
    config_data = {
        "mac": "AA:BB:CC:DD:EE:FF",
        "model": "AquaSky Bluetooth LED",
    }
    if product_id is not None:
        config_data["product_id"] = product_id
    device = Device(
        "AquaSky3.0_Test",
        config_data=config_data,
    )
    device.connected = True
    return device


@pytest.mark.parametrize("slot", [1, 2, 3, 4])
def test_manual_preset_slot_validator_accepts_p1_through_p4(slot):
    assert _validate_manual_preset_slot(slot) == slot


@pytest.mark.parametrize("slot", [0, 5, True, "1"])
def test_manual_preset_slot_validator_rejects_other_values(slot):
    with pytest.raises(vol.Invalid, match="integer from 1 to 4"):
        _validate_manual_preset_slot(slot)


def test_manual_preset_services_dispatch_to_selected_device():
    asyncio.run(_async_test_manual_preset_services_dispatch_to_selected_device())


def test_set_channels_service_reports_ble_write_failure():
    asyncio.run(_async_test_set_channels_service_reports_ble_write_failure())


async def _async_test_set_channels_service_reports_ble_write_failure():
    from homeassistant.exceptions import HomeAssistantError

    device = _make_device()
    device.async_set_channels = AsyncMock(return_value=False)
    device.diagnostics["last_error"] = "BLE write failed"
    hass = _FakeHass(device)
    _register_services(hass)

    with pytest.raises(HomeAssistantError, match="BLE write failed") as raised:
        await hass.services.handlers[(DOMAIN, SERVICE_SET_CHANNELS)](
            SimpleNamespace(
                data={
                    "entry_id": "entry_1",
                    "red": 50,
                    "transition": 0,
                    "step_seconds": 0.1,
                }
            )
        )

    assert raised.value.translation_domain == DOMAIN
    assert raised.value.translation_key == "command_failed"
    assert raised.value.translation_placeholders == {"error": "BLE write failed"}
    device.async_set_channels.assert_awaited_once_with(
        {"channel_1": 50},
        transition=0,
        step_seconds=0.1,
    )


async def _async_test_manual_preset_services_dispatch_to_selected_device():
    from homeassistant.exceptions import HomeAssistantError

    device = _make_device()
    device.async_recall_manual_preset = AsyncMock(return_value=True)
    device.async_save_manual_preset = AsyncMock(return_value=True)
    hass = _FakeHass(device)
    _register_services(hass)

    await hass.services.handlers[(DOMAIN, SERVICE_RECALL_MANUAL_PRESET)](
        SimpleNamespace(data={"entry_id": "entry_1", "slot": 2})
    )
    await hass.services.handlers[(DOMAIN, SERVICE_SAVE_MANUAL_PRESET)](
        SimpleNamespace(data={"mac": "aa:bb:cc:dd:ee:ff", "slot": 3})
    )

    device.async_recall_manual_preset.assert_awaited_once_with(2)
    device.async_save_manual_preset.assert_awaited_once_with(3)

    device.async_recall_manual_preset.return_value = False
    device.diagnostics["last_error"] = "preset readback unavailable"
    with pytest.raises(HomeAssistantError, match="preset readback unavailable"):
        await hass.services.handlers[(DOMAIN, SERVICE_RECALL_MANUAL_PRESET)](
            SimpleNamespace(data={"entry_id": "entry_1", "slot": 1})
        )


def test_service_without_target_keeps_single_fixture_compatibility():
    asyncio.run(_async_test_service_without_target_keeps_single_fixture_compatibility())


async def _async_test_service_without_target_keeps_single_fixture_compatibility():
    device = _make_device()
    device.async_recall_manual_preset = AsyncMock(return_value=True)
    hass = _FakeHass(device)
    _register_services(hass)

    await hass.services.handlers[(DOMAIN, SERVICE_RECALL_MANUAL_PRESET)](SimpleNamespace(data={"slot": 4}))

    device.async_recall_manual_preset.assert_awaited_once_with(4)


def test_services_accept_home_assistant_device_targets():
    asyncio.run(_async_test_services_accept_home_assistant_device_targets())


async def _async_test_services_accept_home_assistant_device_targets():
    from unittest.mock import patch

    first = _make_device()
    second = Device(
        "Plant4.0_Test",
        config_data={"mac": "11:22:33:44:55:66", "model": "Fluval Plant 4.0 LED", "product_id": 545},
    )
    second.connected = True
    first.async_recall_manual_preset = AsyncMock(return_value=True)
    second.async_recall_manual_preset = AsyncMock(return_value=True)
    hass = _FakeHass(first)
    hass.data[DOMAIN]["entry_2"] = FluvalRuntimeData(device=second)
    registry = SimpleNamespace(
        async_get=lambda device_id: SimpleNamespace(config_entries={"entry_2"}) if device_id == "device_2" else None
    )

    with patch("custom_components.fluvalble.dr.async_get", return_value=registry, create=True):
        _register_services(hass)
        await hass.services.handlers[(DOMAIN, SERVICE_RECALL_MANUAL_PRESET)](
            SimpleNamespace(data={"device_id": "device_2", "slot": 2})
        )

    first.async_recall_manual_preset.assert_not_awaited()
    second.async_recall_manual_preset.assert_awaited_once_with(2)
    schema = hass.services.schemas[(DOMAIN, SERVICE_RECALL_MANUAL_PRESET)].schema
    assert {"device_id", "entry_id", "mac"}.issubset(schema)


def test_service_without_target_rejects_ambiguous_fixtures():
    asyncio.run(_async_test_service_without_target_rejects_ambiguous_fixtures())


async def _async_test_service_without_target_rejects_ambiguous_fixtures():
    from homeassistant.exceptions import ServiceValidationError

    first = _make_device()
    second = Device(
        "Plant4.0_Test",
        config_data={"mac": "11:22:33:44:55:66", "model": "Fluval Plant 4.0 LED", "product_id": 545},
    )
    second.connected = True
    hass = _FakeHass(first)
    hass.data[DOMAIN]["entry_2"] = FluvalRuntimeData(device=second)
    _register_services(hass)

    with pytest.raises(ServiceValidationError) as raised:
        await hass.services.handlers[(DOMAIN, SERVICE_RECALL_MANUAL_PRESET)](SimpleNamespace(data={"slot": 1}))

    assert raised.value.translation_domain == DOMAIN
    assert raised.value.translation_key == "select_one_light"
    assert raised.value.translation_placeholders is None


@pytest.mark.parametrize(
    ("registry_entry", "translation_key"),
    [
        (None, "selected_device_missing"),
        (SimpleNamespace(config_entries=set()), "device_not_managed"),
    ],
)
def test_service_device_target_errors_are_translated_validation_errors(registry_entry, translation_key):
    asyncio.run(_async_test_service_device_target_error(registry_entry, translation_key))


async def _async_test_service_device_target_error(registry_entry, translation_key):
    from unittest.mock import patch

    from homeassistant.exceptions import ServiceValidationError

    device = _make_device()
    hass = _FakeHass(device)
    registry = SimpleNamespace(async_get=lambda _device_id: registry_entry)

    with patch("custom_components.fluvalble.dr.async_get", return_value=registry, create=True):
        _register_services(hass)
        with pytest.raises(ServiceValidationError) as raised:
            await hass.services.handlers[(DOMAIN, SERVICE_RECALL_MANUAL_PRESET)](
                SimpleNamespace(data={"device_id": "missing-device", "slot": 1})
            )

    assert raised.value.translation_domain == DOMAIN
    assert raised.value.translation_key == translation_key


def test_set_channels_requires_a_channel_as_translated_validation_error():
    asyncio.run(_async_test_set_channels_requires_a_channel())


async def _async_test_set_channels_requires_a_channel():
    from homeassistant.exceptions import ServiceValidationError

    hass = _FakeHass(_make_device())
    _register_services(hass)

    with pytest.raises(ServiceValidationError) as raised:
        await hass.services.handlers[(DOMAIN, SERVICE_SET_CHANNELS)](
            SimpleNamespace(
                data={
                    "entry_id": "entry_1",
                    "transition": 0,
                    "step_seconds": 0.1,
                }
            )
        )

    assert raised.value.translation_domain == DOMAIN
    assert raised.value.translation_key == "channels_required"


def test_unloaded_light_is_a_translated_operational_error():
    asyncio.run(_async_test_unloaded_light_is_a_translated_operational_error())


async def _async_test_unloaded_light_is_a_translated_operational_error():
    from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

    hass = _FakeHass()
    _register_services(hass)

    with pytest.raises(HomeAssistantError) as raised:
        await hass.services.handlers[(DOMAIN, SERVICE_RECALL_MANUAL_PRESET)](
            SimpleNamespace(data={"entry_id": "entry_1", "slot": 1})
        )

    assert not isinstance(raised.value, ServiceValidationError)
    assert raised.value.translation_domain == DOMAIN
    assert raised.value.translation_key == "light_unavailable"


def test_service_descriptions_use_device_picker_and_fixture_language():
    source = (Path(__file__).parents[1] / "custom_components" / "fluvalble" / "services.yaml").read_text()

    assert source.count("integration: fluvalble") == 3
    assert "entry_id:" not in source
    assert "MAC address" not in source
    for internal_label in ("classic/OLD", "FACEBD", "FFF0", "SPP", "MESH", "product ID"):
        assert internal_label not in source


def test_effect_schedule_normalizes_submitted_and_fixture_shapes():
    submitted = _normalize_effect_schedule(
        [
            {
                "start_hour": 12,
                "start_minute": 5,
                "end_hour": 12,
                "end_minute": 15,
                "effect_id": 2,
                "weekdays": [True, False, True, False, False, False, False],
                "enabled": True,
            }
        ]
    )

    assert submitted == [
        {
            "start": "12:05",
            "end": "12:15",
            "effect": "Lightning",
            "weekdays": ["monday", "wednesday"],
            "enabled": True,
        }
    ]
    assert _normalize_effect_schedule([]) == []
    assert _normalize_effect_schedule([{"start": "12:00"}]) is None


def test_integration_has_no_recurring_ha_schedule_executor():
    import custom_components.fluvalble as integration

    source = inspect.getsource(integration)
    assert "async_track_time_interval" not in source
    assert "_async_run_auto_schedule" not in source


def test_fixture_schedule_readback_normalizes_protocol_shapes():
    device = _make_device()
    device.product_id = 532
    device.values.update(
        {
            "mode": "professional",
            "native_auto_schedule": {
                "sunrise": {"hour": 8, "minute": 0, "ramp": 60},
                "sunset": {"hour": 20, "minute": 30, "ramp": 45},
                "sleep": {"hour": 23, "minute": 15},
                "day_levels": [80, 70, 60, 50],
                "night_levels": [0, 5, 0, 0],
            },
            "native_pro_schedule": [
                {"time": "08:00", "levels": [10, 20, 30, 40, 50]},
                {"minute": 750, "channel_1": 1, "channel_2": 2, "channel_3": 3, "channel_4": 4},
            ],
            "native_effect_schedule": [
                {
                    "start": "12:00",
                    "end": "12:10",
                    "effect": "Lightning",
                    "weekdays": [True, False, True, False, False, False, False],
                    "enabled": True,
                }
            ],
        }
    )
    device.conn_info["service_uuids"] = ["facebd00-0000-1000-8000-00805f9b34fb"]
    device.facebd = True
    device.diagnostics.update(
        {
            "native_schedule_protocol": "facebd",
            "native_schedule_readback_at": "2026-08-31T18:00:00+00:00",
        }
    )

    readback = _native_schedule_readback(device)

    assert readback["available"] is True
    assert readback["protocol"] == "facebd"
    assert readback["spectrum_profile"] == "aquasky_current"
    assert readback["auto"] == {
        "sunrise": "08:00",
        "sunrise_ramp": 60,
        "sunset": "20:30",
        "sunset_ramp": 45,
        "sleep": "23:15",
        "day_levels": [80, 70, 60, 50],
        "night_levels": [0, 5, 0, 0],
    }
    assert readback["professional"] == [
        {
            "time": "08:00",
            "channel_1": 10,
            "channel_2": 20,
            "channel_3": 30,
            "channel_4": 40,
            "channel_5": 50,
        },
        {
            "time": "12:30",
            "channel_1": 1,
            "channel_2": 2,
            "channel_3": 3,
            "channel_4": 4,
            "channel_5": 0,
        },
    ]
    assert readback["effects"] == [
        {
            "start": "12:00",
            "end": "12:10",
            "effect": "Lightning",
            "weekdays": ["monday", "wednesday"],
            "enabled": True,
        }
    ]
    assert readback["channels"] == ["Red", "Green", "Blue", "White"]
    assert readback["effect_options"] == [
        "Thunderstorm",
        "Lightning",
        "Sun and lightning",
        "Colour cycle",
        "Mostly sunny",
        "Partly sunny",
        "Partly cloudy",
        "Mostly cloudy",
        "Full moon",
        "Half moon",
        "Crescent moon",
    ]
    assert readback["effect_readback_complete"] is True


def test_current_reef_spp_effect_readback_is_complete():
    device = _make_device(product_id=546)
    device.values["native_effect_schedule"] = [
        {
            "start": "12:00",
            "end": "12:10",
            "effect": "Lightning",
            "weekdays": [True, False, False, False, False, False, False],
            "enabled": True,
        }
    ]
    device.diagnostics["native_schedule_protocol"] = "spp"

    readback = _native_schedule_readback(device)

    assert readback["protocol"] == "spp"
    assert readback["effect_readback_complete"] is True


def test_only_everyday_control_services_are_registered():
    hass = _FakeHass(_make_device())
    _register_services(hass)
    assert {name for domain, name in hass.services.handlers if domain == DOMAIN} == {
        "set_channels",
        "recall_manual_preset",
        "save_manual_preset",
    }


def test_readback_payload_does_not_load_or_write_local_schedules():
    device = _make_device()
    device.async_refresh_state = AsyncMock(return_value=True)
    hass = _FakeHass(device)
    payload = asyncio.run(_async_schedule_payload(hass, "entry_1"))
    assert set(payload) == {"entry_id", "fixture", "refresh_ok"}
    device.async_refresh_state.assert_not_awaited()
    payload = asyncio.run(_async_schedule_payload(hass, "entry_1", refresh=True))
    device.async_refresh_state.assert_awaited_once_with()
    assert payload["refresh_ok"] is True
