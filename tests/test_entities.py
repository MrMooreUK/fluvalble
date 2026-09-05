"""Tests for Home Assistant entity platform glue."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ATTR_RGB_COLOR,
    ColorMode,
)
from homeassistant.exceptions import HomeAssistantError

from custom_components.fluvalble import (
    DOMAIN,
    FluvalRuntimeData,
    binary_sensor,
    button,
    diagnostics,
    light,
    number,
    select,
    sensor,
    switch,
)
from custom_components.fluvalble.core.device import Device


def _make_device(*, active_time: int = 120):
    now = datetime.now(UTC)
    device = Device(
        "AquaSky3.0_Test",
        config_data={
            "mac": "AA:BB:CC:DD:EE:FF",
            "model": "AquaSky Bluetooth LED",
            "product_id": 532,
        },
        active_time=active_time,
    )
    device.connected = True
    device.conn_info["rssi"] = -70
    device.conn_info["rssi_updated_at"] = now
    device.conn_info["advertisement_source"] = "Aquarium USB adapter"
    device.conn_info["advertisement_source_address"] = "00:11:22:33:44:55"
    device.conn_info["advertisement_source_type"] = "usb"
    device.conn_info["advertisement_rssi"] = -82
    device.conn_info["advertisement_updated_at"] = now
    device.conn_info["active_connection_source"] = "fish"
    device.conn_info["active_connection_source_address"] = "66:77:88:99:AA:BB"
    device.conn_info["active_connection_source_type"] = "remote"
    device.conn_info["active_connection_connected_at"] = now
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

    mode_entities = select.create_entities(device)
    assert len(mode_entities) == 1
    assert mode_entities[0].attr == "mode"
    assert len(sensor.create_entities(device)) == 4
    assert len(button.create_entities(device)) == 2
    assert len(binary_sensor.create_entities(device)) == 1
    assert len(light.create_entities(device)) == 1
    channel_entities = number.create_entities(device)
    assert [entity._attr_name for entity in channel_entities] == [
        "Red",
        "Green",
        "Blue",
        "White",
    ]
    assert switch.create_entities(device) == []

    device.facebd = True
    assert len(switch.create_entities(device)) == 1


@pytest.mark.parametrize(
    ("product_id", "expected_names"),
    [
        (532, ["Red", "Green", "Blue", "White"]),
        (305, ["Pink", "Blue", "Cold White", "White", "Warm White"]),
        (546, ["Pink", "Cyan", "Blue", "Purple", "Cold White"]),
    ],
)
def test_channel_controls_follow_apk_product_layout(product_id, expected_names):
    device = Device(
        "Fluval_Test",
        config_data={"mac": "AA:BB:CC:DD:EE:FF", "product_id": product_id},
    )
    device.connected = True
    device.conn_info["last_seen"] = datetime.now(UTC)

    entities = number.create_entities(device)

    assert [entity._attr_name for entity in entities] == expected_names
    assert all(entity._attr_native_min_value == 0 for entity in entities)
    assert all(entity._attr_native_max_value == 100 for entity in entities)
    assert all(entity._attr_native_step == 1 for entity in entities)
    assert all(entity._attr_native_unit_of_measurement == "%" for entity in entities)
    assert all(entity._attr_available for entity in entities)
    assert all(getattr(entity, "_attr_entity_category", None) is None for entity in entities)
    assert all(getattr(entity, "_attr_entity_registry_enabled_default", True) for entity in entities)


def test_channel_control_writes_exact_emitter_percentage():
    asyncio.run(_async_test_channel_control_writes_exact_emitter_percentage())


async def _async_test_channel_control_writes_exact_emitter_percentage():
    device = _make_device()
    device.async_set_value = AsyncMock(return_value=True)
    entity = number.FluvalChannelNumber(device, "channel_2")

    await entity.async_set_native_value(37)

    device.async_set_value.assert_awaited_once_with("channel_2", 37)


def test_channel_control_refreshes_light_with_new_best_fit_colour():
    asyncio.run(_async_test_channel_control_refreshes_light_with_new_best_fit_colour())


async def _async_test_channel_control_refreshes_light_with_new_best_fit_colour():
    device = _make_device()
    device.values.update(
        {
            "channel_1": 100,
            "channel_2": 0,
            "channel_3": 0,
            "channel_4": 0,
            "mode": "manual",
            "led_on_off": True,
        }
    )
    device._async_prepare_command = AsyncMock(return_value=True)
    device._async_send_channel_state = AsyncMock(return_value=True)
    light_entity = light.FluvalLight(device, "light")
    channel_entity = number.FluvalChannelNumber(device, "channel_2")
    device.updates_component.extend([light_entity.internal_update, channel_entity.internal_update])
    original_rgb = light_entity._attr_rgb_color

    await channel_entity.async_set_native_value(100)

    assert channel_entity._attr_native_value == 100
    assert light_entity._attr_rgb_color == device.aquasky_rgb_255()
    assert light_entity._attr_rgb_color != original_rgb
    device._async_send_channel_state.assert_awaited_once()


def test_channel_control_surfaces_ble_command_failure():
    asyncio.run(_async_test_channel_control_surfaces_ble_command_failure())


async def _async_test_channel_control_surfaces_ble_command_failure():
    device = _make_device()
    device.client = SimpleNamespace(last_error="fixture unavailable", command_write_uuid=None)
    device.async_set_value = AsyncMock(return_value=False)
    entity = number.FluvalChannelNumber(device, "channel_1")

    with pytest.raises(HomeAssistantError, match="fixture unavailable"):
        await entity.async_set_native_value(25)


def test_empty_effect_list_uses_typed_empty_feature_flag():
    """HA 2026.9 requires supported_features to remain an IntFlag value."""
    device = Device(
        "Fluval Plant 3.0",
        config_data={
            "mac": "AA:BB:CC:DD:EE:FF",
            "product_id": 305,
        },
    )

    entity = light.create_entities(device)[0]

    assert entity._attr_supported_color_modes == {ColorMode.RGB}
    assert entity._attr_supported_features == light.LightEntityFeature(0)
    assert isinstance(entity._attr_supported_features, light.LightEntityFeature)


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


def test_diagnostic_entities_update_from_device_attributes():
    device = _make_device()

    connection = binary_sensor.FluvalSensor(device, "connection")
    rssi = sensor.FluvalSensor(device, "rssi")
    last_seen = sensor.FluvalSensor(device, "last_seen")
    connection_source = sensor.FluvalSensor(device, "active_connection_source")
    connection_mode = sensor.FluvalSensor(device, "connection_mode")

    assert rssi._attr_entity_registry_enabled_default is True
    assert last_seen._attr_entity_registry_enabled_default is True

    connection.internal_update()
    rssi.internal_update()
    last_seen.internal_update()
    connection_source.internal_update()
    connection_mode.internal_update()

    assert connection._attr_is_on is True
    assert rssi._attr_available is True
    assert rssi._attr_native_value == -70
    assert rssi._attr_state_class.value == "measurement"
    assert rssi._attr_extra_state_attributes == {
        "last_updated": device.conn_info["rssi_updated_at"],
    }
    assert last_seen._attr_native_value == device.conn_info["last_seen"]
    assert connection_source._attr_native_value == "fish"
    assert connection_source._attr_icon == "mdi:bluetooth"
    assert "source_address" not in connection_source._attr_extra_state_attributes
    assert connection_source._attr_extra_state_attributes["source_type"] == "remote"
    assert connection_source._attr_extra_state_attributes["gatt_connected"] is True
    assert connection_mode._attr_native_value == "120 seconds"

    device.connected = False
    rssi.internal_update()
    assert rssi._attr_available is True
    assert rssi._attr_native_value == -70


def test_persistent_connection_mode_hides_stale_rssi():
    device = _make_device(active_time=0)

    connection_mode = sensor.FluvalSensor(device, "connection_mode")
    rssi = sensor.FluvalSensor(device, "rssi")
    connected_since = sensor.FluvalSensor(device, "last_seen")

    assert connection_mode._attr_native_value == "Persistent"
    assert rssi._attr_entity_registry_enabled_default is False
    assert connected_since._attr_entity_registry_enabled_default is False
    assert rssi._attr_available is False
    assert rssi._attr_native_value is None
    assert rssi._attr_extra_state_attributes == {
        "last_updated": device.conn_info["rssi_updated_at"],
    }
    assert connected_since._attr_translation_key == "connected_since"
    assert connected_since._attr_native_value == device.conn_info["active_connection_connected_at"]

    device.connected = False
    connected_since.internal_update()
    assert connected_since._attr_available is False
    assert connected_since._attr_native_value is None


def test_connection_mode_uses_singular_second():
    device = _make_device(active_time=1)

    connection_mode = sensor.FluvalSensor(device, "connection_mode")
    last_seen = sensor.FluvalSensor(device, "last_seen")

    assert connection_mode._attr_native_value == "1 second"
    assert last_seen._attr_translation_key == "last_seen"
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
    assert report["active_connection"]["source"] == diagnostics.REDACTED
    assert report["active_connection"]["source_name"] == diagnostics.REDACTED
    assert report["active_connection"]["source_type"] == "remote"
    assert report["latest_advertisement"]["source"] == diagnostics.REDACTED
    assert report["latest_advertisement"]["source_name"] == diagnostics.REDACTED
    assert report["active_connection"]["rssi"] == -70
    assert report["latest_advertisement"]["rssi"] == -82


def test_diagnostics_support_legacy_runtime_storage():
    asyncio.run(_async_test_diagnostics_support_legacy_runtime_storage())


async def _async_test_diagnostics_support_legacy_runtime_storage():
    fluval = SimpleNamespace(async_collect_diagnostics=AsyncMock(return_value={"status": "ok"}))
    entry = SimpleNamespace(
        entry_id="private-entry-id",
        title="Kitchen Aquarium",
        unique_id="AA:BB:CC:DD:EE:FF",
        data={"mac": "AA:BB:CC:DD:EE:FF"},
        options={},
    )
    hass = SimpleNamespace(data={DOMAIN: {entry.entry_id: FluvalRuntimeData(device=fluval)}})

    report = await diagnostics._build_report(entry, hass)

    fluval.async_collect_diagnostics.assert_awaited_once_with()
    assert report["status"] == "ok"


def test_light_internal_update_and_actions():
    asyncio.run(_async_test_light_internal_update_and_actions())


async def _async_test_light_internal_update_and_actions():
    device = _make_device()
    entity = light.FluvalLight(device, "light")
    device.async_apply_light_channels = AsyncMock(return_value=True)
    device.async_set_switch = AsyncMock(return_value=True)
    device.values["led_on_off"] = False

    entity.internal_update()
    await entity.async_turn_on(**{ATTR_BRIGHTNESS: 128, ATTR_RGB_COLOR: (0, 255, 0)})
    await entity.async_turn_off()

    assert entity._attr_is_on is False
    device.async_apply_light_channels.assert_awaited_once_with(
        {
            "channel_1": 31,
            "channel_2": 50,
            "channel_3": 0,
            "channel_4": 0,
        }
    )
    device.async_set_switch.assert_awaited_once_with("led_on_off", False)


def test_aquasky_mauve_does_not_enable_white_channel():
    asyncio.run(_async_test_aquasky_mauve_does_not_enable_white_channel())


async def _async_test_aquasky_mauve_does_not_enable_white_channel():
    device = _make_device()
    entity = light.FluvalLight(device, "light")
    device.async_apply_light_channels = AsyncMock(return_value=True)

    await entity.async_turn_on(**{ATTR_BRIGHTNESS: 255, ATTR_RGB_COLOR: (215, 150, 255)})

    device.async_apply_light_channels.assert_awaited_once_with(
        {
            "channel_1": 90,
            "channel_2": 32,
            "channel_3": 100,
            "channel_4": 0,
        }
    )


def test_aquasky_neutral_rgb_uses_only_white_channel():
    asyncio.run(_async_test_aquasky_neutral_rgb_uses_only_white_channel())


async def _async_test_aquasky_neutral_rgb_uses_only_white_channel():
    device = _make_device()
    entity = light.FluvalLight(device, "light")
    device.async_apply_light_channels = AsyncMock(return_value=True)

    await entity.async_turn_on(**{ATTR_BRIGHTNESS: 128, ATTR_RGB_COLOR: (255, 255, 255)})

    device.async_apply_light_channels.assert_awaited_once_with(
        {
            "channel_1": 0,
            "channel_2": 0,
            "channel_3": 0,
            "channel_4": 50,
        }
    )
    assert device.light_brightness_255() == 128
    assert entity._attr_supported_color_modes == {ColorMode.RGB}
    assert entity._attr_color_mode is ColorMode.RGB
    assert entity._attr_rgb_color == (255, 255, 255)


def test_marine_light_uses_standard_rgb_control_for_all_five_channels():
    asyncio.run(_async_test_marine_light_uses_standard_rgb_control_for_all_five_channels())


async def _async_test_marine_light_uses_standard_rgb_control_for_all_five_channels():
    device = Device(
        "Reef4_Test",
        config_data={
            "mac": "AA:BB:CC:DD:EE:FF",
            "model": "Bluetooth LED",
            "product_id": 546,
        },
    )
    device.connected = True
    device.async_apply_light_channels = AsyncMock(return_value=True)
    entity = light.FluvalLight(device, "light")

    assert entity._attr_color_mode == ColorMode.RGB
    assert entity._attr_supported_color_modes == {ColorMode.RGB}

    await entity.async_turn_on(**{ATTR_BRIGHTNESS: 255, ATTR_RGB_COLOR: (255, 0, 255)})

    device.async_apply_light_channels.assert_awaited_once_with(
        {
            "channel_1": 100,
            "channel_2": 0,
            "channel_3": 0,
            "channel_4": 0,
            "channel_5": 10,
        }
    )


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


def test_normal_light_and_mode_controls_stop_active_previews_first():
    asyncio.run(_async_test_normal_light_and_mode_controls_stop_active_previews_first())


async def _async_test_normal_light_and_mode_controls_stop_active_previews_first():
    device = _make_device()
    device.values["led_on_off"] = True
    events = []

    async def stop_preview(*, restore=True):
        events.append(("stop_preview", restore))
        return True

    async def apply_channels(_channels):
        events.append(("apply_channels", None))
        return True

    async def set_switch(_attr, _value):
        events.append(("set_switch", None))
        return True

    async def set_option(_attr, _option):
        events.append(("set_option", None))
        return True

    device.async_stop_preview = AsyncMock(side_effect=stop_preview)
    device.async_apply_light_channels = AsyncMock(side_effect=apply_channels)
    device.async_set_switch = AsyncMock(side_effect=set_switch)
    device.async_select_option = AsyncMock(side_effect=set_option)
    light_entity = light.FluvalLight(device, "light")
    mode_entity = select.FluvalSelect(device, "mode")

    await light_entity.async_turn_on(**{ATTR_RGB_COLOR: (0, 255, 0)})
    device.async_stop_preview.assert_awaited_once_with(restore=False)
    assert events == [("stop_preview", False), ("apply_channels", None)]

    device.async_stop_preview.reset_mock()
    events.clear()
    await light_entity.async_turn_off()
    device.async_stop_preview.assert_awaited_once_with()
    assert events == [("stop_preview", True), ("set_switch", None)]

    device.async_stop_preview.reset_mock()
    events.clear()
    await mode_entity.async_select_option("automatic")
    device.async_stop_preview.assert_awaited_once_with(restore=False)
    device.async_select_option.assert_awaited_once_with("mode", "automatic")
    assert events == [("stop_preview", False), ("set_option", None)]


def test_preview_stop_and_replacement_entity_command_are_atomic():
    asyncio.run(_async_test_preview_stop_and_replacement_entity_command_are_atomic())


async def _async_test_preview_stop_and_replacement_entity_command_are_atomic():
    device = _make_device()
    device.values["led_on_off"] = True
    events = []
    first_stop_started = asyncio.Event()
    release_first_stop = asyncio.Event()
    stop_calls = 0

    async def stop_preview(*, restore=True):
        nonlocal stop_calls
        stop_calls += 1
        events.append(("stop_preview", restore))
        if stop_calls == 1:
            first_stop_started.set()
            await release_first_stop.wait()
        return True

    async def set_switch(_attr, _value):
        events.append(("set_switch", None))
        return True

    async def set_option(_attr, _option):
        events.append(("set_option", None))
        return True

    device.async_stop_preview = AsyncMock(side_effect=stop_preview)
    device.async_set_switch = AsyncMock(side_effect=set_switch)
    device.async_select_option = AsyncMock(side_effect=set_option)
    light_entity = light.FluvalLight(device, "light")
    mode_entity = select.FluvalSelect(device, "mode")

    power_task = asyncio.create_task(light_entity.async_turn_off())
    await first_stop_started.wait()
    mode_task = asyncio.create_task(mode_entity.async_select_option("automatic"))
    await asyncio.sleep(0)

    assert events == [("stop_preview", True)]
    assert not mode_task.done()

    release_first_stop.set()
    await power_task
    await mode_task
    assert events == [
        ("stop_preview", True),
        ("set_switch", None),
        ("stop_preview", False),
        ("set_option", None),
    ]


def test_turn_off_is_attempted_when_preview_stop_fails():
    asyncio.run(_async_test_turn_off_is_attempted_when_preview_stop_fails())


async def _async_test_turn_off_is_attempted_when_preview_stop_fails():
    device = _make_device()
    device.client = SimpleNamespace(
        last_error="preview stop failed",
        command_write_uuid=None,
    )
    device.async_stop_preview = AsyncMock(return_value=False)
    device.async_set_switch = AsyncMock(return_value=True)
    entity = light.FluvalLight(device, "light")

    with pytest.raises(HomeAssistantError, match="preview stop failed"):
        await entity.async_turn_off()

    device.async_stop_preview.assert_awaited_once_with()
    device.async_set_switch.assert_awaited_once_with("led_on_off", False)


def test_turn_on_does_not_write_over_a_preview_that_failed_to_stop():
    asyncio.run(_async_test_turn_on_does_not_write_over_a_preview_that_failed_to_stop())


async def _async_test_turn_on_does_not_write_over_a_preview_that_failed_to_stop():
    device = _make_device()
    device.client = SimpleNamespace(
        last_error="preview stop failed",
        command_write_uuid=None,
    )
    device.async_stop_preview = AsyncMock(return_value=False)
    device.async_apply_light_channels = AsyncMock(return_value=True)
    entity = light.FluvalLight(device, "light")

    with pytest.raises(HomeAssistantError, match="preview stop failed"):
        await entity.async_turn_on(**{ATTR_RGB_COLOR: (0, 255, 0)})

    device.async_stop_preview.assert_awaited_once_with(restore=False)
    device.async_apply_light_channels.assert_not_awaited()


def test_light_entity_surfaces_ble_command_failures():
    asyncio.run(_async_test_light_entity_surfaces_ble_command_failures())


async def _async_test_light_entity_surfaces_ble_command_failures():
    device = _make_device()
    device.client = SimpleNamespace(
        last_error="connect failed: fixture unavailable",
        command_write_uuid=None,
    )
    device.async_set_switch = AsyncMock(return_value=False)
    entity = light.FluvalLight(device, "light")

    with pytest.raises(HomeAssistantError, match="connect failed: fixture unavailable") as raised:
        await entity.async_turn_off()

    assert raised.value.translation_domain == "fluvalble"
    assert raised.value.translation_key == "command_failed"
    assert raised.value.translation_placeholders == {"error": "connect failed: fixture unavailable"}


def test_non_light_entities_surface_ble_command_failures():
    asyncio.run(_async_test_non_light_entities_surface_ble_command_failures())


async def _async_test_non_light_entities_surface_ble_command_failures():
    device = _make_device()
    device.client = SimpleNamespace(
        last_error="write failed: fixture unavailable",
        command_write_uuid=None,
    )
    device.facebd = True
    device.values["daylight_saving_time"] = False
    device.async_select_option = AsyncMock(return_value=False)
    device.async_set_daylight_saving_time = AsyncMock(return_value=False)
    device.async_identify = AsyncMock(return_value=False)
    device.async_sync_clock = AsyncMock(return_value=False)

    actions = (
        select.FluvalSelect(device, "mode").async_select_option("automatic"),
        switch.FluvalDaylightSavingSwitch(
            device,
            "daylight_saving_time",
        ).async_turn_on(),
        button.FluvalIdentifyButton(device, "identify").async_press(),
        button.FluvalSyncClockButton(device, "sync_clock").async_press(),
    )

    for action in actions:
        with pytest.raises(HomeAssistantError, match="write failed: fixture unavailable") as raised:
            await action
        assert raised.value.translation_domain == "fluvalble"
        assert raised.value.translation_key == "command_failed"
        assert raised.value.translation_placeholders == {"error": "write failed: fixture unavailable"}


def test_light_exposes_and_routes_classic_native_effects():
    asyncio.run(_async_test_light_exposes_and_routes_classic_native_effects())


async def _async_test_light_exposes_and_routes_classic_native_effects():
    device = _make_device()
    device.conn_info["service_uuids"] = ["00001002-0000-1000-8000-00805f9b34fb"]
    device.async_set_effect = AsyncMock(return_value=True)
    device.async_stop_effect = AsyncMock(return_value=True)
    entity = light.FluvalLight(device, "light")

    assert entity._attr_effect_list == [
        "off",
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

    await entity.async_turn_on(**{ATTR_EFFECT: "off"})
    device.async_stop_effect.assert_awaited_once()

    device.values["effect"] = "Lightning"
    entity.internal_update()
    assert entity._attr_effect == "Lightning"
    assert entity._attr_color_mode is light.ColorMode.ONOFF
    assert entity._attr_brightness is None
    assert entity._attr_rgb_color is None
    assert entity._attr_rgbw_color is None


def test_light_exposes_facebd_native_effects():
    device = _make_device()
    device.conn_info["service_uuids"] = ["facebd00-0000-1000-8000-00805f9b34fb"]
    device.facebd = True
    entity = light.FluvalLight(device, "light")

    assert entity._attr_effect_list == [
        "off",
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


def test_entity_subscribes_and_unregisters_update_handler_in_ha_lifecycle():
    device = _make_device()
    device.register_update = MagicMock()
    device.deregister_update = MagicMock()
    entity = light.FluvalLight(device, "light")

    async def run_test():
        assert device.register_update.call_count == 0
        await entity.async_added_to_hass()
        device.register_update.assert_called_once_with("light", entity._update_handler)

        await entity.async_will_remove_from_hass()

    asyncio.run(run_test())
    device.deregister_update.assert_called_once_with("light", entity._update_handler)


def test_entity_reload_cycle_leaves_no_stale_update_handlers():
    device = _make_device()

    async def run_test():
        first = light.FluvalLight(device, "light")
        assert first._update_handler not in device.updates_component
        await first.async_added_to_hass()
        assert device.updates_component == [first._update_handler]
        await first.async_will_remove_from_hass()
        assert device.updates_component == []

        second = light.FluvalLight(device, "light")
        await second.async_added_to_hass()
        assert device.updates_component == [second._update_handler]
        await second.async_will_remove_from_hass()
        assert device.updates_component == []

    asyncio.run(run_test())


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
