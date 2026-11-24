"""Explicit, offline-built native provisioning frames from FluvalConnect.

Never invoked by config entry setup or an ordinary light command. These frames
replace the fixture's saved network/broker configuration.
"""

import re

PROVISION_UUID = "facebd80-7261-6262-6974-696f74626c65"


class InvalidProvisioningField(ValueError):
    """A field cannot be represented in the fixture's provisioning format."""


def _field(value: str, *, maximum: int, empty: bool = False) -> str:
    """Reject delimiters/control bytes; don't interpolate arbitrary config text."""
    if not isinstance(value, str) or (not value and not empty):
        raise InvalidProvisioningField("A nonempty configuration field is required")
    if len(value) > maximum or any(not 32 <= ord(char) <= 126 or char in ":;" for char in value):
        raise InvalidProvisioningField("Configuration fields must be bounded printable ASCII without ':' or ';'")
    return value


def wifi_frame(ssid: str, password: str, offset_minutes: int) -> bytes:
    """Encode network credentials followed by the local UTC offset in minutes."""
    if type(offset_minutes) is not int or not -840 <= offset_minutes <= 840:
        raise ValueError("Invalid timezone offset")
    return (
        f"ssid:{_field(ssid, maximum=32)};password:{_field(password, maximum=63, empty=True)};"
        f"timeoffset:{offset_minutes};;"
    ).encode("ascii")


def broker_frame(host: str, port: int, client_id: str, username: str, password: str) -> bytes:
    """APK broker configuration, using owner-provided local credentials only."""
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("Invalid MQTT port")
    # Conservative tool bounds, not a claim about every firmware buffer size.
    return (
        f"host:{_field(host, maximum=63)};port:{port};clientid:{_field(client_id, maximum=63)};"
        f"username:{_field(username, maximum=63, empty=True)};"
        f"password:{_field(password, maximum=63, empty=True)};;"
    ).encode("ascii")


def provisioning_wifi_mac(report: str) -> str | None:
    """Extract MAC only from the native identity response, never infer from BLE."""
    match = re.search(r"(?:^|;)mac:([0-9A-Fa-f]{12}|(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2})(?:;|$)", report)
    if not match:
        return None
    raw = match.group(1).replace(":", "").upper()
    return ":".join(raw[index : index + 2] for index in range(0, 12, 2))
