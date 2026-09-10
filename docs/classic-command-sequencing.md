# Classic command sequencing verification

Local follow-up to the 2026-09-09 product 328 (Aquasky 750mm) captures.

- A channel frame sent while Off did not survive the next On. The same
  frame sent while On was reported correctly. Keep power before channels.
- A Full moon effect survived bare power switching in earlier captures.
  Sending zero manual channels while On, then Off, cleared the reported
  effect through the following On. This is an HA shutdown policy, not a
  claim that the APK power button performs this sequence.
- A delayed Off notification between colour and power handling caused a
  redundant On. Channel application now owns power sequencing; callers do
  not retry power based on the cache after successful channel application.
- Freeze outgoing channel values before awaiting power, because incoming
  notifications can replace cached channels during that await.

APK evidence: `OldLightKxtKt.createLightSwitchValueForOld` builds 6803;
the all-zone builder supplies 6804. `ManFragment` manual channel handlers
leave weather through channel writes, and `LightWeatherAdapter.clearSelect`
only clears UI selection. No dedicated weather-cancel command is invented.

Weather clearing is limited to an active Manual effect on a confirmed classic
transport. Ordinary static Off and other transports retain their existing
power path. Off is attempted even if clearing fails, and partial failure is
reported to the caller.

Tests cover delayed notifications across classic, FACEBD and SPP, unchanged
positive channels while Off, the weather clear sequence and its failure path.
The complete suite passed 1,145 tests before installation.

## Installed-build verification

The repaired build was installed on 2026-09-09 and activated with one approved
Home Assistant restart. A brief product 328 test reported Full moon (09), then
Off with effect 00, then On with effect 00 and red at 1%, followed by Off with
all channels zero. A delayed Off notification arrived after the colour
operation's On, but no redundant On was sent. The requested channel packet
remained correct. Final diagnostics showed connected with no error.

These are device-readback results, not visual confirmation of brightness,
fade appearance or ghost glow. They do not constitute physical testing of
FACEBD, SPP, or classic scheduled Auto/Pro output.

## Relationship to scheduled-state reporting

Include this command repair and hardware evidence alongside the pending
scheduled-state change, while keeping their validation boundaries separate.
Classic Manual reports power and channels; classic Auto/Pro responses instead
provide schedule parameters. The schedule-derived display remains assumed
output, not a newly discovered live power measurement. FACEBD and SPP retain
their existing reported switch fields and do not use the classic projection.
