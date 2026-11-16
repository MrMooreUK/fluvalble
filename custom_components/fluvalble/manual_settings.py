"""Persist one confirmed HA Manual bank per config entry, independently of readback."""

import logging

from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

SAVE_DELAY = 5

# One Store per entry, so removal cancels any pending delayed save on the same
# instance instead of letting it recreate the file afterwards.
_STORES: dict[str, Store] = {}


def _store(hass, entry) -> Store:
    store = _STORES.get(entry.entry_id)
    if store is None:
        store = _STORES[entry.entry_id] = Store(hass, 1, f"fluvalble.{entry.entry_id}.manual_settings")
    return store


async def async_manual_settings_storage(hass, entry):
    """Load storage once and return an attach callback for immediate/deferred discovery."""
    store = _store(hass, entry)
    try:
        saved = await store.async_load()
    except OSError:
        _LOGGER.warning("Unable to load Fluval Manual settings", exc_info=True)
        saved = None

    def attach(device):
        async def persist(levels):
            data = {
                "mac": device.mac,
                "product_id": device.product_id,
                "spectrum_profile": device.spectrum_profile(),
                "levels": [levels[channel] for channel in device.numbers()],
            }
            # Debounced: rapid confirmed changes produce one disk write.
            store.async_delay_save(lambda: data, SAVE_DELAY)

        device.configure_manual_settings(saved, persist)

    return attach


async def async_remove_manual_settings(hass, entry):
    """Remove only this entry's saved bank when the integration entry is deleted."""
    store = _STORES.pop(entry.entry_id, None) or Store(hass, 1, f"fluvalble.{entry.entry_id}.manual_settings")
    await store.async_remove()
