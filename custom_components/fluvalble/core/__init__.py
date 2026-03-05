"""Constants for the Fluval Aquarium LED integration."""

DOMAIN = "fluvalble"

# Options flow keys / defaults
CONF_PING_INTERVAL = "ping_interval"
CONF_ACTIVE_TIME = "active_time"
DEFAULT_PING_INTERVAL = 10  # seconds between keep-alive reads
DEFAULT_ACTIVE_TIME = 120   # seconds to stay connected after last command
