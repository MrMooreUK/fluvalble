# Classic scheduled-state reporting

This change addresses the stale Manual-mode indication described in upstream
issue #110. It changes presentation only: no new command bytes, scheduler,
Bluetooth polling, minimum HA version, or automatic clock writes are introduced.

## FluvalConnect APK evidence

Paths are relative to the decompiled application's sources directory:

- `eu/hagen/fluvalconnect/kxt/light/OldLightKxtKt.java`,
  `createLightReadParamsValueForOld`: reads active-mode parameters using `6805`.
- `eu/hagen/fluvalconnect/kxt/LightKxtKt.java`,
  `analyticLightParameterToOld`: Manual includes switch/channel state; Auto/Pro
  include programmed times and levels, not instantaneous power readback.
- `eu/hagen/fluvalconnect/ui/main/device/light/detail/AutoFragment.java`,
  `getBright`: four day/night points, or six including duplicate sleep-time
  points, with integer interpolation at a 0..1000 scale and midnight wrapping.
- `eu/hagen/fluvalconnect/ui/main/device/light/detail/ProFragment.java`,
  `getBrights`: stable timepoint sorting, cyclic interpolation, and the same
  integer scale. Descending integer division truncates toward zero.

Both calculations were rechecked using JADX 1.5.5's `simple` decompilation mode,
which exposes branch labels where the default decompilation lost control flow.
They calculate preview output; they are not a physical light-output sensor.

## Implementation boundaries

- The forecast uses immutable copies of fixture readback, separate from manual
  values and editable schedules used in command generation.
- Whole-percent rounding from the existing preview helper is not reused to
  decide on/off. A positive tenth-percent output still indicates on.
- A 30-second HA entity callback updates presentation only. HA's entity removal
  callbacks cancel the timer and deregister updates on unload.
- Normal idle disconnection does not erase the last schedule/clock basis.
  Device reachability remains independent of the assumed output calculation.
- Existing explicit successful power-off commands override the projection;
  failed commands do not change this override. Selecting a mode or successfully
  turning power on releases it. This adds no packet or mode-switch sequence.
- Static projection is withheld during previews, without a successful clock
  initialization/readback basis, or during active timed-weather windows whose
  instantaneous output is not described by the static channel curve. Weekday
  and time-window filtering keeps normal reporting available outside them.
- Successful classic schedule writes immediately invalidate the old projection,
  even if subsequent activation fails. A parameter read after the save repopulates
  it from the fixture; failed readback never restores the older projection.
- Successful schedule activation clears the explicit Off override. Saving
  without activation, failed writes and failed activation preserve it.
- FACEBD/SPP reporting is unchanged. No assumption is made that their switch
  fields describe the same state as a classic schedule projection.

## Verification

Tests cover four/five-channel Auto and Pro schedules, night and sleep behavior,
midnight wrap, equal-time steps, tenth-percent ramps, actual classic response
decoding, invalid readback, isolation from editable/manual caches, off-command
precedence and failures, display-only ticks, and entity unload cleanup.
Additional checks cover Auto/Pro save-readback transactions, read timeouts,
partial activation failures, and timed-weather weekday/midnight boundaries.

Hardware validation has not been performed. This is expected output with HA's
standard `assumed_state` flag, not confirmation of physical illumination.
