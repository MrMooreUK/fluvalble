# Fluval BLE technical reference

This document collects implementation details used for development, protocol
review, and issue diagnosis. FluvalConnect APK evidence is the source of truth
for product identity, channel layouts, native effects, schedule limits, and
controller commands.

## Product identity and capabilities

The advertised product ID selects the FluvalConnect model, physical channel
layout, spectrum profile, schedule support, and native-effect catalogue.
Bluetooth names are display data, not capability evidence.

Plant PRO (product 386) and Plant 4.0 (product 545) are distinct products even
though both use five-channel Plant spectra and may expose the same FFF0/SPP
transport. If an advertisement has no APK-known product ID, the integration
uses a generic layout until an explicit fixture profile or decoded controller
response supplies the missing capability information.

See [APK colour-control evidence](apk-colour-evidence.md) for colour conversion
details and their source locations in the decompiled APK.

## Controller transports

Product identity and BLE transport are separate. Transport selection comes
from the services exposed by the connected fixture. The integration supports
legacy encrypted controllers, AquaSky 3.0/FACEBD controllers, and FFF0/SPP
controllers using D1 command and D2 status CBOR frames.

## Native schedules and previews

Classic/OLD controllers accept 4–10 Professional schedule points. FACEBD and
FFF0/SPP controllers accept 4–12 points. Schedule actions use positional
`channel_1` through `channel_5` fields and label those positions with the
detected product's APK-defined channel names. Earlier RGB-style and
Plant-specific names remain accepted as compatibility aliases.

Timed-effect schedules support up to seven windows, with a weekday assigned to
no more than one window. The product ID selects either the 11-effect catalogue
or the four-effect subset. Classic status readback exposes only one embedded
effect slot, so a longer submitted schedule is retained in diagnostics without
being presented as complete fixture-confirmed readback.

Fixture schedule previews use the schedule already stored by the controller
and never upload unsaved editor values. Stopping a preview sends the APK stop
command and restores the prior fixture mode.

FACEBD daylight-saving state is reported through CBOR key `99`. Clock
synchronization sends the Home Assistant host's UTC offset and Unix time using
keys `101` and `102`; it does not alter the fixture's daylight-saving flag or
apply another one-hour offset.

## Bluetooth lifecycle and diagnostics

On load and reconnect, the integration asks Home Assistant for its best
connectable route across local adapters and ESPHome Bluetooth proxies. It uses
a fresh BLE client for each reconnect and runs a keep-alive every 10 seconds
while connected.

An active connection window of `0` keeps the session open and starts one
serialized reconnect cycle after an unexpected drop. A finite window closes an
idle session; the default is two minutes. FFF0/SPP fixtures permit one BLE
central at a time, so a persistent Home Assistant connection prevents the
official application or gateway from connecting.

Reachability remains true for five minutes after an advertisement, successful
connection, or successful command. While connected, signal strength represents
the latest advertisement from the scanner selected for GATT. Its timestamp is
preserved because Fluval controllers normally stop advertising during an
active session, and advertisements from other scanners do not replace it.

Source exposes only the friendly name of the adapter or proxy confirmed by
Home Assistant's connected GATT client. Scanner addresses, the latest
advertisement, product profile, connection and command state, and schedule
evidence remain available in redacted diagnostics.

Complete commands are serialized per fixture so multi-packet operations retain
their APK-defined order when different Home Assistant entities or actions are
called concurrently. Long channel transitions release the transaction between
frames, allowing a newer explicit command to stop the remaining transition
without interleaving packet sequences.
