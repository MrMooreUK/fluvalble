"""Constants for the Fluval Aquarium LED integration."""

DOMAIN = "fluvalble"

# Options flow keys / defaults
CONF_PING_INTERVAL = "ping_interval"
CONF_ACTIVE_TIME = "active_time"
CONF_LAMP_PROFILE = "lamp_profile"
DEFAULT_PING_INTERVAL = 10  # seconds between keep-alive reads
DEFAULT_ACTIVE_TIME = 120  # seconds to stay connected after last command
DEFAULT_LAMP_PROFILE = "auto"

# Lamp profile options (options flow + channel layout)
LAMP_PROFILE_AUTO = "auto"
LAMP_PROFILE_PLANT = "plant"
LAMP_PROFILE_PLANT_PRO = "plant_pro"
LAMP_PROFILE_MARINE = "marine"
LAMP_PROFILE_AQUASKY = "aquasky"
LAMP_PROFILE_AQUASKY3 = "aquasky3"
LAMP_PROFILES = (
    LAMP_PROFILE_AUTO,
    LAMP_PROFILE_PLANT,
    LAMP_PROFILE_PLANT_PRO,
    LAMP_PROFILE_MARINE,
    LAMP_PROFILE_AQUASKY,
    LAMP_PROFILE_AQUASKY3,
)

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
CMD_CLOCK = 0x0E  # sync RTC: Y M D W h m s
