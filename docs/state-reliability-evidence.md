# State reliability repairs

These repairs follow the FluvalConnect 1.0.15 (versionCode 110) decompilation,
base APK SHA-256 9c3cecf8edebff06ac945d7431b078813af9d4fd86ba9fba40453dc612be3415.
They change Home Assistant state coordination, not firmware opcodes, GATT UUIDs,
encryption, percentage scales, product identities or native effect catalogues.

## APK and captured protocol evidence

| Area | Primary evidence | Integration repair |
|---|---|---|
| Initialization | LightDetailActivity.java 931–950 queues clock then parameter read; OLD read is 6805, current SPP is D0 FF | Wait for valid initial readback before declaring the session ready; release an unready connection |
| Independent commands | LightKxtKt.java 640–787 defines separate mode, power and weather commands | Preserve completed operations and notifications when a later operation fails; do not pretend the sequence is atomic |
| Physical channels | ManFragment.java 581–624, 1059–1175; LightInstructionsKxtKt.java 160–207 | Derive brightness and channel writes after connection readback; an individual channel notification does not redefine channel count |
| Product layout | LightDeviceUtils.getLightType/getLightTypeAndOld/getLightChannel/getChannelCount | Keep known product layouts authoritative; reconcile deferred identification and exact channel entities |
| Local clock | OldLightKxtKt.java 21–44; LightKxtKt.java 535–560, 1048 | Use HA-local calendar time and UTC offset, not the container timezone; epoch milliseconds remain absolute |
| Schedule banks | LightKxtKt.java 931–989; AutoFragment and ProFragment handlers | Fresh Auto fields (FACEBD 114–118 / SPP 8–12) and Pro fields (120–122 / 13) are required for schedule conflict checks and confirmation |
| Local recall | LightKxtKt.java 384–410; ManFragment.java 740–770 | Keep explicit local-bank recall, require freshly read Manual mode, never automatically stop an Auto/Pro programme |

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

## Scope

The broader failures predate PRs #139–#141. The stale cached-mode refusal was
introduced by #140. This repair preserves its Manual-only restore policy,
the zero-bank protection, debounced storage and the live-state fade changes.
It does not revert those PRs, redesign scheduling, change minimum HA support,
add workflows, bump a version or prepare a release.
