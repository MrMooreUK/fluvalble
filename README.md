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
| **Native light control** | Use Home Assistant's standard light card for power, brightness, colour, and supported controller-native effects. AquaSky fixtures expose RGBW; Plant, Plant Pro, and Marine spectra are translated to RGB. |
| **Weather effects** | Positively identified classic and AquaSky 3.0/FACEBD controllers expose the 11 native FluvalConnect weather effects, including lightning, colour cycle, cloud, and moon scenes. Selecting **None** restores the preceding static colour. |
| **Plant Pro effects** | Plant Pro / Plant 4.0 exposes its four native effects—Thunderstorm, Lightning, Sun and lightning, and Colour cycle—through the standard light effect control. |
| **Native fixture schedules** | Store Auto and Professional schedules directly in supported classic, AquaSky 3.0/FACEBD, and Plant Pro/4.0 controllers. The fixture follows its own clock; Home Assistant does not write channel levels every minute. |
| **Daylight-saving control** | FACEBD controllers expose their fixture-owned daylight-saving setting as a configuration switch, using the same state and command as FluvalConnect. |
| **Mode** | Select **Manual**, **Automatic**, or **Professional** from a dropdown. Setting a colour automatically switches the fixture to Manual mode. |
| **Reachability** | Shows whether the fixture was seen recently over BLE instead of treating an expected idle GATT disconnect as a failure. |
| **Auto-discovery** | Home Assistant detects nearby Fluval lights and prompts you to add them—no manual searching required. |
| **Bluetooth routing** | Works with local Bluetooth adapters and ESP32 boards running ESPHome Bluetooth Proxy. Home Assistant automatically selects the best connectable route on each connection. |

Entities are created per device around one native colour light, with mode and connection status alongside it. Everything updates from the device when it sends state, so the UI stays in sync.

---

## Supported devices

Designed for Fluval aquarium LED fixtures that use BLE (Bluetooth Low Energy), including series such as:

- **Plant 3.0** (5 channels)
- **Plant Pro / Plant 4.0** (5 channels)
- **Reef 3.0** (5 channels)
- **Aquasky 2.0 / 3.0** (4 channels)
- **Marine 3.0** (5 channels)
- Other 1st‑gen BLE Fluval LED lights

Your light must be controllable via the Fluval (e.g. FluvalSmart / FluvalConnect) app over Bluetooth. If the app can see and control it, this integration can too.

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
seconds.

Plant Pro / 4.0 permits only one BLE central at a time. Persistent mode therefore
prevents the official app or gateway from connecting while Home Assistant holds
the connection, and it also continuously occupies one local-adapter or ESPHome
proxy connection slot.

---

## Lovelace dashboard cards

Optional dashboard cards are available for Auto and Professional schedule editing,
fixture-native timed-effect windows, spectrum bar preview, and wavelength
preview. See
[`docs/lovelace-cards.md`](docs/lovelace-cards.md) for setup instructions,
example YAML, usage notes, and preview safety guidance.

The schedule card has separate **Auto** and **Professional** editors. Auto writes
the fixture's sunrise, sunset, optional sleep time, ramp durations, and day/night
channel levels, then activates Automatic mode. Professional offers **Manual** and
**Fixture native** modes; Fixture native uploads an APK-supported curve once:
4–10 points for classic/OLD controllers and 4–12 points for AquaSky 3.0/FACEBD
and Plant Pro/MESH. Manual disables the fixture's onboard schedule. Saved
schedules from the retired Home Assistant Auto executor are migrated to Fixture
native when they fit the controller limit. **Load from fixture** explicitly
refreshes and imports the reported schedule for the active editor without
silently replacing the other editor. Each editor labels its current data as
local, uploaded, or confirmed fixture readback.

**Preview fixture time** and **Play fixture schedule** use FluvalConnect's
native preview commands against the schedule already stored by the controller.
They never upload unsaved editor values. Classic controllers receive their
dedicated preview-level frames; FACEBD and Plant Pro controllers evaluate the
stored schedule for the requested minute themselves. **Stop preview** sends the
APK stop command and restores the fixture's prior mode.

The separate timed-effects card writes the same onboard effect windows exposed
by `fluvalble.set_native_effect_schedule`. It limits the effect picker to the
connected controller's supported catalog, prevents assigning a weekday to more
than one window, and keeps the complete submitted schedule in Home Assistant.
Classic controller readback is identified as partial because its normal state
response exposes only one timed-effect slot.

### Native fixture schedules

Supported classic, AquaSky 3.0/FACEBD, and Plant Pro/4.0 controllers can keep
schedules in the fixture itself. The integration provides actions under
**Developer tools → Actions**:

- `fluvalble.set_native_auto_schedule` stores sunrise, sunset, optional sleep,
  ramp duration, and day/night channel levels.
- `fluvalble.set_native_pro_schedule` stores 4–10 classic/OLD or 4–12
  FACEBD/MESH timed channel points, matching FluvalConnect.
- `fluvalble.set_native_effect_schedule` stores up to seven timed effect
  windows on supported classic, AquaSky 3.0/FACEBD, and Plant Pro controllers;
  passing an empty `windows` list clears them. Classic and FACEBD fixtures use
  the 11 weather effects, while Plant Pro uses its four-effect subset. Matching
  FluvalConnect, each weekday can belong to only one effect window.
- `fluvalble.preview_native_schedule` previews one minute from an Auto or
  Professional schedule already confirmed by fixture readback. Use
  `fluvalble.stop_preview` to stop and restore the prior fixture mode.

The action UI contains complete examples and field descriptions. These actions
use the protocol identified by the live BLE connection. Fixture readback is
included in the downloadable diagnostics report where the controller reports it.
Classic status readback exposes only its single embedded effect slot even when
the fixture was sent a longer schedule; the submitted schedule remains recorded
in diagnostics without being misrepresented as fixture-confirmed readback.

FACEBD fixtures also expose a **Daylight saving time** configuration switch once
the controller reports CBOR key `99`. This switch changes only the fixture's
own DST flag. Clock synchronization continues to send the Home Assistant host's
current UTC offset and Unix time using keys `101` and `102`; the integration
does not add or subtract another hour and never silently changes the DST flag.

---

## Entities

After setup you'll see one device with entities like:

| Entity | Display name | Purpose |
|--------|-------------|---------|
| **Light** | Light | Native power, brightness, colour, and supported effects. AquaSky uses RGBW; Plant, Plant Pro, and Marine spectra use RGB translation. |
| **Select** | Mode | Manual / Automatic / Professional. |
| **Button** | Identify | Runs the fixture's native FluvalConnect Find command so the physical light identifies itself. |
| **Binary sensor** | Reachable | Fixture seen recently over BLE; raw GATT connection state remains available as an attribute. |
| **Sensors** | Signal strength / Last seen | Advertisement RSSI, its observation time, and the latest successful BLE activity. |
| **Button** | Sync Clock | Synchronizes the fixture's real-time clock with Home Assistant. |
| **Switch** | Daylight saving time | FACEBD-only fixture DST setting, available after confirmed controller readback. |

Entity IDs follow the pattern `<platform>.fluval_<mac_without_colons>_<name>`, for example `light.fluval_aabbccddeeff_light`. You can find the exact IDs in **Settings → Devices & services → Fluval Aquarium LED → entities**.

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
      entity_id: binary_sensor.fluval_aabbccddeeff_connection
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
| **ESPHome proxy is online but commands are unreliable** | Check the proxy's Wi-Fi signal and place it closer to the light. The integration asks HA for the best connectable adapter or ESPHome proxy on reconnect; no adapter needs to be disabled manually. Download diagnostics from the Fluval integration or device page and include the report when opening an issue. |
| **Light entity doesn't turn the fixture on/off** | Ensure the light model uses the same BLE command set. Try toggling once from the Fluval app, then again from HA. Restart HA and retry. |
| **Entities show "unavailable"** | The light may be out of range or off. Move the light or HA adapter closer; check Reachable, Last seen, and RSSI. An idle GATT disconnect is expected when a finite active connection window is configured. |
| **Colour or mode doesn't update** | Some firmware reports only its physical channel levels. Plant/Marine RGB is therefore an approximation when the colour was changed outside Home Assistant. |
| **Colour control doesn't change the light** | Confirm the fixture works in the Fluval app, select Manual mode, and retry. If it still fails, download diagnostics from the Fluval integration or device page and include the report with your model when opening an issue. |

If you have a different Fluval BLE model and the light or other controls don't behave as expected, open an issue with your model name and (if possible) a note on what works in the official app.

---

## How it works

The integration uses Home Assistant's Bluetooth support to connect to the Fluval light through either a local adapter or an ESPHome Bluetooth proxy. Commands (on/off, brightness, mode) are sent as small BLE packets; the encryption scheme for legacy controllers is based on reverse‑engineered protocols used by Fluval's own app and community projects (e.g. [Fluval Plant 3.0 BLE protocol](https://www.plantedtank.net/threads/reverse-engineering-the-fluval-plant-3.0-ble-protocol.1325539/)). Plant Pro / 4.0 controllers use the newer unencrypted `FFF0` SPP service with `D1` command and `D2` status CBOR frames. No data is sent to Fluval or any third party—everything stays between your HA instance, Bluetooth route, and fixture.

**BLE connection lifecycle:**
- On load and reconnect, the integration asks HA for its best connectable BLE route. This includes local adapters and ESPHome Bluetooth proxies.
- A keep-alive loop pings the light every 10 seconds to maintain the connection and flush any queued commands.
- Persistent mode (`0`) keeps the session open and immediately starts one serialized reconnect cycle if the link drops.
- Finite mode cleanly closes the connection after the configured idle window; the default remains 2 minutes.
- Reachable remains on for five minutes after an advertisement, successful connection, or successful command. RSSI comes only from advertisements, so it may remain unchanged while a connected controller is not advertising.
- Each reconnect uses a fresh BLE client and the current HA-selected route.

---

## Credits & license

- Original integration structure and BLE work by [@mrzottel](https://github.com/mrzottel).
- Community reverse‑engineering of the Fluval BLE protocol (e.g. Planted Tank Forum, ESPHome/fluval projects).
- Plant Pro / 4.0 SPP protocol research and hardware validation by [@cryystyy](https://github.com/cryystyy/fluval-plant-pro-4-homeassistant), used under the MIT License.
- Licensed under the **Apache License 2.0**. See [LICENSE](LICENSE) in this repo.

---

**Enjoy your smarter aquarium lighting.**

*This README is the integration's main documentation and is kept up to date with each release in this repo.*
