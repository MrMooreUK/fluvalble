# Fluval BLE

**Control your Fluval aquarium LED lights from Home Assistant—no cloud, no app, just local Bluetooth.**

Turn lights on and off, adjust channel brightness, switch modes (Manual / Automatic / Professional), and monitor connection status. All communication is over BLE between your Home Assistant host and the light; no internet or vendor apps required.

---

## Features

| Feature | Description |
|--------|-------------|
| **Power** | Turn the LED fixture on or off via a switch entity. |
| **Channels** | Five brightness sliders (0–1000) for manual control of each channel. |
| **Mode** | Select **Manual**, **Automatic**, or **Professional** from a dropdown. |
| **Connection** | Binary sensor shows when the light is connected over BLE (RSSI and last seen in attributes). |

Entities are created per device: one switch, one connection sensor, one mode select, and five number entities for the channels. Everything updates from the device when it sends state, so the UI stays in sync.

---

## Supported devices

Designed for Fluval aquarium LED fixtures that use BLE (Bluetooth Low Energy), including series such as:

- **Plant 3.0**
- **Reef 3.0**
- **Aquasky 2.0 / 3.0**
- **Marine 3.0**
- Other 1st‑gen BLE Fluval LED lights

Your light must be controllable via the Fluval (e.g. FluvalSmart / FluvalConnect) app over Bluetooth. If the app can see and control it, this integration can too.

---

## Requirements

- **Home Assistant** with a working **Bluetooth** stack (built-in or add-on Bluetooth adapter).
- The Fluval light must be in range and powered on so it advertises over BLE.
- Your HA host (or the machine running the Bluetooth proxy) must be able to see the light in BLE scans.

---

## Installation

### Option A: HACS (recommended)

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

1. Go to **Settings** → **Devices & services** → **Add integration**.
2. Search for **Fluval Aquarium LED** (or **Fluval BLE**).
3. Enter the **MAC address** of your Fluval light.
   - You can find it in your phone’s Bluetooth settings while the light is on and in pairing/discoverable mode, or from the Fluval app if it shows the device address.
   - Format: `AA:BB:CC:DD:EE:FF` (colons optional in some setups).
4. Submit. The integration will create one device with all entities.

No cloud account or app login is needed; the integration talks directly to the light over BLE.

---

## Entities

After setup you’ll see one device with entities like:

| Entity type | Purpose |
|-------------|--------|
| **Switch** | `switch.fluval_xxxx_led_on_off` — Turn the light on or off. |
| **Numbers** | `number.fluval_xxxx_channel_1` … `channel_5` — Brightness 0–1000 per channel (manual mode). |
| **Select** | `select.fluval_xxxx_mode` — Manual / Automatic / Professional. |
| **Binary sensor** | `binary_sensor.fluval_xxxx_connection` — Connection status (diagnostic). |

Replace `fluval_xxxx` with your device’s unique ID (derived from MAC). Add them to dashboards, use in automations, or expose to Google Home / Apple Home via the HA bridges.

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
        entity_id: switch.fluval_xxxx_led_on_off

- id: fluval_evening
  alias: "Tank light off at sunset"
  trigger:
    - platform: sun
      event: sunset
  action:
    - service: switch.turn_off
      target:
        entity_id: switch.fluval_xxxx_led_on_off
```

**Dim the light when you’re away**

```yaml
- id: fluval_away_dim
  alias: "Dim tank light when away"
  trigger:
    - platform: state
      entity_id:
        - person.you
      to: "not_home"
  action:
    - service: number.set_value
      target:
        entity_id: number.fluval_xxxx_channel_1
      data:
        value: 200
```

**Notify if the light disconnects**

```yaml
- id: fluval_disconnect
  alias: "Tank light disconnected"
  trigger:
    - platform: state
      entity_id: binary_sensor.fluval_xxxx_connection
      to: "off"
  action:
    - service: notify.mobile
      data:
        message: "Fluval tank light lost connection."
```

Replace `fluval_xxxx` and `person.you` / `notify.mobile` with your actual entity IDs and services.

---

## Troubleshooting

| Issue | What to try |
|-------|---------------------|
| **Integration not found** | Restart HA after installation. Ensure the `fluvalble` folder is directly under `custom_components`. |
| **Cannot connect / no entities** | Confirm the light is on and in BLE range. Check that HA has Bluetooth enabled and that the adapter can see other BLE devices. Verify the MAC address (no typos, correct format). |
| **Switch doesn’t turn light on/off** | Ensure the light model uses the same BLE command set (e.g. CMD_SWITCH). Try toggling once from the Fluval app, then again from HA. Restart HA and retry. |
| **Entities show “unavailable”** | The light may be out of range, off, or the BLE connection dropped. Move the light or HA adapter closer; check the connection binary sensor and RSSI. |
| **Channels or mode don’t update** | Some features (e.g. mode change) may require the device to send state back; if the firmware doesn’t report mode, the dropdown may not reflect external changes. |

If you have a different Fluval BLE model and the switch or other controls don’t behave as expected, open an issue with your model name and (if possible) a note on what works in the official app.

---

## How it works

The integration uses Home Assistant’s Bluetooth support to connect to the Fluval light. Commands (on/off, brightness, mode) are sent as small encrypted BLE packets; the encryption scheme is based on reverse‑engineered protocols used by Fluval’s own app and community projects (e.g. [Fluval Plant 3.0 BLE protocol](https://www.plantedtank.net/threads/reverse-engineering-the-fluval-plant-3-0-ble-protocol.1325539/)). No data is sent to Fluval or any third party—everything stays between your HA instance and the fixture.

---

## Credits & license

- Original integration structure and BLE work by [@mrzottel](https://github.com/mrzottel).
- Community reverse‑engineering of the Fluval BLE protocol (e.g. Planted Tank Forum, ESPHome/fluval projects).
- Licensed under the **Apache License 2.0**. See [LICENSE](LICENSE) in this repo.

---

**Enjoy your smarter aquarium lighting.**
