"""Client class connecting the Fluval BLE Entity to a bluetooth connection."""

import asyncio
from collections.abc import Callable
import contextlib
import logging
import time

from bleak import BleakClient, BleakError, BleakGATTCharacteristic, BLEDevice
from bleak_retry_connector import establish_connection

from . import encryption

_LOGGER = logging.getLogger(__name__)

ACTIVE_TIME = 120
COMMAND_TIME = 15
PING_INTERVAL = 10
RECONNECT_DELAY = 5

CHAR_NOTIFY = "00001002-0000-1000-8000-00805F9B34FB"
CHAR_KEEPALIVE = "00001004-0000-1000-8000-00805F9B34FB"
CHAR_COMMAND_OUT = "00001001-0000-1000-8000-00805F9B34FB"
CHAR_COMMAND_IO = "00001002-0000-1000-8000-00805F9B34FB"


class Client:
    """Basic client handling BLE sending and callbacks."""

    def __init__(
        self,
        device: BLEDevice,
        status_callback: Callable = None,
        update_callback: Callable = None,
    ) -> None:
        """Initialize the client."""
        self.device = device
        self.status_callback = status_callback
        self.update_callback = update_callback

        self.client: BleakClient | None = None
        self._stopped = False

        self.ping_future: asyncio.Future | None = None
        self.ping_task: asyncio.Task | None = None
        self.ping_time = 0

        self.send_data = None
        self.send_time = 0
        self.connect_task = asyncio.create_task(self._connect())

        self.receive_buffer = b""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ping(self):
        """Start the ping task to periodically talk to the Fluval."""
        self.ping_time = time.time() + ACTIVE_TIME

        if not self.ping_task or self.ping_task.done():
            self.ping_task = asyncio.create_task(self._ping_loop())

    def send(self, data: bytes):
        """Queue a packet to send to the Fluval on the next ping cycle."""
        self.send_time = time.time() + COMMAND_TIME
        self.send_data = data
        self.ping()

        if self.ping_future and not self.ping_future.done():
            self.ping_future.cancel()

    async def stop(self):
        """Disconnect and cancel all background tasks."""
        self._stopped = True

        if self.ping_future and not self.ping_future.done():
            self.ping_future.cancel()

        for task in (self.connect_task, self.ping_task):
            if task and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

        if self.client:
            try:
                await self.client.disconnect()
            except (BleakError, TimeoutError, OSError):
                pass
            self.client = None

        self._set_status(False)

    # ------------------------------------------------------------------
    # BLE notification handler
    # ------------------------------------------------------------------

    def notify_callback(self, sender: BleakGATTCharacteristic, data: bytearray):
        """Handle packets sent by the Fluval."""
        decrypted = decrypt(data)
        if len(decrypted) == 17:
            # Partial packet — accumulate
            self.receive_buffer += decrypted
        else:
            # Final fragment (or single packet): append, deliver, reset
            full_payload = self.receive_buffer + decrypted
            _LOGGER.debug("Got all data: %s", to_hex(full_payload))
            if self.update_callback:
                self.update_callback(full_payload)
            self.receive_buffer = b""

    # ------------------------------------------------------------------
    # Internal: initial connection
    # ------------------------------------------------------------------

    async def _connect(self):
        """Connect to the Fluval and subscribe to notifications."""
        try:
            self.client = await establish_connection(
                BleakClient, self.device, self.device.address
            )

            await self.client.start_notify(CHAR_NOTIFY, self.notify_callback)

            self._set_status(True)

            # Handshake step 0 — dummy read
            await self.client.read_gatt_char(CHAR_KEEPALIVE)

            # Handshake step 1 — request current state
            await self.client.write_gatt_char(
                CHAR_COMMAND_OUT,
                data=encrypt([0x68, 0x05]),
                response=False,
            )
            _LOGGER.info("Connected to Fluval %s", self.device.address)
        except (BleakError, TimeoutError, OSError) as err:
            _LOGGER.warning(
                "Initial connection to %s failed: %s — will retry via ping loop",
                self.device.address,
                err,
            )
            self._set_status(False)

    # ------------------------------------------------------------------
    # Internal: keep-alive / reconnect loop
    # ------------------------------------------------------------------

    async def _ping_loop(self):
        """Ping the Fluval to keep connection alive, reconnect on drop."""
        loop = asyncio.get_event_loop()

        while not self._stopped and time.time() < self.ping_time:
            try:
                # (Re-)establish connection if needed
                if not self.client or not self.client.is_connected:
                    _LOGGER.debug("Reconnecting to %s", self.device.address)
                    self.client = await establish_connection(
                        BleakClient, self.device, self.device.address
                    )
                    await self.client.start_notify(CHAR_NOTIFY, self.notify_callback)
                    self._set_status(True)

                    # Re-do handshake after reconnect
                    await self.client.read_gatt_char(CHAR_KEEPALIVE)
                    await self.client.write_gatt_char(
                        CHAR_COMMAND_OUT,
                        data=encrypt([0x68, 0x05]),
                        response=False,
                    )
                    _LOGGER.info("Reconnected to Fluval %s", self.device.address)

                # Keep-alive read
                await self.client.read_gatt_char(CHAR_KEEPALIVE)

                # Send queued command if within the time window
                if self.send_data and time.time() < self.send_time:
                    await self.client.write_gatt_char(
                        CHAR_COMMAND_IO,
                        data=encrypt(self.send_data),
                        response=True,
                    )
                    _LOGGER.debug("Sent command to %s", self.device.address)
                self.send_data = None

                # Interruptible sleep (cancelled early when send() is called)
                self.ping_future = loop.create_future()
                loop.call_later(PING_INTERVAL, self.ping_future.cancel)
                with contextlib.suppress(asyncio.CancelledError):
                    await self.ping_future

            except asyncio.CancelledError:
                break
            except TimeoutError:
                _LOGGER.warning(
                    "Timeout communicating with %s — will reconnect",
                    self.device.address,
                )
                await self._safe_disconnect()
            except BleakError as err:
                _LOGGER.warning(
                    "BLE error with %s: %s — will reconnect",
                    self.device.address,
                    err,
                )
                await self._safe_disconnect()
            except Exception:
                _LOGGER.exception(
                    "Unexpected error in ping loop for %s", self.device.address
                )
                await self._safe_disconnect()

            # Brief pause before reconnect attempt (unless we're shutting down)
            if not self._stopped:
                await asyncio.sleep(RECONNECT_DELAY)

        # Cleanly disconnect when the active window expires
        await self._safe_disconnect()
        self.ping_task = None
        _LOGGER.debug("Ping loop ended for %s", self.device.address)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _set_status(self, connected: bool):
        """Notify the device of connection status changes."""
        if self.status_callback:
            self.status_callback(connected)

    async def _safe_disconnect(self):
        """Disconnect the BLE client without raising."""
        self._set_status(False)
        if self.client:
            try:
                await self.client.disconnect()
            except (BleakError, TimeoutError, OSError):
                pass
            self.client = None


def encrypt(data: bytearray) -> bytearray:
    """Encrypt a packet for sending to Fluval."""
    data = encryption.add_crc(data)
    return encryption.encrypt(data)


def decrypt(data: bytearray) -> bytearray:
    """Decrypt a packet that has been received by the Fluval."""
    return encryption.decrypt(data)


def to_hex(data: bytes) -> str:
    """Print a byte array as hex strings for debugging."""
    return " ".join(format(x, "02x") for x in data)
