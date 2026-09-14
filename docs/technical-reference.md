# Fluval BLE technical reference

This document collects implementation details used for development, protocol
review, and issue diagnosis. FluvalConnect APK evidence is the source of truth
for product identity, channel layouts, native effects, schedule limits, and
controller commands.

## Product identity and capabilities

The advertised product ID selects the FluvalConnect model, physical channel
layout, spectrum profile, neutral emitter, manual-preset support, and native
effect catalogue. Bluetooth names are display data, not capability evidence.
The following table is the integration's complete APK-recognized light matrix.

| APK family | Product IDs | Spectrum profile | Channels | Neutral | Effects | P1-P4 | APK controller path |
|---|---|---|---:|---:|---:|---:|---|
| Current Reef-type | 385, 546, 547 | `reef_current` | 5 | 5 | 4 | 0 | FFF0/SPP |
| Current Plant | 386, 545, 548, 563 | `plant_current` | 5 | 4 | 4 | 0 | FFF0/SPP |
| AquaSky 3.0 | 532 | `aquasky_current` | 4 | 4 | 11 | 0 | FACEBD |
| Current RGBW | 564 | `aquasky_current` | 4 | 4 | 11 | 0 | FFF0/SPP |
| Legacy Reef | 289-294, 337, 536, 640 | `reef_legacy` | 5 | 5 | 0 | 4 | Classic |
| Legacy Plant | 305-311, 338, 373-377, 387-388, 537, 641, 29058 | `plant_legacy` | 5 | 4 | 0 | 4 | Classic |
| Legacy AquaSky/RGBW | 321-329, 336, 369-372, 384, 609, 29057 | `aquasky_legacy` | 4 | 4 | 11 | 4 | Classic |
| APK default-routed product | 281 | `reef_current` | 5 | 5 | 0 | 4 | Classic |

The channel orders are Pink, Cyan, Blue, Purple, Cold White for Reef;
Pink, Blue, Cold White, Pure White, Warm White for Plant; and Red, Green,
Blue, White for RGBW. Product 385 retains the APK's unusual current Reef-type
classification even though its older device name is A-Sky Aqua. Product 281
likewise retains the APK's default current Reef spectrum while remaining an
OLD/classic controller. Neither exception is normalized from its display name.

If an advertisement has no APK-known product ID, the integration uses a
generic layout until an explicit fixture profile or decoded controller response
supplies the missing capability information.

See [APK colour-control evidence](apk-colour-evidence.md) for colour conversion
details and their source locations in the decompiled APK.

## Controller transports

Product identity and BLE transport are separate. The table records the route
selected by FluvalConnect, while runtime transport selection comes from the
services exposed by the connected fixture. The integration supports
legacy encrypted controllers, AquaSky 3.0/FACEBD controllers, and FFF0/SPP
controllers using D1 command and D2 status CBOR frames.

FluvalConnect sends all three controller families through one command queue at
200 ms intervals. Its current-generation BLE writer splits long frames at the
negotiated ATT payload size and waits 5 ms between chunks. FFF0/SPP parameter
dumps may likewise span multiple notifications; the integration reassembles a
complete D2 CBOR value before updating fixture state or confirming a command.
The transport is therefore named `spp` in protocol-neutral diagnostics; the
former `plant_pro_spp` flag remains as a compatibility alias.

## Native schedule readback

Classic/OLD controllers accept 4–10 Professional schedule points. FACEBD and
FFF0/SPP controllers accept 4–12 points. Readback uses the detected product's
APK-defined channel order and width. Program these schedules in Fluval Connect.

Auto schedules preserve FluvalConnect's midnight wrapping for sunrise and
sunset ramps. Four-channel product profiles read exactly four day
and night levels; five-channel profiles use five. Readback is accepted only
when its packet shape, channel width, point limits, times, ramps, and levels
fit the corresponding APK controller format.

Timed-effect schedules support up to seven windows, with a weekday assigned to
no more than one window. The product ID selects either the 11-effect catalogue
or the four-effect subset. Classic status readback exposes only one embedded
effect slot, which is not presented as complete fixture-confirmed readback.
The integration does not provide schedule-writing or preview actions.

FACEBD daylight-saving state is reported through CBOR key `99`. Clock
synchronization sends the Home Assistant host's UTC offset and Unix time using
keys `101` and `102`; it does not alter the fixture's daylight-saving flag or
apply another one-hour offset.

## Classic manual presets

FluvalConnect exposes four fixture-resident P1-P4 presets only when its product
routing identifies a controller as `LightType.OLD`. The integration mirrors
that exact APK product boundary and does not expose these scenes on current
FACEBD or FFF0/SPP controllers.

Each scene applies the channel array returned in the selected preset slot using
the classic `6804` channel command. The fixture must be on and complete preset
readback must be available. Saving is intentionally kept as the explicit
**Save manual preset** action: it uses the APK's zero-based `6806` slot command
and overwrites memory in the physical fixture.

## Bluetooth lifecycle and diagnostics

On load and reconnect, the integration asks Home Assistant for its best
connectable route across local adapters and ESPHome Bluetooth proxies. It uses
a fresh BLE client for each reconnect. The keep-alive interval is configurable
from 5 to 60 seconds (default 10) while connected; it is separate from the idle
connection window.

The active connection window is configurable from 30 to 600 seconds, with a
two-minute default. An idle session closes after this window. FFF0/SPP fixtures
permit one BLE central
at a time, so allow the idle window to expire before using Fluval Connect.

Reachability remains true for five minutes after an advertisement, successful
connection, or successful command. While connected, signal strength represents
the latest advertisement from the scanner selected for GATT. Its timestamp is
preserved because Fluval controllers normally stop advertising during an
active session, and advertisements from other scanners do not replace it.

Source exposes only the friendly name of the adapter or proxy confirmed by
Home Assistant's connected GATT client. Product profile, connection and command
state, and schedule evidence remain available in redacted diagnostics.
Identifying addresses and names are removed from that downloadable report.

Complete commands are serialized per fixture so multi-packet operations retain
their APK-defined order when different Home Assistant entities or actions are
called concurrently. Long channel transitions release the transaction between
frames, allowing a newer explicit command to stop the remaining transition
without interleaving packet sequences.

An accepted GATT write is not reported as fixture-confirmed state. FACEBD and
FFF0/SPP commands whose written keys are observable use exact typed state
readback; commands without an observable state key remain explicitly
unverified. A successful GATT write is sent once, while only an actual write
exception enters the bounded retry path.
