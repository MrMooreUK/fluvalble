"""Tests for Home Assistant entity platform glue."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from homeassistant.components.light import ATTR_BRIGHTNESS, ATTR_EFFECT, ATTR_RGBW_COLOR

from custom_components.fluvalble import binary_sensor, button, light, select, sensor, switch
from custom_components.fluvalble.core.device import Device


def _make_device():
    device = Device(
        "AquaSky3.0_Test",
        config_data={
            "mac": "AA:BB:CC:DD:EE:FF",
            "model": "AquaSky Bluetooth LED",
        },
    )
    device.connected = True
    device.conn_info["rssi"] = -70
    device.conn_info["last_seen"] = datetime(2026, 1, 1, tzinfo=UTC)
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

    assert len(switch.create_entities(device)) == 1
    assert len(select.create_entities(device)) == 2
    assert len(sensor.create_entities(device)) == 3
    assert len(button.create_entities(device)) == 3
    assert len(binary_sensor.create_entities(device)) == 1
    assert len(light.create_entities(device)) == 1


def test_switch_internal_update_and_actions():
    asyncio.run(_async_test_switch_internal_update_and_actions())


async def _async_test_switch_internal_update_and_actions():
    device = _make_device()
    entity = switch.FluvalSwitch(device, "led_on_off")
    device.async_set_switch = AsyncMock(return_value=True)

    entity.internal_update()
    await entity.async_turn_off()
    await entity.async_turn_on()

    assert entity._attr_is_on is True
    assert device.async_set_switch.await_args_list[0].args == ("led_on_off", False)
    assert device.async_set_switch.await_args_list[1].args == ("led_on_off", True)


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
    diagnostics = sensor.FluvalSensor(device, "diagnostics")

    connection.internal_update()
    rssi.internal_update()
    last_seen.internal_update()
    diagnostics.internal_update()

    assert connection._attr_is_on is True
    assert rssi._attr_native_value == -70
    assert last_seen._attr_native_value == device.conn_info["last_seen"]
    assert diagnostics._attr_native_value == "ok"


def test_diagnostics_button_presses_device_collector():
    asyncio.run(_async_test_diagnostics_button_presses_device_collector())


async def _async_test_diagnostics_button_presses_device_collector():
    device = _make_device()
    device.async_collect_diagnostics = AsyncMock(return_value={"status": "ok"})
    entity = button.FluvalDiagnosticsButton(device, "refresh_diagnostics")

    await entity.async_press()

    device.async_collect_diagnostics.assert_awaited_once()


def test_channel_test_button_presses_device_test():
    asyncio.run(_async_test_channel_test_button_presses_device_test())


async def _async_test_channel_test_button_presses_device_test():
    device = _make_device()
    device.async_test_led_channels = AsyncMock(return_value=True)
    entity = button.FluvalChannelTestButton(device, "test_led_channels")

    await entity.async_press()

    device.async_test_led_channels.assert_awaited_once()


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

    switch_entity = switch.FluvalSwitch(device, "led_on_off")
    select_entity = select.FluvalSelect(device, "mode")
    light_entity = light.FluvalLight(device, "light")

    assert switch_entity._attr_available is True
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
    entity = light.FluvalLight(device, "light")

    assert entity._attr_unique_id == "AABBCCDDEEFF_light"
    assert entity._attr_device_info["identifiers"] == {("fluvalble", "AA:BB:CC:DD:EE:FF")}
    assert ("bluetooth", "AA:BB:CC:DD:EE:FF") in entity._attr_device_info["connections"]
