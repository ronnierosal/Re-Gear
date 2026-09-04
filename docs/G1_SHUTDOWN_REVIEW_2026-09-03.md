# G1 shutdown review — 2026-09-03

## Evidence and scope

The maintainer requested shutdown after the TV/Portable test and reported continued
fan activity and two illuminated LEDs before leaving. Final power state remains
unknown. No live commands, remote changes, or retries were performed in this review.

Reviewed the other workstream's `EGPU_HARDWARE_ECOSYSTEM_AUDIT_2026-09-03.md`
in the primary checkout. That draft and its INDEX/UI edits were not absorbed.
External-project findings remain attributed to that dated audit, not newly
verified upstream facts.

## Audit dispositions

| Audit finding | Decision |
| --- | --- |
| Full G1 topology and fresh driver/DRM identity are needed | Preserve existing profile gates; do not add IDs or broaden matching for this fix. |
| Connected connector is not active output | Retain Gamescope/render/output checks and human picture/audio confirmation. |
| One removal success was invalidated by later teardown/rebind failures | Keep shutdown-before-unplug; import no reset/remove/deauthorize recipe. |
| Teardown/reconnect symptoms need timestamped evidence | Add bounded previous-boot retrieval and HDM unload markers. |
| Polling causality is unproven | No speculative cadence change or new live poller. |
| Other GPUs, split scanout/render, and wider catalogs | Backlog until concrete hardware evidence requires changes. |
| Mainline AMDGPU fixes may be relevant | Verify Valve kernel ancestry/backports before attribution; no kernel changes. |

## Confirmed local defect, not confirmed hardware cause

The shutdown service uses one-use approval, fresh unchanged evidence, idle game,
supported host, and Portable placement before ordinary nonblocking poweroff.
Acceptance is never physical completion. The login1 helper requests `sleep`, not
`shutdown`; its presence does not prove it is blocking poweroff.

`Plugin._unload` caught only `CancelledError` while awaiting owned tasks. An
already-failed task can raise its original exception, skipping remaining cleanup
and the HDM sleep-guard release. Tests reproduce this code defect. It is NOT yet
established as the cause of the hardware shutdown hang.

The fix tolerates each failed HDM observer, retires the other owned tasks, and
attempts release of its own guard. It does not drain the shared executor, shorten
system stop timeouts, or terminate Steam/Gamescope/audio/storage/driver clients.

## Diagnostic limits

Existing Decky logging now emits `HDM shutdown checkpoint` stages with bounded
elapsed milliseconds: unload start, observer failure/stopped, guard release
start/failure/released, and unload complete. No raw exceptions, identities, or
paths are exported. Logging failure cannot prevent cleanup. No new disk-sync
loop, journal configuration, shutdown hook, or poller is added.

Markers survive reboot only if the system journal already retains them. Plugin
unload can mean an update: completion never proves kernel teardown or poweroff.
The developer-only previous-boot collector returns categorical symptoms and
timings from a bounded tail. Missing journal/permissions, truncated coverage, or
missing markers remain incomplete evidence. It does not enable journaling or
use sudo. A new boot and journal EOF never establish clean prior shutdown.

## Next supervised step

Local verification: 838 backend tests passed with five platform skips, including
15 previous-boot-reader tests and four new cleanup/checkpoint tests. All 66
frontend tests, typecheck, Rollup, architecture, compileall, package contract, and
whitespace checks passed. No hardware validation was performed for these changes.

When the maintainer returns, first confirm physical power state. Wait for explicit
fan/LED poweroff before unplugging. After a safe boot, collect retained prior-boot
evidence without initiating another shutdown. Correlate HDM cleanup with systemd
stop failures and kernel symptoms. If logs were not retained, record the gap and
seek separate approval before changing capture configuration.

The already-staged `bf1b2efde366` ZIP has launcher/audio fixes, not this shutdown
change. Neither that package nor this local fix proves the hardware hang resolved.
