# Classic scheduled-state reporting

This change addresses the stale Manual-mode indication described in upstream
issue #110. It adds schedule-based presentation and refreshes parameter readback
after schedule saves and mode selection. No new command bytes, scheduler,
periodic Bluetooth polling, minimum HA version, or automatic clock writes are introduced.

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
  A successful explicit Off does not require a schedule or synchronized clock
  to retain its Off indication. Releasing that override does not substitute for
  missing schedule/clock data.
- An active preview temporarily takes precedence over the preceding Off
  override. Native preview start/stop notifies light entities immediately after
  changing the preview flag. Failed starts retain the previous indication;
  failed stops keep the preview indication instead of claiming normal output.
- Plain turn-on in classic Auto/Pro uses the existing power command even when
  cached Manual channels are zero. It does not apply a default colour or switch
  to Manual. Explicit colour and brightness requests retain their normal behavior.
  `OldLightKxtKt.createLightSwitchValueForOld` constructs the separate `6803`
  power command without channel data; no protocol bytes are changed here.
- Shared power and mode bookkeeping now commits the requested value after a
  successful write, then notifies entities after updating the classic Off
  override. Failed preparation or writes preserve fresh reconnect/verification
  readback instead of restoring the older idle cache. Classic, FACEBD and SPP
  still use their existing power and mode packet builders.
- Static projection is withheld during previews, without a successful clock
  initialization/readback basis, or during active timed-weather windows whose
  instantaneous output is not described by the static channel curve. Weekday
  and time-window filtering keeps normal reporting available outside them.
- Successful classic schedule writes immediately invalidate the old projection,
  even if subsequent activation fails. A parameter read after the save repopulates
  it from the fixture; failed readback never restores the older projection.
- Successful schedule activation clears the explicit Off override. Saving
  without activation, failed writes and failed activation preserve it.
- Classic mode selection requests fresh active-mode parameters, including when
  restoring a mode after manual channel adjustments. Reconnection readback is
  completed before committing the requested mode, so it cannot overwrite the request.
  Failed mode writes also retain fresh verification readback rather than rolling
  back the complete device state.
- Each classic response replaces the active forecast and weather windows together.
  Inactive-mode forecasts are discarded; failed reads cannot combine an older
  schedule with missing or different weather settings.
- Successful classic timed-weather writes also invalidate the forecast and
  request active-mode readback. Submitted windows alone are not used to resume
  projection. Failed writes preserve the preceding confirmed forecast, while a
  failed read after a successful write leaves projection unavailable.
- FACEBD/SPP continue to use their existing reported switch fields, not the
  classic schedule projection. The shared command-state fixes apply to these
  transports as well, without changing their protocol or schedule calculations.

## Verification

Tests cover four/five-channel Auto and Pro schedules, night and sleep behavior,
midnight wrap, equal-time steps, tenth-percent ramps, actual classic response
decoding, invalid readback, isolation from editable/manual caches, off-command
precedence and failures, display-only ticks, and entity unload cleanup.
Additional checks cover Auto/Pro save-readback transactions, read timeouts,
partial activation failures, and timed-weather weekday/midnight boundaries.
Mode-selection checks cover reconnect readback, failed reads and matching
schedule/weather snapshots when returning from Manual to Auto or Pro.
Timed-weather save checks include readback differing from the submitted window,
read failure, timeout, and failed-write preservation of the confirmed forecast.

An isolated smoke check also passed against real Home Assistant 2024.1.0 and
2026.7.2 (locally cached Docker images). It bootstrapped HA, added the light to
an entity platform, verified published assumed-state attributes and a real
30-second timer update, returned to Manual, and removed/re-added the entity
without duplicate device callbacks. Containers had networking disabled, a
read-only candidate checkout, temporary configuration, and no Bluetooth devices.
This validates entity-platform behavior, not a full Bluetooth config-entry setup.
The expanded check also verified missing-clock and active-preview `unknown`
states, explicit Off without clock data, and `unavailable` when the device has
neither a client nor discovery data needed to attempt controls.

Hardware validation has not been performed. This is expected output with HA's
standard `assumed_state` flag, not confirmation of physical illumination.
