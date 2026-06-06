"""Constants for the Fluval Aquarium LED integration."""

DOMAIN = "fluvalble"

# Options flow keys / defaults
CONF_PING_INTERVAL = "ping_interval"
CONF_ACTIVE_TIME = "active_time"
DEFAULT_PING_INTERVAL = 10  # seconds between keep-alive reads
DEFAULT_ACTIVE_TIME = 120  # seconds to stay connected after last command

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
