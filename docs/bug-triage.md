# Open Bug Triage

This document captures the state of the two currently-open bugs. Neither
is fixed yet; both are documented here so they remain solvable once we
have the right evidence.

| # | Title | Status | Blocker |
|---|-------|--------|---------|
| [#6](https://github.com/MrMooreUK/fluvalble/issues/6) | Aquasky 2.0: connected but does not respond to commands | Open — investigation | Needs debug logs from a real Aquasky 2.0 |
| [#8](https://github.com/MrMooreUK/fluvalble/issues/8) | Automatic mode schedule wrong after power cut (lamp RTC reset) | Open — investigation | Needs protocol capture of clock-sync command (or confirmation it doesn't exist) |

---

## #6 — Aquasky 2.0 commands ignored

**Symptom:** Integration connects to the lamp, but toggling the LED switch
or moving a channel slider has no effect. Device briefly disconnects then
reconnects with the previous state unchanged.

**Hypothesis:** Either (a) the v0.0.4 BLE client is not re-usable after
idle and the user is on an old release, or (b) the Aquasky 2.0 requires
`response=False` on its write characteristic where Plant 3.0 accepts
`response=True`.

**What we need to make progress:**

- [ ] Confirm reporter is on v0.0.5+ (the BLE-reuse fix from PR #4 was
      released in v0.0.5). If they're on v0.0.4, ask them to retest.
- [ ] Debug log capture from an Aquasky 2.0 with
      `custom_components.fluvalble: debug` enabled, while sending one
      command. The log lines we need look like:
      ```
      Sending to XX:XX:XX:XX:XX:XX — raw: 68 04 ... | encrypted: 54 ...
      ```
- [ ] A BLE sniffer trace (ESP32 or nRF) of the same operation in the
      official Fluval app, for byte-level comparison.

**Workaround:** None yet. Users should keep the lamp in Manual mode and
control channels via automations.

---

## #8 — Schedule drift after power cut

**Symptom:** After a power interruption, the lamp's built-in Automatic /
Professional lighting schedule runs at the wrong times. Manual mode is
unaffected.

**Root cause:** The lamp's automatic schedule is driven by an internal
RTC. Power loss resets the RTC to its epoch, and the schedule drifts
from wall-clock time. The official Fluval app presumably re-syncs the
clock on connect; this integration does not.

**What we need to make progress:**

- [ ] Confirm the BLE protocol includes a clock-sync command. Sources
      to check:
  - Fluval Plant 3.0 BLE protocol thread on Planted Tank Forum
  - ESPHome `fluval` external component source
  - A captured traffic dump from the official Fluval app
- [ ] If a command exists: implement and test sending it after
      `CMD_STATUS` on each fresh connection.
- [ ] If no command exists: document as a known limitation in README
      and recommend Manual mode for HA-controlled setups.

**Workaround:** Set the Mode select entity to **Manual** and drive
brightness from HA automations (sunrise / sunset, or a fixed schedule).
This is already covered in the README's example automations.

---

## Reporting a new bug

When a new issue is opened, please ask the reporter to:

1. Confirm the integration version (Settings → Devices & services →
   Fluval Aquarium LED → ⓘ).
2. Enable debug logging:
   ```yaml
   logger:
     default: info
     logs:
       custom_components.fluvalble: debug
   ```
3. Capture the log snippet around a failing command.
4. Note the lamp model and Bluetooth adapter (built-in vs ESP32
   proxy vs other).
