# Classic scheduled-state reporting

Scheduled-state reporting addresses the stale Manual-mode indication described
in upstream issue #110. It uses schedule-based presentation and refreshes
parameter readback on mode selection. No new command bytes, scheduler,
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
  channel values. Schedule editing and previews belong in Fluval Connect.
- Whole-percent rounding is not used to decide on/off. A positive tenth-percent
  output still indicates on.
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
  Per-field readback revisions distinguish a submitted command from a power or
  mode value actually decoded during the write. Fresh fixture reports take
  precedence, including reports equal to the previous cached value.
  The light entity also renders that final device state after Off rather than
  forcing its own false value. Effect state is only cleared when the resulting
  power state is Off, not when fresh readback still reports On.
- Static projection is withheld without a successful clock
  initialization/readback basis, or during active timed-weather windows whose
  instantaneous output is not described by the static channel curve. Weekday
  and time-window filtering keeps normal reporting available outside them.
- Classic mode selection requests fresh active-mode parameters, including when
  restoring a mode after manual channel adjustments. Reconnection readback is
  completed before committing the requested mode, so it cannot overwrite the request.
  Failed mode writes also retain fresh verification readback rather than rolling
  back the complete device state.
- Each classic response replaces the active forecast and weather windows together.
  Inactive-mode forecasts are discarded; failed reads cannot combine an older
  schedule with missing or different weather settings.
- FACEBD/SPP continue to use their existing reported switch fields, not the
  classic schedule projection. The shared command-state fixes apply to these
  transports as well, without changing their protocol or schedule calculations.

## Verification

Tests cover four/five-channel Auto and Pro schedules, night and sleep behavior,
midnight wrap, equal-time steps, tenth-percent ramps, actual classic response
decoding, invalid readback, isolation from manual caches, off-command
precedence and failures, display-only ticks, and entity unload cleanup.
An independent transcription of the APK Auto segment walk is compared with the
projection for all 1,440 minutes of 16 four-/five-channel schedules, including
midnight rotations and sleep transitions (23,040 comparisons). This is a source
cross-check, not execution of the Android application or fixture firmware.
Additional checks cover timed-weather weekday/midnight boundaries.
Mode-selection checks cover reconnect readback, failed reads and matching
schedule/weather snapshots when returning from Manual to Auto or Pro.

## Earlier validation of scheduled-state reporting

The following records the checks performed when scheduled-state reporting was
introduced.

An isolated smoke check also passed against real Home Assistant 2024.1.0 and
2026.7.2 (locally cached Docker images). It bootstrapped HA, added the light to
an entity platform, verified published assumed-state attributes and a real
30-second timer update, returned to Manual, and removed/re-added the entity
without duplicate device callbacks. Containers had networking disabled, a
read-only candidate checkout, temporary configuration, and no Bluetooth devices.
This validates entity-platform behavior, not a full Bluetooth config-entry setup.
The expanded check also verified missing-clock `unknown`
states, explicit Off without clock data, and `unavailable` when the device has
neither a client nor discovery data needed to attempt controls.

A separate real-HA config-entry check passed on both versions as well. It
starts with a version-one entry and exercises migration, all platforms, 18
registered entities, unload/setup and the public reload operation. Entity IDs
remain stable, there is one light entity, entity-bound callbacks are removed,
and Bluetooth subscription registration/unregistration stays balanced.
Only the radio/discovery boundary and initial
device construction are simulated; the HA entry manager and entity platforms
are real. No BLE client is created.

This exposed a HA 2024.1 migration compatibility failure, now repaired:
version-one migration uses direct version assignment on the legacy API (HA
persists successful migrations). Current HA retains its current APIs.
This repair does not change the minimum HA version or fixture protocol.

The lifecycle check also covers cached and delayed discovery, unloading before
any discovery, and real HA light-service dispatch with simulated successful and
failed writes. Both HA versions pass. On HA 2024.1, a real options update is
checked to cause exactly one reload. This exposed and fixed a legacy-listener
race: saving newly discovered identity data previously triggered a reload while
late entities were being added. The fallback listener now compares options and
ignores data-only updates. Current HA continues to use OptionsFlowWithReload.

Classic Auto/Pro output has not been physically validated. This is expected
output with HA's standard `assumed_state` flag, not confirmation of illumination.
Manual-mode reads and the accompanying command repairs were tested on product
328; see [command sequencing evidence](classic-command-sequencing.md). That
test does not establish scheduled output or other models' physical behaviour.
