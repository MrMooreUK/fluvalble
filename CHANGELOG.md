# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

---

## [0.0.8] — 2026-08-30

### Added
- **Sync clock** button and automatic RTC sync on BLE connect (fixes #8, #25).
- AquaSky 3.0/FACEBD discovery, diagnostics, and write support (#22).
- Lovelace schedule, spectrum bar, and wavelength preview cards (#15).
- HA-managed schedule storage, auto mode, and physical preview services.
- ESP32 boards running ESPHome Bluetooth Proxy as a supported connection path.
- A Test LED Channels button that verifies power and each physical channel,
  records the results in Diagnostics, and restores the previous light state.
- Lamp profile option (`auto` / `plant` / `aquasky` / `aquasky3`) with tighter
  model detection and packet-based channel-count hints (#24, fixes #17).

### Changed
- Renamed channel 5 to Violet.
- Skip unchanged channel writes and throttle physical preview writes.
- Resolve every BLE connection through Home Assistant so it can automatically
  select the best available local adapter or ESPHome proxy.
- Keep schedule execution in Home Assistant's background scheduler so it does
  not depend on an open dashboard.

### Fixed
- Restore lowercase BLE characteristic UUIDs so ESPHome 2026.x / esp-idf 5.x
  Bluetooth proxies can look up GATT characteristics (regression of #7).
- Keep entity unique IDs and device identifiers uppercase so they stay stable
  if a proxy reports a mixed-case MAC address.
- FACEBD commands now use the hardware-verified command characteristic and
  confirm the requested state through the response characteristic.
- Retry and report unverified AquaSky writes instead of treating an accepted
  BLE write as proof that the fixture changed.
- Schedule preview stop/restore, live slider dragging, physical playback, and
  unavailable control behavior during BLE reconnects.
- Options Configure flow returning HTTP 500 (#18, fixes #16).
- Rediscovery of already-configured lamps caused by mixed-case unique IDs (#26).
- Old BLE AquaSky writes now prefer write-without-response and scale channels
  correctly (#20, related to #6).

### Security
- Harden schedule inputs and pin GitHub Actions to SHAs (#23).

### Notes
- AquaSky 3.0 control and state verification were validated on physical
  hardware through an ESPHome Bluetooth proxy.
- For issues with other Fluval lights, please open a GitHub issue with the
  model, Home Assistant version, diagnostics output, and relevant logs.

---

## [0.0.6] — 2026-06-08

### Added
- **`docs/bug-triage.md`** — internal triage document for the two
  currently-open bugs (#6 Aquasky 2.0 no response, #8 schedule drift
  after power cut), with what we know, what we need from reporters,
  and the workarounds to use in the meantime.
- **`CONTRIBUTING.md`** — contributor guidance (dev branch workflow,
  test expectations, local linting, release process).
- **`AGENTS.md`** — guidance for AI coding agents working in this repo
  (test commands, branch rules, what _not_ to change).
- **`.pre-commit-config.yaml`** — `ruff format` + `ruff check` run on
  every commit.
- **`mypy` in CI** — soft, non-gating static type-checking job.
  Reports existing type errors in the job log so progress is visible
  as the integration gains type hints.
- **`pytest-cov` in CI** — coverage report uploaded to Codecov when
  the `CODECOV_TOKEN` secret is configured. The job degrades
  gracefully without it.
- **`pyproject.toml` config** — `[tool.mypy]` and `[tool.coverage.*]`
  sections, with a 33% coverage floor.

---

## [0.0.5] — 2026-06-06

### Added
- **Light entity** — a master dimmer (`light.fluval_xxxx_light`) that turns the fixture
  on/off and sets overall brightness, scaling all channels together while preserving
  their relative ratios. Works with HA light cards, voice assistants, and light
  automations. The per-channel number sliders remain for fine control.

### Fixed
- **BLE client stays reusable after idle** — previously the client called
  `_safe_disconnect()` when the active window expired, leaving the device unavailable
  on some HA Bluetooth proxy setups until the config entry was reloaded. The client
  now stays alive; a subsequent command wakes and reconnects it automatically.
- **Ping restart guard** — `ping()` now returns immediately if the client has been
  stopped, preventing an accidental restart after the integration is unloaded.
- **Entity sync after channel change** — `updates_component` handlers (which push
  state to HA) now fire on every channel change, not only when switching modes.
  Previously, sliders in manual mode wouldn't update each other or the new light entity.

### Changed
- **Protocol constants** — command bytes (`CMD_HEADER`, `CMD_MODE`, `CMD_SWITCH`,
  `CMD_BRIGHTNESS`, `CMD_STATUS`) are now named constants in `core/__init__.py`
  instead of inline magic numbers, making the BLE command set self-documenting.

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
