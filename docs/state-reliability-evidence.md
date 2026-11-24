# State reliability repairs

These repairs follow FluvalConnect 1.0.15, derived for interoperability.
They change Home Assistant state coordination, not firmware opcodes, GATT UUIDs,
encryption, percentage scales, product identities or native effect catalogues.

## App and captured protocol evidence

| Area | Primary evidence | Integration repair |
|---|---|---|
| Initialization | App initialization queues clock then parameter read; OLD read is 6805, current SPP is D0 FF | Wait for valid initial readback before declaring the session ready; release an unready connection |
| Independent commands | The app defines separate mode, power and weather commands | Preserve completed operations and notifications when a later operation fails; do not pretend the sequence is atomic |
| Physical channels | The app's Manual screen and channel command builders | Derive brightness and channel writes after connection readback; an individual channel notification does not redefine channel count |
| Product layout | The app's product type, combined type, channel and channel-count lookups | Keep known product layouts authoritative; reconcile deferred identification and exact channel entities |
| Local clock | The app's classic and current clock builders | Use HA-local calendar time and UTC offset, not the container timezone; epoch milliseconds remain absolute |
| Schedule banks | The app's schedule builders and Auto/Pro screen handlers | Fresh Auto fields (FACEBD 114–118 / SPP 8–12) and Pro fields (120–122 / 13) are required for schedule conflict checks and confirmation |
| Local recall | The app's local colour-bank storage and Manual recall | Keep explicit local-bank recall, require freshly read Manual mode, never automatically stop an Auto/Pro programme |

[Issue #133's public SPP capture](https://github.com/MrMooreUK/fluvalble/issues/133#issuecomment-6895548202)
contains Manual channels and both schedule banks together. It demonstrates the
existing read command and field separation; it does not prove that a particular
incoming report was caused by the fixture's button. No such inference is used.

The APK sends reads asynchronously. Queueing a read is not proof its response
has arrived. Waiting for required fields is HA coordination over the existing
read command, not an invented command or a claim that Android blocks its UI.
Ratio-preserving HA brightness is likewise an adapter feature, not an APK RGB
algorithm; its source values must come from post-connection physical channels.

## Failure cases covered

- Initial classic notification arrives after submission, or no state arrives.
- Partial current notifications arrive before all required readback fields.
- Cached Auto/Pro differs from the actual Manual mode on a connected session.
- A Manual request receives contradictory fresh Auto readback.
- Mode and power succeed, fresh channels arrive, and the effect command fails.
- Brightness is requested while reconnecting supplies a different channel mix.
- An unchanged slider request is made while a schedule mode remains active.
- An unidentified controller resolves four channels during its first command,
  or receives a partial update after five channels are established.
- A schedule refresh returns mode/power but no selected schedule data.
- HA and process timezones differ, including explicit timezone-aware clock input.
- Deferred channel controls and obsolete registry rows are reconciled; removal
  tasks cannot recreate entities during unload.

Tests exercise classic, FACEBD and SPP paths and complete initial Manual-state
requirements for every product in the 54-product APK-derived catalogue. These
checks establish source/transport behaviour, not optical colour measurements.

## Combined follow-up review

The complete combined implementation was reviewed again, including our earlier
contributions. Nine reproducible gaps were corrected on the same repair branch:

1. Effect revisions are captured separately for mode, power and effect writes.
   An earlier mode response cannot reject a later power-on command when there
   is no contradictory new response.
2. Physical channel width is resolved again after the Manual-mode response,
   before constructing and confirming the channel bank.
3. Relative brightness and partial mode-switch edits require a fresh Manual
   bank; scheduled/cached channels cannot substitute for that readback.
4. Empty requests and requests containing unsupported channel keys fail before
   any mode, power or channel command on a known layout.
5. The final fade step is confirmed and saved even if rounding reached its
   target during an earlier, deliberately unsaved step.
6. Schedule saves require a runtime that remains loaded and unchanged, checked
   after acquiring the command lock and again before writing.
7. Professional drafts are validated together and sent in one existing native
   bank command. Validation/batching changes; wire layouts do not.
8. Deferred FACEBD identification adds its DST control once. Unload cancels
   the subscription and prevents later entity creation.
9. Product 281 follows the active screen's Reef labels, not the older unused
   product table. The app's Manual screen uses the current table's colours and
   defaults product 281 to type 1. Auto/Pro likewise use the current channel
   lookup. Spectrum is unchanged.

Additional regressions cover classic, FACEBD and SPP, every known product's
invalid-channel rejection, late four/five-channel resolution, runtime replacement,
both Professional edit orders and malformed batches. Server-isolated browser
checks cover batching, failed-save drafts and stale fixture responses. No
physical fixture is controlled.

The repeat review also checked failure after the new Manual read. Rollback now
uses that post-read bank, preserving newly reported untouched channels rather
than replaying the pre-read cache. Three transport-specific regressions cover it.

Final offline verification: 1,683 tests passed and two optional image checks
skipped on both Python 3.11 and 3.12. Ruff lint/format, mypy and the isolated
headless card checks passed. Coverage is 79.76%. These are source and simulated
transport results, not a claim of physical testing on all fixtures.

## Scope

### Follow-up to the PR #142 review

Initialization now has its own five-second response window and one retry before
the unready connection is released. The normal 0.75-second verification window
is unchanged. This is a host-side tolerance for delayed transport responses,
not an APK-derived timing guarantee or a different firmware command.

Four FACEBD channel keys can establish an initial four-channel hint without
mode/power keys in that same map. The client accumulates the separate reports
before accepting complete Manual state. A valid fifth key upgrades the hint;
four-key partial reports cannot shrink an established five-channel hint.

Entity-registry pruning requires a recognized catalogue product. Provisional
hints leave existing controls and their IDs/customizations intact, marking
out-of-layout channels unavailable instead of deleting their records. Deferred
removal also rechecks the current identified layout before deleting a row.

Effect operations carry an explicit kind instead of identifying their purpose
by rebuilding and comparing bytes. Incomplete non-batch schedule edits fail
before any read. Brightness retains its fresh Manual read deliberately: a
connected session alone does not prove that cached ratios are current. The
light's preparation remains inside its existing command transaction and is
needed before selecting a product-dependent colour conversion.

Regression tests cover replies delayed beyond the normal deadline on all three
transports, one retry after timeout/read error, finite failure and disconnect,
both orders of split FACEBD mode/power/channel reports, provisional entity
preservation and incomplete editor requests. No physical light is contacted.

The broader failures predate PRs #139–#141. The stale cached-mode refusal was
introduced by #140. This repair preserves its Manual-only restore policy,
the zero-bank protection, debounced storage and the live-state fade changes.
It does not revert those PRs, redesign scheduling, change minimum HA support,
add workflows, bump a version or prepare a release.
