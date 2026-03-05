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
RECONNECT_DELAY = 30
INITIAL_RETRY_DELAY = 10
MAX_INITIAL_RETRIES = 30  # ~5 minutes of retrying at 10s intervals

CHAR_NOTIFY = "00001002-0000-1000-8000-00805F9B34FB"
CHAR_KEEPALIVE = "00001004-0000-1000-8000-00805F9B34FB"
CHAR_COMMAND_OUT = "00001001-0000-1000-8000-00805F9B34FB"
# CHAR_COMMAND_IO intentionally shares UUID with CHAR_NOTIFY — the device uses
# a single bidirectional characteristic for both outbound writes and notifications.
CHAR_COMMAND_IO = "00001002-0000-1000-8000-00805F9B34FB"

# Fluval packets come in two fragments; the first is always 17 decrypted bytes.
PARTIAL_PACKET_SIZE = 17


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
        self.send_queue: list[bytes] = []
        self.connect_task = asyncio.create_task(self._connect_with_retry())

        self.receive_buffer = b""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_ble_device(self, ble_device: BLEDevice):
        """Update the BLEDevice reference (e.g. from a newer advertisement)."""
        self.device = ble_device

    def ping(self):
        """Start the ping task to periodically talk to the Fluval."""
        self.ping_time = time.time() + ACTIVE_TIME

        if not self.ping_task or self.ping_task.done():
            self.ping_task = asyncio.create_task(self._ping_loop())

    def send(self, data: bytes | list[bytes]):
        """Queue one or more packets to send to the Fluval on the next ping cycle."""
        self.send_time = time.time() + COMMAND_TIME
        if isinstance(data, list):
            self.send_queue.extend(data)
        else:
            self.send_queue.append(data)
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
        if not data or len(data) < 3:
            _LOGGER.warning(
                "Received short/empty BLE notification (%d bytes) from %s — ignoring",
                len(data) if data else 0,
                self.device.address,
            )
            return
        decrypted = decrypt(data)
        if len(decrypted) == PARTIAL_PACKET_SIZE:
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
    # Internal: initial connection with retry
    # ------------------------------------------------------------------

    async def _connect_with_retry(self):
        """Try to connect, retrying on failure until success or stopped."""
        for attempt in range(1, MAX_INITIAL_RETRIES + 1):
            if self._stopped:
                return

            _LOGGER.debug(
                "Connection attempt %d/%d to %s",
                attempt,
                MAX_INITIAL_RETRIES,
                self.device.address,
            )

            if await self._do_connect():
                return  # Success

            if self._stopped:
                return

            _LOGGER.debug(
                "Attempt %d failed for %s — retrying in %ds",
                attempt,
                self.device.address,
                INITIAL_RETRY_DELAY,
            )
            await asyncio.sleep(INITIAL_RETRY_DELAY)

        _LOGGER.warning(
            "Gave up connecting to %s after %d attempts.",
            self.device.address,
            MAX_INITIAL_RETRIES,
        )

    async def _do_connect(self) -> bool:
        """Single connection attempt. Returns True on success."""
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
                data=encrypt(bytearray([0x68, 0x05])),
                response=False,
            )
            _LOGGER.info("Connected to Fluval %s", self.device.address)
            return True
        except (BleakError, TimeoutError, OSError) as err:
            _LOGGER.warning(
                "Connection to %s failed: %s",
                self.device.address,
                err,
            )
            self._set_status(False)
            return False

    # ------------------------------------------------------------------
    # Internal: keep-alive / reconnect loop
    # ------------------------------------------------------------------

    async def _ping_loop(self):
        """Ping the Fluval to keep connection alive, reconnect on drop."""
        loop = asyncio.get_running_loop()

        while not self._stopped and time.time() < self.ping_time:
            try:
                # (Re-)establish connection if needed
                if not self.client or not self.client.is_connected:
                    _LOGGER.debug("Reconnecting to %s", self.device.address)
                    if not await self._do_connect():
                        # Connection failed — wait and retry
                        await asyncio.sleep(RECONNECT_DELAY)
                        continue

                # Keep-alive read
                await self.client.read_gatt_char(CHAR_KEEPALIVE)

                # Send queued commands if within the time window (small delay between each)
                while self.send_queue and time.time() < self.send_time:
                    cmd = self.send_queue.pop(0)
                    encrypted = encrypt(cmd)
                    _LOGGER.debug(
                        "Sending to %s — raw: %s | encrypted: %s",
                        self.device.address,
                        to_hex(cmd),
                        to_hex(encrypted),
                    )
                    await self.client.write_gatt_char(
                        CHAR_COMMAND_IO,
                        data=encrypted,
                        response=True,
                    )
                    if self.send_queue:
                        await asyncio.sleep(0.2)  # Let device process before next command

                # Interruptible sleep (cancelled early when send() is called)
                self.ping_future = loop.create_future()
                loop.call_later(PING_INTERVAL, self.ping_future.cancel)
                with contextlib.suppress(asyncio.CancelledError):
                    await self.ping_future

                # Normal path complete — loop immediately without reconnect delay.
                continue

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
                    "Unexpected error in ping loop for %s",
                    self.device.address,
                )
                await self._safe_disconnect()

            # Pause before reconnect attempt after an error (unless we're shutting down)
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
        # Discard any partially-assembled packet so the next connection starts clean.
        self.receive_buffer = b""
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
