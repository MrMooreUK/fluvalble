"""Explicit, verified editing of fixture schedule colours and times."""

from pathlib import Path
import asyncio
import re
from collections import Counter

import voluptuous as vol
from homeassistant.components import websocket_api

from .core.schedule_colours import colour_packet, replace_schedule_colours
from .core.products import product_from_id


def _fixture_labels(hass, entries):
    """Use HA device names and areas, never raw addresses as the primary label."""
    from homeassistant.helpers import device_registry as dr, area_registry as ar

    registry = dr.async_get(hass)
    areas = ar.async_get(hass)
    result = []
    for entry in entries:
        devices = dr.async_entries_for_config_entry(registry, entry.entry_id)
        device = devices[0] if devices else None
        product = product_from_id(entry.data.get("product_id"))
        candidates = [
            getattr(device, "name_by_user", None),
            entry.title,
            getattr(device, "name", None),
            getattr(device, "model", None),
            product.model if product else None,
        ]
        name = next(
            (
                name.strip()
                for name in candidates
                if isinstance(name, str)
                and name.strip()
                and not re.search(r"(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}|(?:BLE#0x)?[0-9a-f]{12}", name, re.I)
            ),
            "Fluval light",
        )
        area = areas.async_get_area(device.area_id) if device and device.area_id else None
        if area:
            name = f"{name} · {area.name}"
        result.append({"id": entry.entry_id, "name": name})
    totals = Counter(item["name"] for item in result)
    seen = Counter()
    for item in result:
        if totals[item["name"]] > 1:
            seen[item["name"]] += 1
            item["name"] = f"{item['name']} ({seen[item['name']]})"
    return result


async def _write_schedule_packet(device, packet, transport):
    """Let classic firmware commit schedule memory before another command."""
    if not await device._async_send_packet(packet):
        return False
    if transport == "classic":
        # Community readback verification on CC2541 / FluvalSmart V2.9.
        # This delay is hardware evidence, not an APK clock-format change.
        await asyncio.sleep(1.5)
    return True


async def async_setup_editor(hass):
    """Register one bundled card and its explicit save endpoint."""
    from . import DOMAIN, entry_runtime_data
    from homeassistant.components import frontend

    if hass.data[DOMAIN].get("colour_editor_registered"):
        return

    url = "/fluvalble/schedule-colours.js"
    path = str(Path(__file__).parent / "www" / "schedule-colours.js")
    if hasattr(hass.http, "async_register_static_paths"):
        from homeassistant.components.http import StaticPathConfig

        await hass.http.async_register_static_paths([StaticPathConfig(url, path, False)])
    else:
        hass.http.register_static_path(url, path, cache_headers=False)
    frontend.add_extra_js_url(hass, url)

    @websocket_api.websocket_command({vol.Required("type"): "fluvalble/colour_editor_devices"})
    @websocket_api.async_response
    async def devices(hass, connection, msg):
        connection.send_result(
            msg["id"],
            _fixture_labels(hass, hass.config_entries.async_entries(DOMAIN)),
        )

    @websocket_api.websocket_command(
        {
            vol.Required("type"): "fluvalble/save_schedule_colours",
            vol.Required("entry_id"): str,
            vol.Required("schedule"): vol.In(["auto", "professional"]),
            vol.Required("target"): vol.Any(str, int),
            vol.Required("levels"): [int],
            vol.Required("baseline"): vol.Any(dict, list),
            vol.Optional("times"): vol.Any(dict, int),
        }
    )
    @websocket_api.async_response
    async def save(hass, connection, msg):
        connection.require_admin()
        entry = hass.config_entries.async_get_entry(msg["entry_id"])
        if entry is None or entry.domain != DOMAIN:
            connection.send_error(msg["id"], "not_found", "Fluval fixture not found")
            return
        device = entry_runtime_data(hass, entry).device
        if device is None:
            connection.send_error(msg["id"], "unavailable", "Fixture unavailable")
            return
        try:
            async with device.command_transaction():
                if not await device.async_refresh_state():
                    raise ValueError("Unable to read the fixture before saving")
                key = "native_auto_schedule" if msg["schedule"] == "auto" else "native_pro_schedule"
                required_mode = "automatic" if msg["schedule"] == "auto" else "professional"
                if device.values.get("mode") != required_mode:
                    raise ValueError("Select the matching schedule mode on the light before editing")
                current = device.values.get(key)
                if current != msg["baseline"]:
                    raise ValueError("Schedule changed. Reload it before saving")
                transport = (
                    "facebd" if device._uses_wifi_protocol() else "spp" if device._uses_spp_protocol() else "classic"
                )
                packet = colour_packet(
                    current,
                    transport=transport,
                    channel_count=len(device.numbers()),
                    levels=msg["levels"],
                    target=msg["target"],
                    times=msg.get("times"),
                )
                if not await _write_schedule_packet(device, packet, transport):
                    raise ValueError(device.command_error_message())
                if not await device.async_refresh_state():
                    raise ValueError("Write sent, but readback failed. Reload to confirm the result")
                expected = replace_schedule_colours(
                    current,
                    channel_count=len(device.numbers()),
                    levels=msg["levels"],
                    target=msg["target"],
                    times=msg.get("times"),
                )
                if device.values.get(key) != expected:
                    raise ValueError("Fixture readback did not confirm the saved schedule. Reload before retrying")
            connection.send_result(msg["id"], True)
        except (ValueError, KeyError, TypeError) as err:
            connection.send_error(msg["id"], "save_failed", str(err))

    websocket_api.async_register_command(hass, devices)
    websocket_api.async_register_command(hass, save)
    hass.data[DOMAIN]["colour_editor_registered"] = True
