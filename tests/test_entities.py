"""Tests for Home Assistant entity platform glue."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components.light import ATTR_BRIGHTNESS, ATTR_EFFECT, ATTR_RGBW_COLOR

from custom_components.fluvalble import binary_sensor, button, diagnostics, light, select, sensor, switch
from custom_components.fluvalble.core.device import Device


def _make_device():
    now = datetime.now(UTC)
    device = Device(
        "AquaSky3.0_Test",
        config_data={
            "mac": "AA:BB:CC:DD:EE:FF",
            "model": "AquaSky Bluetooth LED",
        },
    )
    device.connected = True
    device.conn_info["rssi"] = -70
    device.conn_info["rssi_updated_at"] = now
    device.conn_info["last_seen"] = now
    device.diagnostics["status"] = "ok"
    device.values.update(
        {
            "channel_1": 10,
            "channel_2": 20,
            "channel_3": 30,
            "channel_4": 40,
            "led_on_off": True,
            "mode": "manual",
        }
    )
    return device


def test_create_entities_for_platforms():
    device = _make_device()

    assert len(select.create_entities(device)) == 2
    assert len(sensor.create_entities(device)) == 2
    assert len(button.create_entities(device)) == 2
    assert len(binary_sensor.create_entities(device)) == 1
    assert len(light.create_entities(device)) == 1
    assert switch.create_entities(device) == []

    device.facebd = True
    assert len(switch.create_entities(device)) == 1


def test_identify_button_routes_to_device_command():
    async def run_test():
        device = _make_device()
        device.async_identify = AsyncMock(return_value=True)
        entity = button.FluvalIdentifyButton(device, "identify")

        await entity.async_press()

        device.async_identify.assert_awaited_once_with()

    asyncio.run(run_test())


def test_daylight_saving_switch_uses_facebd_readback_and_command():
    asyncio.run(_async_test_daylight_saving_switch_uses_facebd_readback_and_command())


async def _async_test_daylight_saving_switch_uses_facebd_readback_and_command():
    device = _make_device()
    device.facebd = True
    device.values["daylight_saving_time"] = False
    device.async_set_daylight_saving_time = AsyncMock(return_value=True)
    entity = switch.FluvalDaylightSavingSwitch(device, "daylight_saving_time")

    entity.internal_update()
    assert entity._attr_available is True
    assert entity._attr_is_on is False

    await entity.async_turn_on()
    device.async_set_daylight_saving_time.assert_awaited_once_with(True)


def test_daylight_saving_switch_waits_for_fixture_readback():
    device = _make_device()
    device.facebd = True
    entity = switch.FluvalDaylightSavingSwitch(device, "daylight_saving_time")

    entity.internal_update()

    assert entity._attr_available is False
    assert entity._attr_is_on is None


def test_select_internal_update_and_select_option():
    asyncio.run(_async_test_select_internal_update_and_select_option())


async def _async_test_select_internal_update_and_select_option():
    device = _make_device()
    entity = select.FluvalSelect(device, "mode")
    device.async_select_option = AsyncMock(return_value=True)

    entity.internal_update()
    await entity.async_select_option("automatic")

    assert "manual" in entity._attr_options
    assert entity._attr_current_option == "automatic"
    device.async_select_option.assert_awaited_once_with("mode", "automatic")


def test_schedule_mode_select_updates_home_assistant_schedule(monkeypatch):
    asyncio.run(_async_test_schedule_mode_select_updates_home_assistant_schedule(monkeypatch))


async def _async_test_schedule_mode_select_updates_home_assistant_schedule(
    monkeypatch,
):
    import custom_components.fluvalble as integration

    device = _make_device()
    device.entry_id = "entry_1"
    entity = select.FluvalSelect(device, "schedule_mode")
    hass = MagicMock()
    set_schedule_mode = AsyncMock()
    monkeypatch.setattr(select.FluvalSelect, "hass", hass, raising=False)
    monkeypatch.setattr(integration, "async_set_schedule_mode", set_schedule_mode)

    await entity.async_select_option("auto")

    set_schedule_mode.assert_awaited_once_with(hass, "entry_1", "auto")


def test_diagnostic_entities_update_from_device_attributes():
    device = _make_device()

    connection = binary_sensor.FluvalSensor(device, "connection")
    rssi = sensor.FluvalSensor(device, "rssi")
    last_seen = sensor.FluvalSensor(device, "last_seen")

    connection.internal_update()
    rssi.internal_update()
    last_seen.internal_update()

    assert connection._attr_is_on is True
    assert rssi._attr_native_value == -70
    assert rssi._attr_state_class.value == "measurement"
    assert rssi._attr_extra_state_attributes["last_advertisement"] == device.conn_info["rssi_updated_at"]
    assert last_seen._attr_native_value == device.conn_info["last_seen"]


def test_downloadable_diagnostics_redact_identifiers_but_keep_protocol_fields():
    report = diagnostics._redact_diagnostics(
        {
            "configured_mac": "AA:BB:CC:DD:EE:FF",
            "name": "PlantPro_AABBCC",
            "connection_info": {
                "mac": "AA:BB:CC:DD:EE:FF",
                "service_uuids": ["0000fff0-0000-1000-8000-00805f9b34fb"],
                "manufacturer_data": {"12592": "secret"},
            },
            "channel_count": 4,
        }
    )

    assert report["configured_mac"] == diagnostics.REDACTED
    assert report["name"] == diagnostics.REDACTED
    assert report["connection_info"]["mac"] == diagnostics.REDACTED
    assert report["connection_info"]["manufacturer_data"] == diagnostics.REDACTED
    assert report["connection_info"]["service_uuids"] == ["0000fff0-0000-1000-8000-00805f9b34fb"]
    assert report["channel_count"] == 4


def test_downloadable_diagnostics_do_not_touch_ble():
    asyncio.run(_async_test_downloadable_diagnostics_do_not_touch_ble())


async def _async_test_downloadable_diagnostics_do_not_touch_ble():
    device = _make_device()
    device.hass = None
    client = MagicMock(
        profile="classic",
        wifi_facebd=False,
        plant_pro_spp=False,
        raw_facebd=False,
        command_write_uuid="00001001-0000-1000-8000-00805f9b34fb",
        notify_uuids=["00001002-0000-1000-8000-00805f9b34fb"],
        last_error=None,
        last_write_targets=[],
        last_write_verified=True,
    )
    client.disconnect = AsyncMock()
    client.request_state = AsyncMock()
    device.client = client
    entry = SimpleNamespace(
        entry_id="private-entry-id",
        title="Kitchen Aquarium",
        unique_id="AA:BB:CC:DD:EE:FF",
        data={"mac": "AA:BB:CC:DD:EE:FF"},
        options={"active_time": 0},
        runtime_data=SimpleNamespace(device=device),
    )

    with patch(
        "custom_components.fluvalble.core.device.BleakScanner.find_device_by_address",
        new=AsyncMock(),
    ) as scanner:
        report = await diagnostics._build_report(entry)

    client.disconnect.assert_not_awaited()
    client.request_state.assert_not_awaited()
    scanner.assert_not_awaited()
    assert report["entry"]["entry_id"] == diagnostics.REDACTED
    assert report["entry"]["title"] == diagnostics.REDACTED
    assert report["entry"]["unique_id"] == diagnostics.REDACTED
    assert report["entry"]["data"]["mac"] == diagnostics.REDACTED
    assert report["model"] == device.model_name
    assert report["channel_count"] == 4


def test_light_internal_update_and_actions():
    asyncio.run(_async_test_light_internal_update_and_actions())


async def _async_test_light_internal_update_and_actions():
    device = _make_device()
    entity = light.FluvalLight(device, "light")
    device.async_apply_light_channels = AsyncMock(return_value=True)
    device.async_set_switch = AsyncMock(return_value=True)
    device.values["led_on_off"] = False

    entity.internal_update()
    await entity.async_turn_on(**{ATTR_BRIGHTNESS: 128, ATTR_RGBW_COLOR: (0, 255, 0, 0)})
    await entity.async_turn_off()

    assert entity._attr_is_on is False
    device.async_apply_light_channels.assert_awaited_once_with(
        {
            "channel_1": 0,
            "channel_2": 50,
            "channel_3": 0,
            "channel_4": 0,
        }
    )
    device.async_set_switch.assert_awaited_once_with("led_on_off", False)


def test_light_entity_handles_power_only_actions():
    asyncio.run(_async_test_light_entity_handles_power_only_actions())


async def _async_test_light_entity_handles_power_only_actions():
    device = _make_device()
    device.values["led_on_off"] = False
    device.async_set_switch = AsyncMock(return_value=True)
    entity = light.FluvalLight(device, "light")

    await entity.async_turn_on()
    await entity.async_turn_off()

    assert device.async_set_switch.await_args_list[0].args == ("led_on_off", True)
    assert device.async_set_switch.await_args_list[1].args == ("led_on_off", False)


def test_light_exposes_and_routes_classic_native_effects():
    asyncio.run(_async_test_light_exposes_and_routes_classic_native_effects())


async def _async_test_light_exposes_and_routes_classic_native_effects():
    device = _make_device()
    device.conn_info["service_uuids"] = ["00001002-0000-1000-8000-00805f9b34fb"]
    device.async_set_effect = AsyncMock(return_value=True)
    device.async_stop_effect = AsyncMock(return_value=True)
    entity = light.FluvalLight(device, "light")

    assert entity._attr_effect_list == [
        "None",
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

    await entity.async_turn_on(**{ATTR_EFFECT: "Lightning"})
    device.async_set_effect.assert_awaited_once_with("Lightning")

    await entity.async_turn_on(**{ATTR_EFFECT: "None"})
    device.async_stop_effect.assert_awaited_once()


def test_light_exposes_facebd_native_effects():
    device = _make_device()
    device.conn_info["service_uuids"] = ["facebd00-0000-1000-8000-00805f9b34fb"]
    device.facebd = True
    entity = light.FluvalLight(device, "light")

    assert entity._attr_effect_list == [
        "None",
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


def test_entity_unregisters_update_handler():
    device = _make_device()
    device.deregister_update = MagicMock()
    entity = light.FluvalLight(device, "light")

    asyncio.run(entity.async_will_remove_from_hass())

    device.deregister_update.assert_called_once_with("light", entity._update_handler)


def test_controls_remain_available_when_recently_seen_but_not_connected():
    device = _make_device()
    device.connected = False
    device.client = None
    device.conn_info["last_seen"] = datetime(2026, 1, 1, tzinfo=UTC)

    select_entity = select.FluvalSelect(device, "mode")
    light_entity = light.FluvalLight(device, "light")

    assert select_entity._attr_available is True
    assert light_entity._attr_available is True


def test_connection_changes_refresh_control_entities():
    device = _make_device()
    device.connected = False
    light.FluvalLight(device, "light")
    handler = MagicMock()
    device.updates_component.append(handler)

    device.set_connected(True)

    handler.assert_called_once()


def test_unique_id_and_identifiers_are_uppercase_for_mixed_case_mac():
    device = _make_device()
    device.address = "aa:bb:cc:dd:ee:ff"
    device.firmware_version = "14"
    entity = light.FluvalLight(device, "light")

    assert entity._attr_unique_id == "AABBCCDDEEFF_light"
    assert entity._attr_device_info["identifiers"] == {("fluvalble", "AA:BB:CC:DD:EE:FF")}
    assert ("bluetooth", "AA:BB:CC:DD:EE:FF") in entity._attr_device_info["connections"]
    assert entity._attr_device_info["sw_version"] == "14"


def test_reported_firmware_updates_standard_device_registry_info():
    import custom_components.fluvalble as integration

    device = _make_device()
    device.firmware_version = "14"
    registry_device = SimpleNamespace(id="device_1", sw_version=None)
    registry = MagicMock()
    registry.async_get_device.return_value = registry_device

    with patch.object(integration.dr, "async_get", return_value=registry, create=True):
        integration._sync_firmware_version_to_device_registry(MagicMock(), device)

    registry.async_get_device.assert_called_once_with(identifiers={("fluvalble", "AA:BB:CC:DD:EE:FF")})
    registry.async_update_device.assert_called_once_with("device_1", sw_version="14")


def test_product_identity_updates_config_entry_and_device_registry():
    import custom_components.fluvalble as integration

    device = _make_device()
    device.product_id = 328
    device.model = "Aquasky 750mm"
    entry = SimpleNamespace(data={"mac": device.mac})
    hass = MagicMock()
    registry_device = SimpleNamespace(id="device_1", model="AquaSky Bluetooth LED")
    registry = MagicMock()
    registry.async_get_device.return_value = registry_device

    with patch.object(integration.dr, "async_get", return_value=registry, create=True):
        integration._sync_product_identity(hass, entry, device)

    hass.config_entries.async_update_entry.assert_called_once_with(
        entry,
        data={"mac": device.mac, "product_id": 328, "model": "Aquasky 750mm"},
    )
    registry.async_update_device.assert_called_once_with("device_1", model="Aquasky 750mm")
