"""Client class connecting the Fluval BLE Entity to a bluetooth connection."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import contextlib
import logging
import time

from bleak import BleakClient, BleakError, BleakGATTCharacteristic, BLEDevice
from bleak_retry_connector import establish_connection

from . import encryption, protocol

_LOGGER = logging.getLogger(__name__)

ACTIVE_TIME = 120
COMMAND_TIME = 15
CONNECT_TIMEOUT = 20
CONNECT_RETRIES = 3
WRITE_RETRIES = 2
WRITE_DELAY = 0.3
COMMAND_GAP = 0.75
CLASSIC_COMMAND_GAP = 0.2
POST_WRITE_STATE_DELAY = 0.8
STATE_NOTIFY_TIMEOUT = 0.75
UNVERIFIED_WRITE_COPIES = 2
CHUNK_WRITE_GAP = 0.01

# Hardware capture from AquaSky 3.0 establishes this FACEBD split:
#   facebd01 = raw CBOR command writes
#   facebd02 = state/acknowledgement read + notify
#   facebd80 = provisioning/identity (light commands return "err:arg;;")
#
# facebd02 accepts and echoes writes, but that does not prove the controller
# acted on them, so neither facebd02 nor facebd80 is a command fallback.
# Lowercase UUID strings are required for ESPHome 2026.x / esp-idf 5.x
# Bluetooth proxies, which compare characteristic UUIDs case-sensitively.
FACEBD_COMMAND_WRITE_UUIDS = (
    "facebd01-7261-6262-6974-696f74626c65",
    "facebd01-0000-1000-8000-00805f9b34fb",
)
SPP_COMMAND_WRITE_UUIDS = ("0000fff2-0000-1000-8000-00805f9b34fb",)
LEGACY_COMMAND_WRITE_UUIDS = ("00001001-0000-1000-8000-00805f9b34fb",)
COMMAND_WRITE_UUIDS = FACEBD_COMMAND_WRITE_UUIDS + SPP_COMMAND_WRITE_UUIDS + LEGACY_COMMAND_WRITE_UUIDS
NOTIFY_UUIDS = (
    "facebd02-7261-6262-6974-696f74626c65",
    "facebd02-0000-1000-8000-00805f9b34fb",
    "facebd03-7261-6262-6974-696f74626c65",
    "facebd03-0000-1000-8000-00805f9b34fb",
    "facebd80-7261-6262-6974-696f74626c65",
    "facebd80-0000-1000-8000-00805f9b34fb",
    "00001002-0000-1000-8000-00805f9b34fb",
    "0000fff1-0000-1000-8000-00805f9b34fb",
)
INIT_WRITE_UUIDS = LEGACY_COMMAND_WRITE_UUIDS
WAKE_READ_UUIDS = (
    "facebd02-7261-6262-6974-696f74626c65",
    "facebd02-0000-1000-8000-00805f9b34fb",
    "facebd81-7261-6262-6974-696f74626c65",
    "facebd81-0000-1000-8000-00805f9b34fb",
    "facebd80-7261-6262-6974-696f74626c65",
    "facebd80-0000-1000-8000-00805f9b34fb",
    "00001004-0000-1000-8000-00805f9b34fb",
    "0000fff6-0000-1000-8000-00805f9b34fb",
)
WRITE_PROPERTIES = frozenset({"write", "write-without-response"})

DeviceProvider = Callable[[], BLEDevice | None]
ConnectionReadyCallback = Callable[[BLEDevice, str | None], None]
StateReadyCallback = Callable[[dict[int, object]], Awaitable[None]]


class Client:
    """Basic client handling BLE sending and callbacks."""

    def __init__(
        self,
        device: BLEDevice,
        status_callback: Callable | None = None,
        update_callback: Callable | None = None,
        ping_interval: int = 10,
        active_time: int = ACTIVE_TIME,
        device_provider: DeviceProvider | None = None,
        connection_ready_callback: ConnectionReadyCallback | None = None,
        ready_callback: Callable[[], Awaitable[None]] | None = None,
        state_ready_callback: StateReadyCallback | None = None,
    ) -> None:
        """Initialize the client."""
        self.device = device
        self.status_callback = status_callback
        self.update_callback = update_callback
        self.device_provider = device_provider
        self.connection_ready_callback = connection_ready_callback
        self.ready_callback = ready_callback
        self.state_ready_callback = state_ready_callback
        self._ping_interval = ping_interval
        self._active_time = active_time

        self.client: BleakClient | None = None

        self.ping_future: asyncio.Future | None = None
        self.ping_task: asyncio.Task | None = None
        self.ping_time: float = 0.0
        self._stopping = False

        self.send_data = None
        self.send_time = 0
        self.connect_task: asyncio.Task | None = None

        self.receive_buffer = b""
        self.notify_uuid = None
        self.notify_uuids: list[str] = []
        self.init_write_uuid = None
        self.command_write_uuid = None
        self.command_write_uuids: list[str] = []
        self.wake_read_uuid = None
        self.state_read_uuids: list[str] = []
        self.raw_facebd = False
        self.wifi_facebd = False
        self.plant_pro_spp = False
        self.profile = "unresolved"
        self._connection_lock = asyncio.Lock()
        self._command_lock = asyncio.Lock()
        self._state_update_event = asyncio.Event()
        self._observed_state: dict[int, object] = {}
        self.last_error: str | None = None
        self.last_write_targets: list[str] = []
        self.last_write_verified = False
        self.last_expected_state: dict[int, object] = {}
        self.last_confirmed_state: dict[int, object] = {}
        self.last_verification_mismatches: dict[int, dict[str, object]] = {}
        self.last_command_at = 0.0
        self.connect_task = asyncio.create_task(self._connect())

    def _get_characteristic(self, uuid: str) -> BleakGATTCharacteristic | None:
        """Return a characteristic if present, without raising on missing UUIDs."""
        if self.client is None:
            return None
        target = str(uuid).lower()
        try:
            characteristic = self.client.services.get_characteristic(uuid)
        except BleakError:
            characteristic = None
        if characteristic is not None:
            return characteristic
        # ESPHome 2026.x / esp-idf 5.x compares UUID strings case-sensitively.
        if uuid != target:
            try:
                characteristic = self.client.services.get_characteristic(target)
            except BleakError:
                characteristic = None
            if characteristic is not None:
                return characteristic
        try:
            for service in self.client.services:
                for char in getattr(service, "characteristics", ()):
                    if str(char.uuid).lower() == target:
                        return char
        except (AttributeError, TypeError, BleakError):
            return None
        return None

    def _find_characteristic(
        self,
        candidates: tuple[str, ...],
        *,
        require_write: bool = False,
        require_notify: bool = False,
        required: bool = True,
    ) -> str | None:
        """Return the first candidate matching the requested properties."""
        for uuid in candidates:
            characteristic = self._get_characteristic(uuid)
            if characteristic is None:
                continue

            properties = set(characteristic.properties)
            if require_write and not properties.intersection(WRITE_PROPERTIES):
                continue
            if require_notify and "notify" not in properties and "indicate" not in properties:
                # Some FACEBD WiFi controllers still accept start_notify on facebd80
                # even when the advertised property list is incomplete.
                if not characteristic.uuid.lower().startswith("facebd80"):
                    continue

            return characteristic.uuid

        if required:
            raise BleakError(f"None of the candidate UUIDs are available: {candidates}")
        return None

    def _find_characteristics(
        self,
        candidates: tuple[str, ...],
        *,
        require_write: bool = False,
        require_notify: bool = False,
    ) -> list[str]:
        """Return all candidates matching the requested properties."""
        found: list[str] = []
        for uuid in candidates:
            characteristic = self._get_characteristic(uuid)
            if characteristic is None:
                continue

            properties = set(characteristic.properties)
            if require_write and not properties.intersection(WRITE_PROPERTIES):
                continue
            if require_notify and "notify" not in properties and "indicate" not in properties:
                if not characteristic.uuid.lower().startswith("facebd80"):
                    continue

            if characteristic.uuid not in found:
                found.append(characteristic.uuid)
        return found

    async def _resolve_characteristics(self):
        """Resolve the Fluval characteristic profile exposed by this device."""
        self.command_write_uuids = self._find_characteristics(COMMAND_WRITE_UUIDS, require_write=True)
        if not self.command_write_uuids:
            raise BleakError(f"None of the command UUIDs are available: {COMMAND_WRITE_UUIDS}")
        self.command_write_uuid = self.command_write_uuids[0]
        self.notify_uuids = self._find_characteristics(NOTIFY_UUIDS, require_notify=True)
        if not self.notify_uuids:
            raise BleakError(f"None of the notify UUIDs are available: {NOTIFY_UUIDS}")
        self.notify_uuid = self.notify_uuids[0]
        # Init write is only needed by the older encrypted BLE protocol.
        self.init_write_uuid = self._find_characteristic(INIT_WRITE_UUIDS, require_write=True, required=False)
        self.wake_read_uuid = self._find_characteristic(WAKE_READ_UUIDS, required=False)
        self.state_read_uuids = self._find_characteristics(WAKE_READ_UUIDS)
        write_uuid = self.command_write_uuid.lower()
        self.plant_pro_spp = write_uuid.startswith("0000fff2")
        self.raw_facebd = write_uuid.startswith("facebd") or self.plant_pro_spp
        self.wifi_facebd = write_uuid.startswith("facebd01")
        if self.plant_pro_spp:
            self.profile = "plant_pro_spp"
        elif self.wifi_facebd:
            self.profile = "facebd_command"
        else:
            self.profile = "legacy_encrypted"
        _LOGGER.debug(
            "Resolved Fluval GATT profile=%s writes=%s notifies=%s reads=%s init=%s wake=%s raw_facebd=%s",
            self.profile,
            self.command_write_uuids,
            self.notify_uuids,
            self.state_read_uuids,
            self.init_write_uuid,
            self.wake_read_uuid,
            self.raw_facebd,
        )

    def _current_device(self) -> BLEDevice:
        """Refresh the route so HA can select the best adapter or proxy."""
        if self.device_provider is not None:
            try:
                if current := self.device_provider():
                    self.device = current
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Unable to refresh Fluval BLE route", exc_info=err)
        return self.device

    async def _ensure_client(self):
        """Connect and subscribe to notifications if needed."""
        async with self._connection_lock:
            if self._stopping:
                raise BleakError("Fluval BLE client is stopping")
            if self.client and self.client.is_connected:
                return self.client

            stale_client = self.client
            self.client = None
            if stale_client is not None:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(stale_client.disconnect(), timeout=5)

            device = self._current_device()
            try:
                client = await establish_connection(
                    BleakClient,
                    device,
                    device.address,
                    disconnected_callback=self._on_disconnected,
                    max_attempts=CONNECT_RETRIES,
                    timeout=CONNECT_TIMEOUT,
                    ble_device_callback=self._current_device,
                )
            except (TimeoutError, BleakError, EOFError) as err:
                self.last_error = f"connect failed: {type(err).__name__}: {err}"
                raise

            if self._stopping:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(client.disconnect(), timeout=5)
                raise BleakError("Fluval BLE client stopped while connecting")

            self.client = client
            try:
                await self._resolve_characteristics()
                for uuid in self.notify_uuids:
                    with contextlib.suppress(BleakError):
                        await client.start_notify(uuid, self.notify_callback)
            except Exception:
                self.client = None
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(client.disconnect(), timeout=5)
                raise

            if self.connection_ready_callback:
                # HA's client wrapper may select another scanner with an
                # available slot after receiving the requested BLEDevice.
                # Report that confirmed scanner when available and retain the
                # requested device only as a compatibility fallback for other
                # clients. This does not influence HA's route selection.
                connected_scanner = getattr(client, "_connected_scanner", None)
                connected_source = getattr(connected_scanner, "source", None)
                self.connection_ready_callback(
                    device,
                    str(connected_source) if connected_source else None,
                )
            if self.status_callback:
                self.status_callback(True)
            self.last_error = None

            return client

    def _on_disconnected(self, client: BleakClient) -> None:
        """Update state and restore an opted-in persistent connection."""
        if client is not self.client:
            return

        self.client = None
        if self.status_callback:
            self.status_callback(False)

        # Wake the heartbeat so it stops using the disconnected client.
        if self.ping_future:
            self.ping_future.cancel()

        if self._stopping or self._active_time != 0:
            return
        if not self.ping_task or self.ping_task.done():
            self.ping()

    async def ensure_connected(self) -> bool:
        """Connect far enough to resolve the live GATT profile."""
        try:
            await self._ensure_client()
            return True
        except (TimeoutError, BleakError) as err:
            _LOGGER.debug("Fluval connect for profile resolution failed", exc_info=err)
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.warning(
                "Unexpected Fluval connect failure during profile resolution",
                exc_info=err,
            )

        if self.status_callback:
            self.status_callback(False)
        return False

    def ping(self):
        """Start the ping task to periodically talk to the Fluval."""
        if self._active_time == 0:
            self.ping_time = float("inf")
        else:
            self.ping_time = time.time() + self._active_time

        if not self.ping_task:
            self.ping_task = asyncio.create_task(self._ping_loop())

    def _dispatch_update(self, data: bytes) -> bool:
        """Decode an update and signal waiters only for valid state packets."""
        if self.raw_facebd:
            try:
                decoded = protocol.decode_cbor_update(data)
            except ValueError:
                decoded = None
            if decoded:
                self._observed_state.update(decoded)
                self.last_confirmed_state = dict(self._observed_state)
        if not self.update_callback:
            return False
        updated = bool(self.update_callback(bytes(data)))
        if updated:
            self._state_update_event.set()
        return updated

    def notify_callback(self, sender: BleakGATTCharacteristic, data: bytearray):
        """Handle packets sent by the Fluval."""
        if self.raw_facebd:
            _LOGGER.debug("Got raw Fluval data: %s", to_hex(data))
            self._dispatch_update(bytes(data))
            return

        decrypted = decrypt(data)
        if len(decrypted) == 17:
            self.receive_buffer += decrypted
        else:
            self.receive_buffer += decrypted
            _LOGGER.debug("Got all data: %s ", to_hex(self.receive_buffer))
            self._dispatch_update(self.receive_buffer)
            self.receive_buffer = b""

    async def _connect(self):
        """Connect to the Fluval and subscribe to notifications."""
        connected = False
        try:
            client = await self._ensure_client()

            if self.wake_read_uuid:
                with contextlib.suppress(BleakError):
                    await client.read_gatt_char(self.wake_read_uuid)

            # FluvalConnect initializes every BLE light in this order after
            # notifications are enabled: set the fixture clock, read its
            # current parameters, then apply any state-dependent follow-up.
            if self.ready_callback:
                try:
                    await self.ready_callback()
                except Exception as err:  # pylint: disable=broad-except
                    _LOGGER.warning("Fluval pre-read initialization failed", exc_info=err)

            if self.raw_facebd:
                await self.request_state()
            elif self.init_write_uuid:
                await self._write_packet(self.init_write_uuid, protocol.old_read_params_packet())

            if self.state_ready_callback:
                try:
                    await self.state_ready_callback(dict(self._observed_state))
                except Exception as err:  # pylint: disable=broad-except
                    _LOGGER.warning("Fluval post-read initialization failed", exc_info=err)
            connected = True
        except (TimeoutError, BleakError) as err:
            _LOGGER.debug("Fluval initial connection failed", exc_info=err)
            if self.status_callback:
                self.status_callback(False)
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.warning("Unexpected Fluval initial connection error", exc_info=err)
            if self.status_callback:
                self.status_callback(False)
        finally:
            if not self._stopping and (connected or self._active_time == 0):
                self.ping()

    def send(self, data: bytes):
        """Send a packet to the Fluval."""
        # if send loop active - we change sending data
        self.send_time = time.time() + COMMAND_TIME
        self.send_data = bytearray(data)
        _LOGGER.debug("Queued Fluval packet: %s", to_hex(self.send_data))

        self.ping()

        if self.ping_future:
            self.ping_future.cancel()

    async def _ping_loop(self):
        """Ping the Fluval to keep connection."""
        loop = asyncio.get_event_loop()
        while time.time() < self.ping_time and not self._stopping:
            try:
                # Reconnect only after any command using the old link has
                # finished its failure handling. This also makes the heartbeat
                # the single owner of persistent reconnect cycles.
                async with self._command_lock:
                    client = await self._ensure_client()

                # heartbeat loop
                while time.time() < self.ping_time and not self._stopping and client is self.client:
                    if self.wake_read_uuid:
                        with contextlib.suppress(BleakError):
                            await client.read_gatt_char(self.wake_read_uuid)
                    if self.send_data:
                        if time.time() < self.send_time:
                            await self._write_packet(self.command_write_uuid, self.send_data)
                        self.send_data = None

                    # asyncio.sleep(10) with cancel
                    self.ping_future = loop.create_future()
                    loop.call_later(self._ping_interval, self.ping_future.cancel)
                    try:
                        await self.ping_future
                    except asyncio.CancelledError:
                        task = asyncio.current_task()
                        if task is not None and task.cancelling():
                            raise

                if self._stopping:
                    break
                if client is not self.client:
                    continue

                # Never let the idle deadline disconnect a command in flight.
                async with self._command_lock:
                    if time.time() < self.ping_time:
                        continue
                    await self._safe_disconnect()
            except TimeoutError:
                pass
            except asyncio.CancelledError:
                raise
            except BleakError as e:
                _LOGGER.debug("ping error", exc_info=e)
            except Exception as e:
                _LOGGER.warning("ping error", exc_info=e)
            if not self._stopping and time.time() < self.ping_time:
                await asyncio.sleep(1)

        self.ping_task = None

    async def _write_packet(self, uuid: str, data: bytes):
        """Write a packet using the right wire format for the active profile."""
        characteristic = self._get_characteristic(uuid)
        # Prefer write-without-response when available — matches ESPHome
        # fluval_ble_led and fixes Aquasky 2.0 lights that ignore response writes (#6).
        properties = set(characteristic.properties) if characteristic is not None else set()
        if "write-without-response" in properties:
            response = False
        elif "write" in properties:
            response = True
        else:
            response = False
        payloads: list[bytes | bytearray]
        if self.raw_facebd:
            # FluvalConnect packages raw FACEBD/SPP writes at MTU - 3. Native
            # Pro schedules can exceed the default 20-byte ATT payload and
            # must be delivered as consecutive chunks for the fixture to
            # reassemble them.
            chunk_size = 20
            characteristic_limit = getattr(characteristic, "max_write_without_response_size", None)
            if isinstance(characteristic_limit, int) and characteristic_limit > 0:
                chunk_size = characteristic_limit
            else:
                mtu_size = getattr(self.client, "mtu_size", None)
                if isinstance(mtu_size, int) and mtu_size > 3:
                    chunk_size = mtu_size - 3
            payloads = [data[offset : offset + chunk_size] for offset in range(0, len(data), chunk_size)]
        elif len(data) > 15:
            # The classic APK path chunks the complete plaintext frame to 15
            # bytes, then encrypts each slice independently.
            payloads = [encryption.encrypt(bytearray(data[offset : offset + 15])) for offset in range(0, len(data), 15)]
        else:
            payloads = [protocol.encrypted_old_packet(data)]

        for index, payload in enumerate(payloads):
            _LOGGER.debug(
                "Writing Fluval packet to %s response=%s chunk=%s/%s raw=%s encrypted=%s",
                uuid,
                response,
                index + 1,
                len(payloads),
                to_hex(data) if index == 0 else "(cont)",
                to_hex(payload),
            )
            await self.client.write_gatt_char(uuid, data=payload, response=response)
            if index + 1 < len(payloads):
                await asyncio.sleep(CHUNK_WRITE_GAP)

    async def request_state(self, expected_state: dict[int, object] | None = None) -> bool:
        """Read current controller state and optionally verify requested values."""
        client = await self._ensure_client()
        self._state_update_event.clear()
        self._observed_state = {}
        observed = False

        if self.wake_read_uuid:
            with contextlib.suppress(BleakError):
                await client.read_gatt_char(self.wake_read_uuid)

        if self.plant_pro_spp:
            await self._write_packet(
                self.command_write_uuid,
                protocol.SPP_READ_PARAMS_PACKET,
            )
        elif self.raw_facebd and self.notify_uuid:
            # Read every available FACEBD state char. Some controllers return
            # only a wake byte on facebd81 and the real CBOR map on facebd80/02.
            for read_uuid in self.state_read_uuids or [self.notify_uuid]:
                try:
                    data = await client.read_gatt_char(read_uuid)
                except BleakError as err:
                    _LOGGER.debug("Fluval state read failed from %s", read_uuid, exc_info=err)
                    continue
                _LOGGER.debug("Read Fluval state from %s: %s", read_uuid, to_hex(data))
                observed = self._dispatch_update(bytes(data)) or observed
        elif self.init_write_uuid:
            await self._write_packet(self.init_write_uuid, protocol.old_read_params_packet())

        if observed and self._state_matches(expected_state):
            return True
        with contextlib.suppress(TimeoutError):
            async with asyncio.timeout(STATE_NOTIFY_TIMEOUT):
                await self._state_update_event.wait()
        return self._state_update_event.is_set() and self._state_matches(expected_state)

    @property
    def observed_state(self) -> dict[int, object]:
        """Return the state collected by the most recent explicit read."""
        return dict(self._observed_state)

    def _state_matches(self, expected_state: dict[int, object] | None) -> bool:
        """Compare requested FACEBD values with state returned by the lamp."""
        if not expected_state:
            self.last_verification_mismatches = {}
            return True
        mismatches = {}
        for key, expected in expected_state.items():
            confirmed = self._observed_state.get(key)
            if confirmed != expected:
                mismatches[key] = {
                    "expected": expected,
                    "confirmed": confirmed,
                }
        self.last_verification_mismatches = mismatches
        return not mismatches

    def _command_gap(self) -> float:
        """Return the inter-command delay for the resolved GATT transport."""
        if self.profile == "legacy_encrypted":
            return CLASSIC_COMMAND_GAP
        return COMMAND_GAP

    async def send_now(
        self,
        data: bytes,
        *,
        expected_state: dict[int, object] | None = None,
        verify: bool = True,
    ) -> bool:
        """Connect and write a packet before returning to Home Assistant."""
        async with self._command_lock:
            try:
                self.last_write_targets = []
                self.last_write_verified = False
                self.last_expected_state = dict(expected_state or {})
                self.last_confirmed_state = {}
                self.last_verification_mismatches = {}
                client = await self._ensure_client()
                if self.wake_read_uuid:
                    with contextlib.suppress(BleakError):
                        await client.read_gatt_char(self.wake_read_uuid)

                wait_time = self.last_command_at + self._command_gap() - time.time()
                if wait_time > 0:
                    await asyncio.sleep(wait_time)

                write_copies = UNVERIFIED_WRITE_COPIES if verify and self.raw_facebd else 1
                for copy_attempt in range(1, write_copies + 1):
                    self._state_update_event.clear()
                    self._observed_state = {}
                    wrote_target = False
                    for attempt in range(1, WRITE_RETRIES + 1):
                        try:
                            await self._write_packet(self.command_write_uuid, data)
                        except (TimeoutError, BleakError, EOFError) as err:
                            self.last_error = (
                                f"write {self.command_write_uuid} attempt {attempt} failed: {type(err).__name__}: {err}"
                            )
                            _LOGGER.debug(
                                "Fluval BLE write target failed: %s attempt %s",
                                self.command_write_uuid,
                                attempt,
                                exc_info=err,
                            )
                            if attempt < WRITE_RETRIES:
                                await asyncio.sleep(WRITE_DELAY)
                        else:
                            wrote_target = True
                            self.last_write_targets.append(self.command_write_uuid)
                            break

                    if not wrote_target:
                        raise BleakError("No Fluval BLE write target accepted the command")

                    self.last_command_at = time.time()
                    if not verify or not self.raw_facebd:
                        break
                    await asyncio.sleep(POST_WRITE_STATE_DELAY)
                    self.last_write_verified = bool(
                        self._state_update_event.is_set() and self._state_matches(expected_state)
                    )
                    if not self.last_write_verified:
                        self.last_write_verified = await self.request_state(expected_state)
                    if self.last_write_verified:
                        break
                    if copy_attempt < write_copies:
                        await asyncio.sleep(WRITE_DELAY)

                _LOGGER.debug(
                    "Fluval write completed on targets=%s verified=%s",
                    self.last_write_targets,
                    self.last_write_verified,
                )

                # Keep the link warm briefly so HA can continue issuing commands
                # without reconnecting for every toggle.
                self.ping()

                self.last_error = None
                return True
            except (TimeoutError, BleakError, EOFError) as err:
                self.last_error = f"{type(err).__name__}: {err}"
                _LOGGER.warning("Fluval BLE write failed", exc_info=err)
            except Exception as err:  # pylint: disable=broad-except
                self.last_error = f"{type(err).__name__}: {err}"
                _LOGGER.warning("Unexpected Fluval BLE write failure", exc_info=err)

            if self.status_callback:
                self.status_callback(False)
            await self._safe_disconnect()
            return False

    async def _safe_disconnect(self):
        """Disconnect the underlying BLE client without masking the original error."""
        client = self.client
        self.client = None
        if client:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(client.disconnect(), timeout=5)
        if self.status_callback:
            self.status_callback(False)

    async def disconnect(self):
        """Disconnect from the Fluval while keeping this client reusable."""
        await self._async_disconnect(final=False)

    async def _async_disconnect(self, *, final: bool) -> None:
        """Disconnect and optionally prevent this client from being reused."""
        self._stopping = True
        self.ping_time = 0

        if self.ping_future:
            self.ping_future.cancel()

        if self.ping_task:
            self.ping_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, TimeoutError):
                await asyncio.wait_for(self.ping_task, timeout=3)
            self.ping_task = None

        if self.connect_task:
            self.connect_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, TimeoutError):
                await asyncio.wait_for(self.connect_task, timeout=3)
            self.connect_task = None

        with contextlib.suppress(Exception):
            await asyncio.wait_for(self._safe_disconnect(), timeout=6)

        if not final:
            self._stopping = False

    async def stop(self):
        """Permanently stop background work during integration unload."""
        await self._async_disconnect(final=True)


def encrypt(data: bytearray) -> bytearray:
    """Encrypt a packet for sending to Fluval."""
    return protocol.encrypted_old_packet(data)


def decrypt(data: bytearray) -> bytearray:
    """Decrypt a packet that has been received by the Fluval."""
    return encryption.decrypt(data)


def to_hex(data: bytes) -> str:
    """Print a byte array as hex strings for debugging."""
    return " ".join(format(x, "02x") for x in data)
