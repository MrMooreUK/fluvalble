# Native local Wi-Fi (experimental)

This is a direct fixture-to-broker transport for **AquaSky 3.0, product 532**.
It is not cloud MQTT, an ESP32 BLE bridge, or Wi-Fi support for Plant 3.0.
No BLE operational command bytes, encryption, or existing colour translations
are changed. Home Assistant's MQTT integration owns the broker connection.
There are no new integration runtime requirements or minimum-HA-version changes.

## Switching an existing fixture

For first-time setup, select Bluetooth control mode in FluvalConnect and close
the app without deleting the light. Add the fixture to HA over Bluetooth if
needed. Choose **Configure → Fixture connection → Set up Local Wi-Fi over
Bluetooth**. An active ESPHome Bluetooth proxy can carry the GATT connection;
no separate computer or script is required. Enter the fixture Wi-Fi details and
the local MQTT broker details, then confirm replacement of the fixture settings.
HA reads the Wi-Fi address from the fixture and saves the new transport only
after a fresh MQTT state response. A failed attempt can still have changed the
fixture's saved settings. Rerun Wi-Fi setup in FluvalConnect to restore official
app Wi-Fi control. Proxy provisioning and recovery still need hardware testing.

For a fixture already provisioned to the local broker:

1. Configure Home Assistant's MQTT integration with a **local** broker reachable
   by both HA and the fixture. This integration does not install a broker.
2. Explicitly provision the fixture to that broker (below). This can replace its
   vendor broker configuration and interrupt Fluval Connect Wi-Fi access.
3. In the existing Fluval entry, choose **Configure → Fixture connection → Local
   Wi-Fi**, then enter the fixture's **Wi-Fi MAC**, not its BLE address.
4. The entry reloads using local MQTT. Its original Bluetooth address remains
   the stable entity/storage identity. No second device should be added.
5. To use BLE again, choose **Bluetooth** in the same form. This changes only HA's
   selected transport, not the fixture's saved broker or network credentials.

New entries collect both identities for the same reason. Do not derive one MAC
from the other: use the actual Wi-Fi identity/topic reported by the fixture.
Home Assistant and the fixture must use the **same broker**. There is no host or
cloud-account password field in the integration; HA retains its own broker login.

## Explicit provisioning tool

The standalone `scripts/provision_native_mqtt.py` tool is not run by setup,
reload, discovery or control. Run it only with explicit authorization and a
product-532 fixture available for validation. It requires a Python environment
with Bleak and access to a Bluetooth adapter near the fixture. An HA ESPHome
proxy is not automatically a local Bleak adapter for this standalone tool.

```sh
python scripts/provision_native_mqtt.py \
  --ble-address AA:BB:CC:DD:EE:01 \
  --ssid AquariumNetwork \
  --broker mqtt.lan --port 1883 \
  --client-id aquarium-532 --username aquarium \
  --confirm-broker-change
```

Passwords are prompted without echo, not passed in argv or written to disk.
The tool waits for `ip:...;;`, then `mqtt:connected;;`. It does not print raw
firmware responses, which could contain credentials, and does not flash firmware.
If the fixture reports its Wi-Fi identity it is shown; otherwise identify its
exact native uplink topic on your broker. Success here means only the fixture
reported a broker connection, not that lighting control has been validated.

The tool deliberately rejects non-ASCII fields and `:`/`;` delimiters rather than
inventing an escaping scheme absent from the recovered parser. Tool bounds are
conservative; they are not claims about every firmware's buffer capacities.
The firmware's reviewed saved-broker path uses **plain MQTT/TCP**, not TLS. Use
a trusted LAN, a dedicated broker account and per-fixture ACLs; never expose
this listener to the Internet. Give the fixture publish access to its uplink
and subscribe access to its downlink; HA needs the reverse permissions.
During provisioning, Wi-Fi and broker credentials cross BLE without
application-layer encryption. Limit provisioning to a trusted setting.
Any client allowed to publish to the fixture's uplink can spoof its state;
restrict uplink publish permission to that fixture and downlink publish
permission to Home Assistant.

Returning HA to BLE does not restore the original cloud broker. Returning the
fixture to official-app Wi-Fi operation requires deliberately configuring it
again through the official app. That recovery path has not been hardware-tested
as part of this implementation. Do not provision an unattended aquarium first.

## Recovered protocol, not cloud emulation

FluvalConnect **1.0.15 / versionCode 110**:

This is a community integration and is not affiliated with Fluval or Rolf C. Hagen.

| Source | Evidence |
| --- | --- |
| `LightDetailActivity.initWifiMqtt`, lines 1848–1865 | `cyd/dev/Fluval/Fluval-532/<UPPERCASE_WIFI_MAC_NO_COLONS>/downlink` and `/uplink` |
| `LightInstructionsKxtKt`, lines 65–80 and command builders | `id:<number>;type:property_get;;` and `id:<number>;type:property_set;param:<hex CBOR>;;` |
| `MqttHelper.nextTo532`, lines 577–590 | Native text envelope, `param` hex decoded into the shared CBOR parser |
| `LightSettingActivity`, lines 701–773 | FACEBD80 network credentials, then configurable host/port/client ID/user/password; `ip` and `mqtt:connected` responses |
| `BleKxtKt.sendDataToWifi`, lines 197–226 | UTF-8 frames, ATT-sized chunks, 5 ms gap, prefer write-without-response when advertised |

Static inspection of Fluval532 firmware v1.0.10 supports the saved-broker setup
and MQTT envelope described above. The fixture uses `0.pool.ntp.org`; reliable
clock and schedule recovery after a power cut without Internet is unverified.
Check the fixture clock before relying on schedules after an offline reboot.

Prefer a dedicated IoT VLAN where practical. Permit the fixture to reach its
broker and required network services; keep the MQTT listener off the Internet.
Use dedicated accounts and exact-topic ACLs. For example, in a Mosquitto ACL
file, substitute the fixture's uppercase Wi-Fi MAC without separators:

```text
user aquarium_fixture
topic write cyd/dev/Fluval/Fluval-532/AABBCCDDEE02/uplink
topic read cyd/dev/Fluval/Fluval-532/AABBCCDDEE02/downlink

user home_assistant
topic read cyd/dev/Fluval/Fluval-532/AABBCCDDEE02/uplink
topic write cyd/dev/Fluval/Fluval-532/AABBCCDDEE02/downlink
```

These are per-fixture rules, not a replacement for any unrelated HA ACLs.
Clients with downlink write access can send device commands, including a
firmware update URL. The integration does not send firmware update commands.

`DeviceDataKt.wifiLightList` is `0532`: this APK identifies AquaSky 3.0 as
the native Wi-Fi light family. Only product 532 is enabled for native MQTT;
Bluetooth Mesh networking is outside this change.

## Runtime behaviour and validation boundary

The adapter subscribes before reading, rejects retained/malformed/oversized
messages as live evidence, accumulates split CBOR state, requires fresh readback
for verified writes, and retries only initialization reads, not writes. It reads
state every 30 seconds. Availability is based on fixture responses, not merely
the broker being connected. Unload removes only this entry's subscriptions and
poll task; it never disconnects HA's shared MQTT client.

BLE RSSI and proxy-source entities are not fabricated. Existing rows are
integration-disabled while on MQTT, then re-enabled when returning to BLE,
unless the user disabled them independently. Manual settings and the hardware
schedule editor use the same existing state machine and CBOR builders.

Offline tests cover envelope validation, read/write confirmation, split maps,
broker failure, stop during a read, identity preservation and switching. They
do **not** prove physical behaviour. Before publishing as supported, validate:

- explicit provisioning and correct Wi-Fi MAC/topic on a real product-532 light;
- reads, power, individual channels, modes, native effects and schedules;
- reload, broker outage/reconnect and fixture reboot persistence;
- WAN-blocked operation and egress capture, including time behaviour;
- switching back to BLE and deliberate official-app broker recovery.

No user's fixture, Home Assistant, broker or network has been modified to
develop or run these offline checks.
