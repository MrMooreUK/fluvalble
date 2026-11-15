"""Persist one confirmed HA Manual bank per config entry, independently of readback."""

import logging

from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)


async def async_manual_settings_storage(hass, entry):
    """Load storage once and return an attach callback for immediate/deferred discovery."""
    store = Store(hass, 1, f"fluvalble.{entry.entry_id}.manual_settings")
    try:
        saved = await store.async_load()
    except OSError:
        _LOGGER.warning("Unable to load Fluval Manual settings", exc_info=True)
        saved = None

    def attach(device):
        async def persist(levels):
            await store.async_save(
                {
                    "mac": device.mac,
                    "product_id": device.product_id,
                    "spectrum_profile": device.spectrum_profile(),
                    "levels": [levels[channel] for channel in device.numbers()],
                }
            )

        device.configure_manual_settings(saved, persist)

    return attach


async def async_remove_manual_settings(hass, entry):
    """Remove only this entry's saved bank when the integration entry is deleted."""
    await Store(hass, 1, f"fluvalble.{entry.entry_id}.manual_settings").async_remove()
