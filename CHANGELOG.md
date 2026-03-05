# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [0.0.4] — 2026-03-05

### Fixed
- **Entity availability on disconnect** — switch, channel sliders and mode selector now
  correctly become _unavailable_ when the Fluval light goes offline (previously they
  stayed shown as available with stale values, misleading users into thinking commands
  were being sent).

### Added
- **Options flow** — after setup, open _Settings → Devices & Services → Fluval Aquarium
  LED → Configure_ to tune the keep-alive interval (5–60 s, default 10 s) and the
  active-connection window (30–600 s, default 120 s) without removing and re-adding
  the integration.
- **Entity icons** — switch shows `mdi:led-strip-variant`, channel sliders show
  `mdi:brightness-6`, and the mode selector shows `mdi:tune`.
- **Brightness sliders** — channel number entities now render as sliders in the HA UI
  instead of plain text input boxes (`NumberMode.SLIDER`).
- **Better device titles** — when a light is found via Bluetooth auto-discovery the
  entry title now uses the BLE advertised name (e.g. "Fluval Plant 3.0") instead of
  the raw MAC address.
- **Model detection** — device card in HA shows "Aquasky 2.0" or "Aquarium LED 3.0"
  based on the channel count detected from the first state packet.
- **`loggers` in manifest.json** — users can now enable debug-level logging for the
  integration via HA's _Logger_ UI (`Settings → System → Logs → Set custom logger`
  and choose `custom_components.fluvalble`).
- **`PARALLEL_UPDATES = 0`** — declared on all entity platforms (correct for
  push-based `local_push` integrations).
- **`domains` in hacs.json** — HACS now correctly associates the integration with
  its domain.
- **CI/CD** — GitHub Actions workflows for automated linting, testing, and release
  asset publishing.

---

## [0.0.3] — 2025-12-01

### Added
- Bluetooth auto-discovery — Home Assistant prompts to add the light when it is seen
  via BLE advertisement (no manual MAC entry required).
- Entity translation strings — proper names and state labels for all entities.
- Keep-alive reconnect loop — connection is automatically re-established after drops.
- BLE packet reassembly — correctly handles split Fluval notifications.

### Fixed
- Short-packet crash on malformed BLE notifications.
- `channel_5` entity incorrectly shown for 4-channel Aquasky 2.0 lamps.

---

## [0.0.2] — 2025-10-15

### Added
- Manual Bluetooth MAC address entry in the config flow.
- Discovered-device picker — lists nearby Fluval lights filtered by service UUID.
- Mode select entity (manual / automatic / professional).
- Binary sensor for BLE connection status (diagnostic category).

### Fixed
- Smart mode switching — channel brightness commands now automatically switch the
  lamp to manual mode first so changes take effect immediately.

---

## [0.0.1] — 2025-09-01

### Added
- Initial release.
- BLE client using `bleak` and `bleak-retry-connector`.
- Switch entity for LED on/off.
- Number entities for up to 5 brightness channels.
- AES-style packet encryption matching the Fluval/Planted Tank BLE protocol.
