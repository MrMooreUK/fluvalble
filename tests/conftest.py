"""
Shared fixtures and stubs for Fluval BLE integration tests.

Because the integration depends on homeassistant and bleak — neither of which
are installed in the lightweight CI environment — this module registers minimal
stubs for both before any test module is collected.  All stubs live here so
there is a single place to update if HA changes its API.
"""
import enum
import sys
import types
import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# BLE stubs (bleak / bleak_retry_connector)
# ---------------------------------------------------------------------------

def _stub_bleak():
    mod = types.ModuleType("bleak")
    mod.AdvertisementData = object
    mod.BLEDevice = object
    mod.BleakClient = object
    mod.BleakError = Exception
    mod.BleakGATTCharacteristic = object
    sys.modules["bleak"] = mod

    brc = types.ModuleType("bleak_retry_connector")
    brc.establish_connection = MagicMock()
    sys.modules["bleak_retry_connector"] = brc


# ---------------------------------------------------------------------------
# Home Assistant stubs
# ---------------------------------------------------------------------------

def _stub_homeassistant():
    """Register minimal HA stubs so integration modules can be imported."""

    # ---- homeassistant.exceptions ----
    class HomeAssistantError(Exception):
        pass

    ha_exc = types.ModuleType("homeassistant.exceptions")
    ha_exc.HomeAssistantError = HomeAssistantError

    # ---- homeassistant.const ----
    class Platform(str, enum.Enum):
        NUMBER = "number"
        BINARY_SENSOR = "binary_sensor"
        SELECT = "select"
        SWITCH = "switch"

    class EntityCategory(str, enum.Enum):
        DIAGNOSTIC = "diagnostic"

    ha_const = types.ModuleType("homeassistant.const")
    ha_const.CONF_MAC = "mac"
    ha_const.Platform = Platform
    ha_const.EntityCategory = EntityCategory

    # ---- homeassistant.core ----
    ha_core = types.ModuleType("homeassistant.core")
    ha_core.HomeAssistant = MagicMock
    ha_core.callback = lambda f: f  # passthrough decorator

    # ---- homeassistant.config_entries ----
    class _FakeConfigEntry:
        def __init__(self, data=None, options=None):
            self.data = data or {}
            self.options = options or {}
            self.entry_id = "test_entry_id"

    class _FakeConfigFlow:
        # HA uses ConfigFlow(domain=DOMAIN) as a class keyword arg.
        # Accept and ignore it so our stub works the same way.
        def __init_subclass__(cls, domain=None, **kwargs):
            super().__init_subclass__(**kwargs)

    class _FakeOptionsFlow:
        pass

    class _FakeOptionsFlowWithConfigEntry:
        def __init_subclass__(cls, **kwargs):
            super().__init_subclass__(**kwargs)

        def __init__(self, config_entry=None):
            self.config_entry = config_entry or _FakeConfigEntry()

    class _FakeOptionsFlowWithReload(_FakeOptionsFlowWithConfigEntry):
        pass

    ha_ce = types.ModuleType("homeassistant.config_entries")
    ha_ce.ConfigEntry = _FakeConfigEntry
    ha_ce.ConfigFlow = _FakeConfigFlow
    ha_ce.OptionsFlow = _FakeOptionsFlow
    ha_ce.OptionsFlowWithConfigEntry = _FakeOptionsFlowWithConfigEntry
    ha_ce.OptionsFlowWithReload = _FakeOptionsFlowWithReload
    ha_ce.ConfigFlowResult = dict  # type alias in real HA

    # ---- homeassistant.components.bluetooth ----
    ha_bt = types.ModuleType("homeassistant.components.bluetooth")
    ha_bt.BluetoothServiceInfoBleak = MagicMock
    ha_bt.BluetoothScanningMode = MagicMock()
    ha_bt.BluetoothChange = MagicMock
    ha_bt.async_discovered_service_info = MagicMock(return_value=[])
    ha_bt.async_last_service_info = MagicMock(return_value=None)
    ha_bt.async_register_callback = MagicMock(return_value=lambda: None)

    ha_comp = types.ModuleType("homeassistant.components")
    ha_comp.bluetooth = ha_bt

    # ---- homeassistant.helpers.device_registry ----
    ha_dr = types.ModuleType("homeassistant.helpers.device_registry")
    ha_dr.CONNECTION_BLUETOOTH = "bluetooth"

    # ---- homeassistant.helpers.entity ----
    class _FakeEntity:
        _attr_should_poll = False
        _attr_has_entity_name = False
        _attr_available = True
        _attr_unique_id = None
        _attr_translation_key = None
        _attr_device_info = None
        _attr_is_on = None

        @property
        def hass(self):
            return None

        def _async_write_ha_state(self):
            pass

        async def async_will_remove_from_hass(self):
            pass

    ha_entity = types.ModuleType("homeassistant.helpers.entity")
    ha_entity.Entity = _FakeEntity
    ha_entity.DeviceInfo = dict

    ha_helpers = types.ModuleType("homeassistant.helpers")
    ha_helpers.entity = ha_entity
    ha_helpers.device_registry = ha_dr

    # ---- homeassistant.helpers.entity_platform ----
    ha_ep = types.ModuleType("homeassistant.helpers.entity_platform")
    ha_ep.AddEntitiesCallback = MagicMock

    # ---- homeassistant.components.number ----
    class NumberMode(str, enum.Enum):
        SLIDER = "slider"
        BOX = "box"

    class _FakeNumberEntity(_FakeEntity):
        _attr_native_min_value = None
        _attr_native_max_value = None
        _attr_native_step = None
        _attr_native_value = None
        _attr_mode = NumberMode.SLIDER

    ha_number = types.ModuleType("homeassistant.components.number")
    ha_number.NumberEntity = _FakeNumberEntity
    ha_number.NumberMode = NumberMode

    # ---- homeassistant.components.select ----
    class _FakeSelectEntity(_FakeEntity):
        _attr_current_option = None
        _attr_options = []

    ha_select = types.ModuleType("homeassistant.components.select")
    ha_select.SelectEntity = _FakeSelectEntity

    # ---- homeassistant.components.switch ----
    class _FakeSwitchEntity(_FakeEntity):
        pass

    ha_switch = types.ModuleType("homeassistant.components.switch")
    ha_switch.SwitchEntity = _FakeSwitchEntity

    # ---- homeassistant.components.binary_sensor ----
    class BinarySensorDeviceClass(str, enum.Enum):
        CONNECTIVITY = "connectivity"

    class _FakeBinarySensorEntity(_FakeEntity):
        _attr_is_on = None
        _attr_extra_state_attributes = None

    ha_bs = types.ModuleType("homeassistant.components.binary_sensor")
    ha_bs.BinarySensorDeviceClass = BinarySensorDeviceClass
    ha_bs.BinarySensorEntity = _FakeBinarySensorEntity

    # ---- register everything in sys.modules ----
    modules = {
        "homeassistant": types.ModuleType("homeassistant"),
        "homeassistant.exceptions": ha_exc,
        "homeassistant.const": ha_const,
        "homeassistant.core": ha_core,
        "homeassistant.config_entries": ha_ce,
        "homeassistant.components": ha_comp,
        "homeassistant.components.bluetooth": ha_bt,
        "homeassistant.components.number": ha_number,
        "homeassistant.components.select": ha_select,
        "homeassistant.components.switch": ha_switch,
        "homeassistant.components.binary_sensor": ha_bs,
        "homeassistant.helpers": ha_helpers,
        "homeassistant.helpers.device_registry": ha_dr,
        "homeassistant.helpers.entity": ha_entity,
        "homeassistant.helpers.entity_platform": ha_ep,
    }
    for name, mod in modules.items():
        if name not in sys.modules:
            sys.modules[name] = mod


# ---------------------------------------------------------------------------
# Register stubs before any test module is imported
# ---------------------------------------------------------------------------
_stub_bleak()
_stub_homeassistant()


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ble_device():
    """Return a mock BLEDevice for use in tests."""
    device = MagicMock()
    device.address = "AA:BB:CC:DD:EE:FF"
    device.name = "Fluval Plant 3.0"
    return device


@pytest.fixture
def advertisement():
    """Return a mock AdvertisementData for use in tests."""
    adv = MagicMock()
    adv.local_name = "Fluval Plant 3.0"
    adv.service_uuids = ["00001002-0000-1000-8000-00805f9b34fb"]
    adv.rssi = -65
    return adv
