"""Constants for the Fluval Aquarium LED integration."""

DOMAIN = "fluvalble"

# Options flow keys / defaults
CONF_PING_INTERVAL = "ping_interval"
CONF_ACTIVE_TIME = "active_time"
CONF_MODEL = "model"
DEFAULT_PING_INTERVAL = 10  # seconds between keep-alive reads
DEFAULT_ACTIVE_TIME = 120  # seconds to stay connected after last command

# ---------------------------------------------------------------------------
# Channel colour profiles
# ---------------------------------------------------------------------------
# The brightness channels map to different physical LED colours depending on
# the lamp model. The device does not report its model over BLE (Plant and
# Reef/Marine are both 5-channel and otherwise indistinguishable), so the model
# is chosen by the user in the options flow. Order matches the byte order in
# the brightness command, so index 0 == channel_1, index 1 == channel_2, etc.
# Sourced from the working ESPHome component (mrzottel/esphome@fluval_ble_led
# and TheRealFalseReality/fluval-bluetooth-hub).
MODEL_AQUASKY_2 = "aquasky_2"
MODEL_PLANT_3 = "plant_3"
MODEL_REEF_3 = "reef_3"

CHANNEL_PROFILES: dict[str, list[str]] = {
    MODEL_AQUASKY_2: ["Red", "Green", "Blue", "White"],
    MODEL_PLANT_3: ["Pink", "Blue", "Cold White", "Pure White", "Warm White"],
    MODEL_REEF_3: ["Pink", "Cyan", "Blue", "Purple", "Cold White"],
}

# Human-readable labels for the model dropdown in the options flow.
MODEL_NAMES: dict[str, str] = {
    MODEL_AQUASKY_2: "Aquasky 2.0 (4 channels)",
    MODEL_PLANT_3: "Plant 3.0 (5 channels)",
    MODEL_REEF_3: "Reef / Marine 3.0 (5 channels)",
}

# Colour name -> Material Design icon for the channel number entities.
CHANNEL_ICONS: dict[str, str] = {
    "Red": "mdi:palette",
    "Green": "mdi:palette",
    "Blue": "mdi:palette",
    "White": "mdi:white-balance-sunny",
    "Pink": "mdi:palette",
    "Cyan": "mdi:palette",
    "Cold White": "mdi:white-balance-sunny",
    "Pure White": "mdi:white-balance-sunny",
    "Warm White": "mdi:white-balance-incandescent",
    "Purple": "mdi:palette",
}


def default_model_for(channel_count: int) -> str:
    """Best-guess model from the detected channel count.

    4-channel lamps are Aquasky 2.0; 5-channel lamps default to Plant 3.0
    (the most common 5-channel model). The user can change this in options.
    """
    return MODEL_AQUASKY_2 if channel_count < 5 else MODEL_PLANT_3

# ---------------------------------------------------------------------------
# BLE command protocol
# ---------------------------------------------------------------------------
# Every outbound command starts with CMD_HEADER followed by a command byte.
# Reverse-engineered from the Fluval Plant 3.0 ("Planted Tank") protocol.
CMD_HEADER = 0x68
CMD_MODE = 0x02  # followed by mode byte: 0=manual, 1=automatic, 2=professional
CMD_SWITCH = 0x03  # followed by 0x01 (on) / 0x00 (off)
CMD_BRIGHTNESS = 0x04  # followed by per-channel 16-bit big-endian values
CMD_STATUS = 0x05  # request current state (no payload)
