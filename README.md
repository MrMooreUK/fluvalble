<p align="center">
  <img src="images/logo.png" alt="Fluval BLE — Aquarium LED lighting for Home Assistant" width="760"/>
</p>

<p align="center">
  <a href="https://github.com/MrMooreUK/fluvalble/actions/workflows/ci.yml"><img alt="CI" src="https://img.shields.io/github/actions/workflow/status/MrMooreUK/fluvalble/ci.yml?branch=main&style=for-the-badge&label=CI"></a>
  <a href="https://github.com/MrMooreUK/fluvalble/releases"><img alt="Release" src="https://img.shields.io/github/v/release/MrMooreUK/fluvalble?style=for-the-badge&label=release"></a>
  <a href="https://github.com/MrMooreUK/fluvalble/blob/main/LICENSE"><img alt="License" src="https://img.shields.io/badge/license-Apache%202.0-blue?style=for-the-badge"></a>
</p>

<p align="center">
  <strong>Premium local control for Fluval aquarium LED lights in Home Assistant.</strong><br/>
  No cloud. No vendor app dependency. Just Bluetooth, your tank, and automations that behave.
</p>

---

## Why Fluval BLE?

Fluval BLE turns compatible Fluval aquarium lights into first-class Home Assistant devices. Control power, colour, brightness, lighting modes, and connection health directly from your dashboard while keeping every command local over Bluetooth Low Energy.

---

## Features

| Feature | Description |
|--------|-------------|
| **Local-first control** | Talk directly to the LED fixture over BLE; no internet, cloud account, or app login required. |
| **Native light control** | Use Home Assistant's standard light card for power, brightness, colour, and supported controller-native effects. Product-specific FluvalConnect data translates the colour picker to the fixture's physical channels. |
| **Native effects** | Use the light card to select the weather and lighting effects supported by the detected fixture. |
| **Native fixture schedules** | Store Auto, Professional, and timed-effect schedules directly on supported fixtures so they continue running without Home Assistant. |
| **Daylight-saving control** | Supported fixtures expose their onboard daylight-saving setting as a configuration switch. |
| **Mode** | Select **Manual**, **Automatic**, or **Professional** from a dropdown. Setting a colour automatically switches the fixture to Manual mode. |
| **Reachability** | Shows whether the fixture was seen recently over BLE instead of treating an expected idle GATT disconnect as a failure. |
| **Auto-discovery** | Home Assistant detects nearby Fluval lights and prompts you to add them—no manual searching required. |
| **Bluetooth routing** | Works with local Bluetooth adapters and ESP32 boards running ESPHome Bluetooth Proxy. Home Assistant automatically selects the best connectable route on each connection. |

Entities are created per device around one native colour light, with mode and connection status alongside it. Everything updates from the device when it sends state, so the UI stays in sync.

---

## Supported devices

The integration recognizes the light catalogue defined by the current FluvalConnect APK, including:

- **Aquasky 2.0 and 3.0** (4-channel RGBW)
- **Plant 3.0, Plant 4.0, Plant Nano 4.0, and Plant PRO** (5 channels)
- **Marine/Reef 3.0, Reef 4.0, and Reef Nano 4.0** (5 channels)
- **Siena 2.0 and Roma & Shaker 2.0**
- First-generation **Wing Nano, Roma, Vicenza, Venezia, A-Sky Aqua, and Plant Aqua** fixtures

Information advertised by the light selects its FluvalConnect model, channel
layout, and available effects. An unidentified light uses a generic layout
until its fixture profile can be confirmed. See the
[technical reference](docs/technical-reference.md) for product and protocol
details.

---

## Requirements

- **Home Assistant 2024.1.0** or later with a working **Bluetooth** stack. This can be a local adapter or an ESP32 board running ESPHome Bluetooth Proxy.
- The Fluval light must be in range and powered on so it advertises over BLE.
- Your HA host (or the machine running the Bluetooth proxy) must be able to see the light in BLE scans.

No adapter selection is required in this integration. It asks Home Assistant for
the best currently connectable route, allowing HA to use or switch between a
local adapter and ESPHome Bluetooth proxies as signal and availability change.

---

## Installation

### Option A: HACS (recommended)

[![Open your Home Assistant instance and open this repository inside HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=MrMooreUK&repository=fluvalble&category=integration)

1. Ensure [HACS](https://hacs.xyz/) is installed.
2. In HACS: **Integrations** → **⋮** → **Custom repositories**.
3. Add: `https://github.com/MrMooreUK/fluvalble`
   Type: **Integration**.
4. Search for **Fluval Aquarium LED** or **Fluval BLE**, then install.
5. Restart Home Assistant.

### Option B: Manual

1. Download or clone this repo.
2. Copy the `custom_components/fluvalble` folder into your Home Assistant `custom_components` directory so you have:
   ```text
   config/
   └── custom_components/
       └── fluvalble/
           ├── __init__.py
           ├── manifest.json
           ├── config_flow.py
           ├── ...
   ```
3. Restart Home Assistant.

---

## Configuration

### Automatic (recommended)

When Home Assistant detects a Fluval light advertising over BLE, it will show a notification in **Settings → Devices & services** prompting you to set it up. Click **Configure**, confirm the device name, and the integration is ready.

### Manual

1. Go to **Settings** → **Devices & services** → **Add integration**.
2. Search for **Fluval Aquarium LED** (or **Fluval BLE**).
3. **Select your light** from the dropdown. The list shows only devices that look like Fluval lights (by Bluetooth service or name), so your aquarium light is easy to find. Ensure the light is **on** and in range before adding.
   - If your light appears: choose it and submit. The integration creates one device with a primary light entity, mode select, identify and clock-sync buttons, connection status, and diagnostic sensors.
   - If it's not in the list: choose **"My device isn't in the list — enter MAC address manually"**, then enter the MAC (e.g. `AA:BB:CC:DD:EE:FF`). You can find the MAC in your phone's Bluetooth settings or the Fluval app.
4. After setup, the light and supporting entities appear on the device. If you only see the integration card (for example, "Update") and no light entity, see [Troubleshooting](#troubleshooting) below.

No cloud account or app login is needed; the integration talks directly to the light over BLE.
When the product is identified, the device page uses FluvalConnect's model name
and channel layout. A manual lamp profile remains available for unidentified
fixtures. The firmware version also appears in standard device information when
the fixture reports it.

Redacted diagnostics can be downloaded from the integration or device page in
Home Assistant. The report retains protocol, profile, connection, command, and
schedule evidence while removing Bluetooth addresses, names, manufacturer and
service payloads, paths, and registry identifiers. Creating the report does not
disconnect, scan for, reconnect to, or send commands to the light.

### Connection options

Open the integration's **Configure** dialog to adjust its BLE connection behavior.
The **Active connection window** accepts `0` for a persistent connection or
`30`–`600` seconds for an idle timeout. Persistent mode provides the lowest
command latency and reconnects immediately after an unexpected drop. A finite
window releases the Bluetooth connection when idle so the official Fluval app
or a Fluval gateway can connect. The backward-compatible default is `120`
seconds. The **Connection mode** diagnostic reports `Persistent` or the exact
configured timeout, such as `30 seconds`.

Signal strength and the timestamp diagnostic remain registered but are disabled
in persistent mode because advertisement-derived values are not meaningful for
an open GATT session. Selecting a finite timeout and reloading the integration
restores those same entities, with their existing entity IDs and history.
Entities disabled manually by the user remain disabled. In finite mode,
the timestamp is shown as **Last seen** for the latest confirmed fixture
activity.

Some newer fixtures, including Plant PRO and Plant 4.0, permit only one
Bluetooth controller at a time. Persistent mode therefore prevents the official
app or gateway from connecting while Home Assistant holds the connection, and
it also continuously occupies one local-adapter or ESPHome proxy connection
slot.

---

## Lovelace dashboard cards

Optional dashboard cards are available for Auto and Professional schedule editing,
timed effects, fixture readback, and spectrum previews. See
[`docs/lovelace-cards.md`](docs/lovelace-cards.md) for setup instructions,
example YAML, usage notes, and preview safety guidance.

The cards label channels for the detected product, show whether schedule data is
local or confirmed by the fixture, and preview schedules without uploading
unsaved editor values.

## Native fixture schedules

Supported fixtures can keep schedules in their own memory. The integration
provides actions for Auto and Professional schedules, timed effects, manual
presets, and schedule previews under **Developer tools → Actions**. The action
UI contains the available fields, complete examples, and a Fluval light picker.
Existing automations and bundled cards that identify a light by config-entry ID
or Bluetooth address remain compatible.

Schedule previews use data already stored by the fixture and never upload
unsaved editor values. Using the normal light or Mode controls stops an active
preview automatically; the dedicated Stop preview action restores the prior
fixture mode.

Supported fixtures also expose their onboard daylight-saving setting. See the
[technical reference](docs/technical-reference.md) for controller limits,
readback behavior, and protocol details.

---

## Entities

After setup you'll see one device with entities like:

| Entity | Display name | Purpose |
|--------|-------------|---------|
| **Light** | Light | Power, brightness, colour, and supported native effects. |
| **Select** | Mode | Manual / Automatic / Professional. |
| **Button** | Identify | Runs the fixture's native FluvalConnect Find command so the physical light identifies itself. |
| **Binary sensor** | Reachable | Fixture seen recently over BLE; raw GATT connection state remains available as an attribute. |
| **Sensors** | Connection mode / Signal strength / Source / Last seen | Bluetooth diagnostics. Connection mode reports `Persistent` or the configured timeout. Signal strength and Last seen remain registered but are disabled in persistent mode; Source shows the active route's friendly name. |
| **Button** | Sync Clock | Synchronizes the fixture's real-time clock with Home Assistant. |
| **Switch** | Daylight saving time | Onboard setting available on supported AquaSky 3.0 fixtures. |

Entity IDs follow the pattern `<platform>.fluval_<mac_without_colons>_<name>`, for example `light.fluval_aabbccddeeff_light`. You can find the exact IDs in **Settings → Devices & services → Fluval Aquarium LED → entities**.
If a light, mode, daylight-saving, Identify, or Sync clock command cannot reach
the fixture, Home Assistant reports the BLE failure directly in the action UI
and automation trace rather than showing an apparent success.

---

## Example automations

**Turn the tank light on at sunrise and off at sunset**

```yaml
- id: fluval_morning
  alias: "Tank light on at sunrise"
  trigger:
    - platform: sun
      event: sunrise
  action:
    - service: light.turn_on
      target:
        entity_id: light.fluval_aabbccddeeff_light

- id: fluval_evening
  alias: "Tank light off at sunset"
  trigger:
    - platform: sun
      event: sunset
  action:
    - service: light.turn_off
      target:
        entity_id: light.fluval_aabbccddeeff_light
```

**Set a dim blue colour when you're away**

```yaml
- id: fluval_away_dim
  alias: "Dim tank light when away"
  trigger:
    - platform: state
      entity_id:
        - person.you
      to: "not_home"
  action:
    - service: light.turn_on
      target:
        entity_id: light.fluval_aabbccddeeff_light
      data:
        brightness_pct: 35
        rgb_color: [0, 80, 255]
```

**Notify if the light disconnects**

```yaml
- id: fluval_disconnect
  alias: "Tank light disconnected"
  trigger:
    - platform: state
      entity_id: binary_sensor.fluval_aabbccddeeff_reachable
      to: "off"
  action:
    - service: notify.mobile
      data:
        message: "Fluval tank light lost connection."
```

Replace `aabbccddeeff` with your device's MAC (without colons), and `person.you` / `notify.mobile` with your actual entity IDs and services.

---

## Troubleshooting

| Issue | What to try |
|-------|---------------------|
| **Integration not found** | Restart HA after installation. Ensure the `fluvalble` folder is directly under `custom_components`. |
| **Only see "Update" / "Pre-release", no light or entities** | The device wasn't in the Bluetooth cache when the integration loaded. Remove the integration (delete the config entry), ensure the light is **on** and in range, then add the integration again and select your light from the dropdown. Restart HA after updating the integration. |
| **Cannot connect / no entities** | Confirm the light is on and in BLE range. Check that HA has Bluetooth enabled and that the adapter can see other BLE devices. Verify the MAC address (no typos, correct format AA:BB:CC:DD:EE:FF). |
| **My light isn't in the dropdown** | Ensure the light is on and advertising. Use "My device isn't in the list" and enter the MAC manually (from phone Bluetooth settings or the Fluval app). |
| **Lamp connected but doesn't respond to actions** | Try the Fluval app first to confirm the light works. If the app works but HA doesn't, open an issue with your model and HA logs. |
| **ESPHome proxy is online but commands are unreliable** | Check Source for the adapter or proxy that owns the active connection, then check that proxy's Wi-Fi signal and scan settings. The integration asks HA for the best connectable route on reconnect; no adapter needs to be disabled manually. |
| **Light entity doesn't turn the fixture on/off** | Ensure the light model uses the same BLE command set. Try toggling once from the Fluval app, then again from HA. Restart HA and retry. |
| **Entities show "unavailable"** | The light may be out of range or off. Move the light or HA adapter closer; check Reachable, Last seen, and RSSI. An idle GATT disconnect is expected when a finite active connection window is configured. |
| **Colour or mode doesn't update** | Confirm that the detected model or selected lamp profile is correct, then retry in Manual mode. |
| **Colour control doesn't change the light** | Confirm the fixture works in the Fluval app, select Manual mode, and retry. If it still fails, download diagnostics from the Fluval integration or device page and include the report with your model when opening an issue. |

If you have a different Fluval BLE model and the light or other controls don't behave as expected, open an issue with your model name and (if possible) a note on what works in the official app.

---

## How it works

The integration uses Home Assistant's Bluetooth support to connect through a
local adapter or ESPHome Bluetooth proxy. Its controller protocols are based on
FluvalConnect and community reverse-engineering work, including the
[Fluval Plant 3.0 BLE protocol](https://www.plantedtank.net/threads/reverse-engineering-the-fluval-plant-3.0-ble-protocol.1325539/).
No data is sent to Fluval or any third party.

Detailed product, protocol, schedule, and connection behavior is documented in
the [technical reference](docs/technical-reference.md). Colour conversion and
its APK sources are documented separately in
[APK colour-control evidence](docs/apk-colour-evidence.md).

**BLE connection lifecycle:**
- Home Assistant selects the best connectable local adapter or ESPHome proxy on each connection.
- Persistent mode keeps the session open; finite mode releases it after the configured idle window.
- Reachable describes recent fixture activity rather than only the current GATT connection.
- Connection mode reports whether the GATT session is persistent or the exact idle timeout.
- Signal strength and Last seen are integration-disabled in persistent mode and restored for a finite timeout; Source shows the active route's friendly name.

---

## Credits & license

- Original integration structure and BLE work by [@mrzottel](https://github.com/mrzottel).
- Project maintenance and Home Assistant integration development by [@MrMooreUK](https://github.com/MrMooreUK).
- AquaSky 3 schedule-card work and ESPHome Bluetooth Proxy improvements by [@atomicalsoftwares](https://github.com/atomicalsoftwares).
- APK-backed product profiles, native controls, effects, schedules, and diagnostics contributed by [@Wheemer](https://github.com/Wheemer).
- Plant PRO Bluetooth protocol research and hardware validation by [@cryystyy](https://github.com/cryystyy/fluval-plant-pro-4-homeassistant), used under the MIT License.
- Community protocol research shared in the [Fluval Plant 3.0 BLE protocol discussion](https://www.plantedtank.net/threads/reverse-engineering-the-fluval-plant-3.0-ble-protocol.1325539/) and by the project's [contributors](https://github.com/MrMooreUK/fluvalble/graphs/contributors).
- Licensed under the **Apache License 2.0**. See [LICENSE](LICENSE) in this repo.

---

**Enjoy your smarter aquarium lighting.**

*This README is the integration's main documentation and is kept up to date with each release in this repo.*
