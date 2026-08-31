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
| **Classic weather effects** | Positively identified classic controllers expose the 11 native FluvalConnect weather effects, including lightning, colour cycle, cloud, and moon scenes. Selecting **None** restores the preceding static colour. |
| **Plant Pro effects** | Plant Pro / Plant 4.0 exposes its four native effects—Thunderstorm, Lightning, Sun and lightning, and Colour cycle—through the standard light effect control. |
| **Plant Pro fixture schedules** | Store native Auto, Pro, and timed-effect schedules directly in Plant Pro / Plant 4.0 fixtures with Home Assistant actions. |
| **Mode** | Select **Manual**, **Automatic**, or **Professional** from a dropdown. Setting a colour automatically switches the fixture to Manual mode. |
| **Connection health** | Binary sensor shows BLE connection status, with RSSI and last-seen attributes for troubleshooting. |
| **Auto-discovery** | Home Assistant detects nearby Fluval lights and prompts you to add them—no manual searching required. |
| **Bluetooth routing** | Works with local Bluetooth adapters and ESP32 boards running ESPHome Bluetooth Proxy. Home Assistant automatically selects the best connectable route on each connection. |
| **Channel test** | A diagnostic button tests power and each physical LED channel, verifies the state returned by supported controllers, and restores the previous light state. |

Entities are created per device around one native colour light, with mode, connection, and diagnostic controls alongside it. Everything updates from the device when it sends state, so the UI stays in sync.

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
   - If your light appears: choose it and submit. The integration creates one device with the switch, channels, mode select, and connection sensor.
   - If it's not in the list: choose **"My device isn't in the list — enter MAC address manually"**, then enter the MAC (e.g. `AA:BB:CC:DD:EE:FF`). You can find the MAC in your phone's Bluetooth settings or the Fluval app.
4. After setup, the switch and other entities appear on the device. If you only see the integration card (e.g. "Update" / "Pre-release") and no switch, see [Troubleshooting](#troubleshooting) below.

No cloud account or app login is needed; the integration talks directly to the light over BLE.

---

## Lovelace dashboard cards

Optional dashboard cards are available for AquaSky 3.0 schedule editing,
spectrum bar preview, and wavelength preview. See
[`docs/lovelace-cards.md`](docs/lovelace-cards.md) for setup instructions,
example YAML, usage notes, and preview safety guidance.

### Plant Pro native schedules

Plant Pro / Plant 4.0 can keep schedules in the fixture itself, independently
of Home Assistant's existing saved schedule and dashboard card. The integration
provides three actions under **Developer tools → Actions**:

- `fluvalble.set_native_auto_schedule` stores sunrise, sunset, optional sleep,
  ramp duration, and five-channel day/night levels.
- `fluvalble.set_native_pro_schedule` stores 1–20 timed five-channel points.
- `fluvalble.set_native_effect_schedule` stores up to seven effect windows;
  passing an empty `windows` list clears them.

The action UI contains complete examples and field descriptions. These actions
are rejected unless the live BLE connection identifies the Plant Pro SPP
transport. Fixture readback is shown in the Diagnostics entity attributes.

---

## Entities

After setup you'll see one device with entities like:

| Entity | Display name | Purpose |
|--------|-------------|---------|
| **Light** | Light | Native power, brightness, colour, and supported effects. AquaSky uses RGBW; Plant, Plant Pro, and Marine spectra use RGB translation. |
| **Switch** | LED | Turn the light on or off. |
| **Select** | Mode | Manual / Automatic / Professional. |
| **Binary sensor** | Connection | BLE connection status (diagnostic). RSSI and last-seen time in attributes. |
| **Button** | Test LED Channels | Tests power and each supported channel, records verification details in Diagnostics, then restores the prior state. |

Entity IDs follow the pattern `<platform>.fluval_<mac_without_colons>_<name>`, for example `switch.fluval_aabbccddeeff_led_on_off`. You can find the exact IDs in **Settings → Devices & services → Fluval Aquarium LED → entities**.

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
    - service: switch.turn_on
      target:
        entity_id: switch.fluval_aabbccddeeff_led_on_off

- id: fluval_evening
  alias: "Tank light off at sunset"
  trigger:
    - platform: sun
      event: sunset
  action:
    - service: switch.turn_off
      target:
        entity_id: switch.fluval_aabbccddeeff_led_on_off
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
| **Only see "Update" / "Pre-release", no switch or entities** | The device wasn't in the Bluetooth cache when the integration loaded. Remove the integration (delete the config entry), ensure the light is **on** and in range, then add the integration again and select your light from the dropdown. Restart HA after updating the integration. |
| **Cannot connect / no entities** | Confirm the light is on and in BLE range. Check that HA has Bluetooth enabled and that the adapter can see other BLE devices. Verify the MAC address (no typos, correct format AA:BB:CC:DD:EE:FF). |
| **My light isn't in the dropdown** | Ensure the light is on and advertising. Use "My device isn't in the list" and enter the MAC manually (from phone Bluetooth settings or the Fluval app). |
| **Lamp connected but doesn't respond to actions** | Try the Fluval app first to confirm the light works. If the app works but HA doesn't, open an issue with your model and HA logs. |
| **ESPHome proxy is online but commands are unreliable** | Check the proxy's Wi-Fi signal and place it closer to the light. The integration asks HA for the best connectable adapter or ESPHome proxy on reconnect; no adapter needs to be disabled manually. Run **Test LED Channels** and inspect the Diagnostics sensor for `verified`, `confirmed_state`, and any mismatches. |
| **Switch doesn't turn light on/off** | Ensure the light model uses the same BLE command set. Try toggling once from the Fluval app, then again from HA. Restart HA and retry. |
| **Entities show "unavailable"** | The light may be out of range, off, or the BLE connection dropped. Move the light or HA adapter closer; check the connection binary sensor and RSSI. |
| **Colour or mode doesn't update** | Some firmware reports only its physical channel levels. Plant/Marine RGB is therefore an approximation when the colour was changed outside Home Assistant. |
| **Colour control doesn't change the light** | Confirm the fixture works in the Fluval app, select Manual mode, and retry. If it still fails, run **Test LED Channels** and include the Diagnostics result with your model when opening an issue. |

If you have a different Fluval BLE model and the switch or other controls don't behave as expected, open an issue with your model name and (if possible) a note on what works in the official app.

---

## How it works

The integration uses Home Assistant's Bluetooth support to connect to the Fluval light through either a local adapter or an ESPHome Bluetooth proxy. Commands (on/off, brightness, mode) are sent as small BLE packets; the encryption scheme for legacy controllers is based on reverse‑engineered protocols used by Fluval's own app and community projects (e.g. [Fluval Plant 3.0 BLE protocol](https://www.plantedtank.net/threads/reverse-engineering-the-fluval-plant-3.0-ble-protocol.1325539/)). Plant Pro / 4.0 controllers use the newer unencrypted `FFF0` SPP service with `D1` command and `D2` status CBOR frames. No data is sent to Fluval or any third party—everything stays between your HA instance, Bluetooth route, and fixture.

**BLE connection lifecycle:**
- On load and reconnect, the integration asks HA for its best connectable BLE route. This includes local adapters and ESPHome Bluetooth proxies.
- A keep-alive loop pings the light every 10 seconds to maintain the connection and flush any queued commands.
- If the connection drops, the integration retries and refreshes the HA-selected route before reconnecting.
- The connection is cleanly closed after 2 minutes of inactivity (no commands sent).

---

## Credits & license

- Original integration structure and BLE work by [@mrzottel](https://github.com/mrzottel).
- Community reverse‑engineering of the Fluval BLE protocol (e.g. Planted Tank Forum, ESPHome/fluval projects).
- Plant Pro / 4.0 SPP protocol research and hardware validation by [@cryystyy](https://github.com/cryystyy/fluval-plant-pro-4-homeassistant), used under the MIT License.
- Licensed under the **Apache License 2.0**. See [LICENSE](LICENSE) in this repo.

---

**Enjoy your smarter aquarium lighting.**

*This README is the integration's main documentation and is kept up to date with each release in this repo.*
