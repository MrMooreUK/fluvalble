# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

### Added
- Added product-aware wavelength previews backed by FluvalConnect's six current
  and legacy AquaSky, Plant, and Reef spectrum datasets. Five-channel previews
  now use the APK's real fifth curve instead of a synthetic approximation.
- Added APK-backed product-ID detection for Fluval advertisements. Classic
  fixtures now reconstruct the split ASCII product ID correctly (rather than
  mistaking the following firmware bytes for it), use the exact APK model name,
  and select the APK channel count when the lamp profile is Auto. Product
  identity is persisted for existing entries and now selects the APK's 0-, 4-,
  or 11-effect catalogue. Strict product-aware discovery covers the APK's
  classic ASCII prefixes and current binary FFF0 advertisements without
  accepting generic mesh devices.
- Added locally reported fixture firmware versions to standard Home Assistant
  device information for AquaSky 3.0/FACEBD and Plant Pro/MESH controllers.
- Added a FACEBD-only Daylight saving time configuration switch backed by
  FluvalConnect CBOR key 99. The entity follows fixture readback and never
  guesses or silently changes the controller's DST preference.
- Added APK-native preview controls for fixture-stored Auto and Professional
  schedules across classic (`680B`/`680C`), AquaSky 3.0/FACEBD (CBOR key 119),
  and Plant Pro/MESH (D1 CBOR key 51) controllers.
- Added a fixture-native Auto schedule editor to the dashboard card, including
  sunrise, sunset, optional sleep, ramp durations, and fixture-specific day and
  night channel levels. Loading Auto data remains an explicit action and does
  not overwrite the separate Professional editor.
- Added an optional timed-effects dashboard card that edits, validates, uploads,
  clears, and explicitly loads fixture-native effect windows while preserving a
  complete Home Assistant copy when classic readback is partial.
- Added APK-native timed weather-effect schedules for supported classic and
  AquaSky 3.0/FACEBD controllers, extending the existing Plant Pro action.
- Added the 11 APK-native weather effects to positively identified AquaSky
  3.0/FACEBD controllers through Home Assistant's standard light effect control.
- Added standard Home Assistant config-entry and device diagnostics downloads
  with recursive redaction and non-disruptive runtime snapshots.
- Added transport-neutral fixture-native Auto and Professional schedule support
  for classic, AquaSky 3.0/FACEBD, and Plant Pro/4.0 controllers using the
  FluvalConnect protocol layouts.
- Added explicit fixture schedule refresh/readback to the dashboard card. Native
  Professional curves are imported only when **Load from fixture** is selected,
  and the card identifies local, uploaded, and fixture-confirmed data.
- Added an optional persistent BLE connection mode (`0`-second active window)
  with immediate serialized recovery after unexpected disconnects.

### Changed
- Corrected five-channel FACEBD Auto schedules to retain the APK-provided fifth
  day and night level. Four-channel AquaSky schedule packets remain unchanged.
- Corrected five-channel FACEBD manual control and readback to include the APK's
  key 114 fifth channel. Four-channel AquaSky packets remain unchanged.
- Corrected APK-identified Marine and Reef fixtures to use Home Assistant's RGB
  light mode with a dedicated Pink/Cyan/Blue/Purple/Cold White translation,
  rather than treating their first four channels as AquaSky RGBW. A matching
  Marine/Reef manual lamp-profile override is also available.
- Normalized saved and fixture-native schedule payloads to positional
  `channel_1` through `channel_5` fields, with product-specific labels supplied
  from the APK-backed fixture profile. Existing RGB-style and Plant-specific
  field names remain accepted as compatibility aliases.
- Reduced classic encrypted BLE command pacing from 750 ms to the
  FluvalConnect APK's 200 ms affair-queue interval. FACEBD and Plant Pro/SPP
  retain their existing timing.
- Corrected fixture-native Professional schedule validation to match the
  FluvalConnect APK: 4–10 points for classic/OLD controllers and 4–12 for
  AquaSky 3.0/FACEBD and Plant Pro/MESH controllers.
- Replaced the active-session Connection binary sensor with Reachable, based on
  recent advertisements, successful connections, and successful commands. RSSI
  is now a measurement sensor with its advertisement timestamp exposed.
- Retired the duplicate LED switch now that the native light entity provides
  power control, and removed stale switch registry entries during config-entry
  setup.
- Replaced the recorder-backed diagnostics sensor and command-sending diagnostic
  buttons with Home Assistant's standard downloadable report. Collecting a
  report does not scan, connect, disconnect, refresh state, or send BLE commands.
- Remove stale registry entries for the retired Diagnostics, Refresh diagnostics,
  and Test LED channels entities during config-entry setup.
- Replaced the Home Assistant minute-by-minute schedule executor with fixture-native
  scheduling. Existing Auto curves are migrated once when they fit the detected
  controller's APK-defined point limits; other saved curves remain available in
  Manual mode for editing.
- BLE reconnects now replace stale clients, use one bounded connector retry
  cycle, and cannot race an in-flight command or integration unload.

### Added
- Plant Pro / Plant 4.0 core BLE support using its native unencrypted SPP
  transport for discovery, power, mode, five-channel colour, and live state.
- Plant Pro RTC synchronization using the FluvalConnect mesh clock command so
  fixture-owned schedules follow Home Assistant's local time.
- Four Plant Pro native effects through Home Assistant's standard light effect
  control, based on commands recovered from the FluvalConnect APK.
- Plant Pro fixture-owned Auto and Pro schedules, plus seven timed native-effect
  windows, with validated Home Assistant actions and diagnostics readback.

### Documentation
- Added a one-click HACS repository button and Plant Pro native schedule usage.

### Credits
- Plant Pro schedule protocol research and hardware validation by
  [@cryystyy](https://github.com/cryystyy/fluval-plant-pro-4-homeassistant).

---

## [0.0.11] — 2026-08-31

### Added
- APK-native weather effects for positively identified classic Fluval BLE
  controllers, exposed through Home Assistant's standard light effect control (#35).

### Changed
- Tightened Fluval BLE icon and logo to a flat bar-and-wave mark (#36).

---

## [0.0.10] — 2026-08-30

### Added
- Native Home Assistant RGBW control for AquaSky fixtures and RGB spectrum
  translation for Plant/Marine fixtures (#32).

### Changed
- Replaced the individual channel number entities with the standard light
  entity's colour and brightness controls. Existing channel entities are
  removed from the entity registry during config-entry setup (#32).

---

## [0.0.9] — 2026-08-30

### Fixed
- Require Fluval manufacturer data for classic discovery (#27).
- Restore lowercase BLE characteristic UUIDs for ESPHome 2026.x / esp-idf 5.x
  Bluetooth proxies and keep mixed-case MAC identifiers stable (#29).
- Treat manufacturer ID 12592 as Fluval vendor evidence for discovery, not
  FACEBD protocol evidence, so classic AquaSky 2.0 stays four-channel before
  GATT (#31).

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
