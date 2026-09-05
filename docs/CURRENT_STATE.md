# Current state


## Re-Gear 0.3.41 offline icon packaging fix

Compact badge imports were omitted from the inline SVG resolver, leaving
references to dist/assets files excluded by the ZIP contract. All three
compact icons are now embedded as SVG data URLs. Regression coverage resolves
every badge import and compares decoded inline bytes to source assets.
No change to offline readiness decisions or game artwork.


## Re-Gear 0.3.40 UI candidate

Staged 2026-09-05: `/home/deck/Re-Gear-0.3.40.zip`, revision
`c262a2d2b3b427e254623cbe83177750b19ba04c`. Local and final remote SHA-256:
`5a119ed4af0765bcc852f8a3d065d505dd778f9a1cfdf62a31ae5fb5160b51d8`.
956 backend tests passed (six skipped), 159 frontend tests passed; typecheck,
architecture, compilation, build, package and diff checks passed. Not installed.

Unifies the quick menu and animated connection popup, adds five compact live
readiness checks, and a read-only Disconnect status dialog. No live-release
RPC is wired: Ally audio, GPU release and final unplug verification explicitly
show unavailable. A clean resource scan never authorizes physical unplug.
Includes registered offline-ui and quick-launch-name commits. Native layout
and controller acceptance remain pending. Staging is not installation.

## Compact gear and minute refresh - 2026-09-05

0.3.38-offline.1 revision 07b22bf includes installed popup lineage 02d9c84.
Artwork uses a single status-in-gear SVG at bottom-left, aligned to Steam's
symbol center with a 24px size cap (24x24 fallback). Selected-game checks
repeat 60 seconds after completion; selection change/unload cancels the timer,
and gameplay/context guards suppress requests. Automatic badges expire to
neutral at 65 seconds if a refresh fails or does not finish; successful refresh
replaces the badge before expiry. No library scan or network request added.
955 backend tests (six skipped), 156 frontend tests, architecture, compilation,
TypeScript, production build and package/provenance validation passed.
Staged /home/deck/Re-Gear-0.3.38-offline.1.zip; matching SHA-256:
CA3EA0EF73FBB8E8A20C1A3E1403546FBC0CC8A940188163FBBD8E6EDF7D25D8.
Installed before staging: 0.3.38-popup.1 revision 02d9c84. No install/restart.
New filename, no existing ZIP overwritten. Compact icon visual acceptance and
minute refresh on device remain pending.

## Badge stacked above Steam - 2026-09-04

0.3.37-offline.1 revision 1f08bd3 positions Re-Gear above the native Steam
compatibility group on both landscape and portrait covers, right aligned with
four CSS pixels of clearance. Native glyph sizing remains; missing native
reference falls back to bottom-right at bottom 38px, size 64x32. Automatic-only
checks and persistent neutral expiry remain unchanged.
955 backend tests (six skipped), 152 frontend tests, architecture, compilation,
TypeScript, production build, package and provenance checks passed.
Staged /home/deck/Re-Gear-0.3.37-offline.1.zip; matching local/remote SHA-256:
6A70A44633401E390B64A87ACDBD219796412E99975BABB30F07C903C8771D10.
Installed before staging: 0.3.36-offline.1 revision 24b39befb0de.
No installation or restart. New filename verified absent before transfer;
other workstream archives preserved. Player visual confirmation still pending.

## Re-Gear 0.3.38-popup.1 candidate

Combines the committed 0.3.37 offline badge lineage with plugin-owned
connection progress monitoring. Fresh disconnected-to-connected observations
open one popup without opening Quick Access; initial attached state does not.
One-second serialized status refresh updates the checklist. Automatic popups
show one Hide action; manual View progress retains guarded TV switching.
No backend transition behavior changed. Native popup timing remains unverified.

## Steam-reference icon sizing - 2026-09-04

0.3.36-offline.1 revision 24b39be uses a bounded same-tile native lower-right
square SVG reference to match visible symbol height and center. The supplied
asset's 80/128 status-circle ratio is included in sizing; fallback is 64x32.
The percent-width shrink is removed. Native two-SVG group bounds reserve room
for Steam controls; unusually narrow covers move our badge above rather than
overlap. Only Re-Gear styles are changed. No new timer or resize observer.
Live diagnostic inspection found no carousel on the current Steam surface;
new geometry is tested synthetically, not visually verified on device.
955 backend tests (six skipped), 152 frontend tests, architecture, compilation,
TypeScript, build and package/provenance checks passed.
Staged /home/deck/Re-Gear-0.3.36-offline.1.zip; matching SHA-256:
2014635357F0A950FE63328198E29454FE8647DEEF3BAB1C622C4A2719AAE1D7.
Installed before staging: 0.3.35-offline.1 c0590e58abeb. No installation,
restart or existing archive overwrite. Automatic-only behavior retained.

## Automatic-only offline UI - 2026-09-04

0.3.35-offline.1 revision c0590e5 removes the manual Offline Readiness panel,
game picker, check button and manual test confirmation from Quick Access.
The plugin-lifecycle automatic checks and artwork badges remain. Manual-panel
source is dormant and tree-shaken from the build; no manual check is required.
Includes the narrow-cover and persistent neutral-expiry fixes.
Staged at /home/deck/Re-Gear-0.3.35-offline.1.zip; matching local/remote SHA-256:
B6A38CF5B83C2D38C116BDCBDCBB519CBE6A0F26FF15E5D92086C6057B7F716E.
Installed before staging: 0.3.34-offline.1 revision 1ab3b2f8d097.
955 backend tests (six skipped), 149 frontend tests, architecture, compilation,
TypeScript, build and package/provenance checks passed. No installation, restart
or existing ZIP overwrite. Player validation remains pending.

## Combined badge restoration staged - 2026-09-04

Installed 0.3.33 revision 263dc089 retained confidence/branding but omitted
narrow-cover sizing and neutral expiry fixes. Candidate 0.3.34-offline.1
revision 1ab3b2f starts from that installed revision and restores those exact
source/test changes, preserving the Re-Gear Quick Access rename.
Staged: /home/deck/Re-Gear-0.3.34-offline.1.zip. Local/remote SHA-256:
98CCA0F609101F021C53E94E9CA41655D387A7182F8BD9C818E1D7EF3944EF0F.
955 backend tests (six skipped), 149 frontend tests, architecture, compilation,
TypeScript, build, package/provenance and diff checks passed. No installation
or restart. No existing ZIP overwritten. Native visual acceptance pending.
Use branch fix/combined-badges-0.3.34 as the integration reference for these
fixes; taking only the older offline confidence commit loses them.

## Re-Gear 0.3.31 live connection progress candidate

Adds a dismissible live readiness popup and persistent View progress control.
Independent existing observer checks now include sample age; stale/error reads
cannot stay green. Automatic behavior is unchanged. With automatic docking off,
fresh complete readiness offers the guarded Switch to TV action. See
[popup contract](CONNECTION_PROGRESS_POPUP.md). Native layout and hardware
delivery remain unverified; this candidate is not installed.

## Re-Gear 0.3.30 bidirectional display shortcut candidate

Back/View + Y held for three seconds opens Switch to TV from Portable or
Return to Ally from TV Docked. Fresh idle evidence and an idle journal are
required; mode changes during the hold cancel it. Both confirmations use
existing supervised backend guards. The shortcut cannot request shutdown;
that remains a separate panel action. Not installed or hardware validated.

## Re-Gear 0.3.29 Back/View shortcut candidate

The player selected Back/View (two overlapping boxes) + Y for three seconds
after Xbox holding on the Bluetooth Raikiri II powered the controller off.
The native listener and pure policy now require View + Y. Xbox/Guide + Y is
no longer bound. Same confirmation and backend guards; no execution shortcut.
Button mapping comes from Steam API declarations; actual Bluetooth delivery
remains unverified. The player confirmed panel-driven return to Ally display
and speakers; G1 remains attached, and shutdown reliability remains unresolved.
Install only after full power-off, G1 removal and detached boot.

## Re-Gear 0.3.28 controller API compatibility candidate

Installed 0.3.27 displayed Controller shortcut unavailable. Read-only API
inspection found button messages available but controller-list registration
absent. A bounded subscription probe verified button and active-controller
registration return unregister handles. The adapter now accepts the active
controller notification API as a fallback. Physical button/hold/disconnect
delivery remains unverified. No display, sleep or GPU action was performed.

## Re-Gear 0.3.27 controller safe-disconnect candidate — 2026-09-04

Combines the committed neutral Offline Play badge correction from d76ddb7
with the controller candidate; 0.3.26 was already staged by that workstream.

Xbox/Guide + Y held for three seconds now has a native Steam input subscription
candidate that opens the existing safe-disconnect confirmation. It requires
fresh idle/safety-journal evidence and preserves backend approval/revalidation.
The gesture policy uses the requested three-second threshold. Power-button
double press remains unsupported. See the
[controller contract](CONTROLLER_SHORTCUT_PRESENTATION.md) for source, cleanup,
bounds and hardware gates. Not installed or hardware validated.
Local validation: 954 backend tests (six skipped), 124 frontend tests,
TypeScript, architecture, compile, production build and package checks passed.

## Re-Gear 0.3.25 audio activation candidate � 2026-09-04

The [audio sequencing candidate](G1_AUDIO_ACTIVATION.md) separates pre-display
rollback readiness from post-display HDMI audio proof. It preserves rollback
before restart, bounds sink-availability polling, and requires the recovery
mechanism even if the source display is already visible. No profile forcing or
driver mutation was added. It includes the committed 0.3.24 UI lineage.
Validation: 954 backend tests (six skipped), 110 frontend tests, architecture,
compilation, TypeScript, production build and package checks passed. Candidate
only: no installation or hardware validation by this workstream.

## Re-Gear 0.3.24 Home and Library tab refresh candidate � 2026-09-04

The player reports missing Home artwork badges and unreliable badges after
Library tab changes on installed 0.3.23 (`57ebfb9b8cca`). Read-only inspection
of Steam's existing debugging endpoint confirmed a registered focus listener,
a matching focused Home listitem, exact numeric tile identity, positioned
artwork, available native details interface, and zero badge nodes at that
instant. This does not establish why the earlier badge was absent: the
30-second expiry and evidence/game gates remain possible contributors.

The candidate adds a `/library/home` attachment retry and observes DOM changes
in known navigation windows to reconsider only the active tile. Tile or exact
identity changes refresh the check even without focusin. Unrelated mutations
do not restart the 450 ms delay or repeat detail requests; no library scan or
periodic timer was added. Registered windows are rechecked on route callbacks,
and observers disconnect on unload. G1 runtime remains unchanged.

Validation passed: 943 backend tests (six skipped), 110 frontend tests,
architecture, compilation, TypeScript, production build, and package check.
Regression tests cover tab replacement without focusin and repeated unrelated
mutations. Native Home/tab-switch visual acceptance and actual overhead remain
unverified. This is a candidate fix, not a confirmed resolution of the report.
No plugin installation, restart, or hardware transition was performed.

## Re-Gear 0.3.23 Offline Readiness review � 2026-09-04

Local UI candidate based on integrated `37daf74`; G1 runtime is unchanged.
Artwork `src` changes now invalidate recycled Library tiles, and automatic
attachments remain restricted to the original focused tile after DOM updates.
Requests recheck actual focus and Steam's running display status before showing
results; classification failures are contained and a later focus can retry.
The four `*-gear.svg` assets match fetched `origin/main`; only attention and
online-check assets are imported because evidence cannot prove offline launch.

Validation: 943 backend tests (six skipped), 108 frontend tests, architecture,
Python compilation, TypeScript, production build, and package check passed.
New tests exercise artwork-only recycling, duplicate tiles, startup focus,
focus loss/game start, failed classification retry, and late classification.
These are simulated checks, not native Steam visual or gameplay validation.

A subsequent SSH retry succeeded. Installed metadata reports 0.3.22 revision
`37daf74a025785b4c1b581fc6bba64eb735f32cd`; PCI observation shows the external
AMD `1002:7480` GPU present. Do not install or restart while G1 is attached.
Candidate 0.3.23 was copied to `/home/deck/Re-Gear-0.3.23.zip`; local and remote
SHA-256 match `BFBB1BAC93BF986712551D908122624564E42A79153612F6966C9EA2D84EEC7A`.
The enumerated superseded `/home/deck/Re-Gear-0.3.22.zip` was removed after hash
verification. No installation, restart, or hardware transition was performed.
Current visible badge behavior remains unverified.

Remaining review limits: the badge expires after 30 seconds, cache is volatile,
and manual/automatic attachment handles can overlap on the same tile. Native
Home startup attachment, bottom-left layout, scrolling cost, and absence during
gameplay still need device evidence. Metadata remains insufficient for Ready
Offline or Requires Internet conclusions.

## Re-Gear 0.3.22 late-enumeration candidate � 2026-09-04

The supervised 0.3.21 attach began with `observation.wake.kernel_event`, then
reported timeout at 120.593 seconds from a `poll_timer` scan. Kernel Link Up
arrived about 168 seconds after USB4 discovery; Re-Gear observed the exact G1
at 169.240 seconds. Later read-only evidence verified the GPU bound to amdgpu
and TV HDMI/EDID present, with only the internal display active. PCI BAR
assignment failures were logged during enumeration; their causal role is
unproven. Evidence: `out/ally-0.3.21-late-enumeration.jsonl` and
`out/ally-0.3.21-late-enumeration-state.json` in the release worktree.

The local 0.3.22 candidate allows first exact G1 enumeration after timeout to
open one fresh 120-second readiness window on that transport. It binds the
identity and discards prior settling samples. Unknown identity, a transport
failure requiring absence, repeated events, and a second timeout do not renew
that window. Existing game/session/audio/display/link gates and automatic
transition one-shot/Portable-suppression state remain authoritative. This is
late-arrival handling, not a fix for the underlying kernel enumeration delay.
Local checks passed: 943 backend tests (six skipped), 102 frontend tests,
TypeScript, architecture, compilation, build, and package validation.
Not installed or hardware validated; keep the connected Ally untouched until
normal shutdown, confirmed power-off, disconnect, and detached boot.

## Re-Gear 0.3.21 G1 readiness candidate � 2026-09-04

Unreleased local changes invalidate readiness and reset settling counters when
transport observation becomes unknown. The 120-second initial deadline stops
applying after topology, HDMI, audio, and session readiness settle, allowing
game completion or result acknowledgement later; fresh observations still gate
every request. Verified absence or changed identity resets initial readiness.

Wake diagnostics distinguish kernel events, local changes, mixed wakeups,
observer degradation, and timer polling at readiness changes and automatic
transition requests. These describe what woke the scan, not device-specific
causality. Local validation passed: 938 backend tests (six skipped), 102
frontend tests, architecture, compilation, TypeScript, production UI build,
and package checks. Hardware validation remains pending; the candidate is not
installed. Read-only verification found 0.3.20 installed on the detached Ally
before staging this candidate.

## Re-Gear 0.3.17 observed-link correction — 2026-09-04

The first 0.3.14 hardware attach verified the exact G1 profile and G1 HDMI, but
the readiness window remained at `waiting_for_link` and timed out. Direct
read-only observation showed the exact removable bridge was Up at 2.5 GT/s x4
with `observed` confidence. The integration had incorrectly required `verified`
confidence even though the profile-bound link adapter intentionally reports
observed sysfs link state. The 0.3.17 candidate accepts observed or verified Up
only after exact G1 topology is established; Down and Unknown still fail closed.
It is not installed or hardware validated.

## Re-Gear 0.3.14 combined G1 readiness candidate — 2026-09-04

The 0.3.13 Offline Play and UI lineage now includes the hybrid G1 connection
pipeline: bounded Thunderbolt/PCI/DRM event wakeups, adaptive polling through a
120-second enumeration window, exact USB4 and complete G1 identity, driver and
link checks, G1-backed HDMI/EDID, read-only selectable TV-audio and Portable
rollback validation, Gamescope readiness, and known idle game state. Four
topology samples and two HDMI/audio samples are required before the existing
one-shot automatic transition engine may receive a request.

The readiness observer does not reset USB4, rescan PCI, authorize devices, bind
drivers, or mutate display/audio state. This combined candidate is not installed
or hardware validated. Stage its ZIP only in `/home/deck/`, verify the installed
version first, and remove superseded ZIPs from `/home/deck/` and
`/home/deck/Downloads/` before the supervised detached-install test.

## Re-Gear 0.3.11 transparent white icon correction — 2026-09-04

The installed 0.3.10 lineage still imported the 0.3.6 black-filled gear asset.
This UI-only correction embeds the user's white gear-and-handheld RGBA PNG so
the Decky row color shows through every transparent area. It preserves the
0.3.10 focused-game/offline and G1 runtime changes and does not modify backend,
RPC, polling, lifecycle, or safety behavior. Not installed or hardware validated.

Manual-install package staging now uses `/home/deck/Re-Gear-<version>.zip`.
After verifying the current candidate's SHA-256, remove older Re-Gear and
HandheldDockMode ZIPs from `/home/deck/` and `/home/deck/Downloads/` so only
the current installation candidate remains.

## Re-Gear 0.3.8 combined G1 audio readiness candidate — 2026-09-04

Installed 0.3.7 revision `52db288056c3` and the separately built 0.3.7 audio
candidate `9d85b35` collided on the same version. The installed build did not
contain the audio readiness change. This candidate starts from the installed
runtime revision and adds that bounded change, then advances the version to
0.3.8. It requires two consecutive matching exact G1 HDMI sink observations,
bounded to six attempts at 250 ms intervals, before any audio mutation.

The triggering hot-attach attempt bound the G1 GPU but twice failed automatic
docking at `audio.external_sink_ambiguous`. PipeWire later showed one exact G1
HDMI loopback sink. This supports a transient readiness defect; hardware
validation remains required. Keep G1 detached for candidate installation.

## Re-Gear 0.3.7 combined candidate — 2026-09-04

- Local candidate combines the preserved 0.3.6 G1/runtime and transparent-icon
  release baseline with Offline Readiness, the latest compact Quick Access UI,
  and supplied offline badges. This is a build candidate, not installed evidence.
- Full integration gate passed: architecture, 913 backend tests (6 skipped),
  compilation, TypeScript, 101 frontend tests, frontend build, package check,
  and whitespace validation.
- Do not overwrite the shared installed runtime while G1 is connected. The ZIP
  may be staged in the deck user's home without changing the running plugin;
  installation still requires a detached/idle coordinated window and rollback.

## Re-Gear 0.3.6 transparent icon — 2026-09-04

Replaces the opaque JPEG background with a derived RGBA PNG in list and header.
Alpha inspection: 1254x1254, 668393 fully transparent pixels, corner alpha 0.
White internal details remain opaque. Original supplied artwork is retained.
No backend, identity, lifecycle or polling changes. Not installed or uploaded
by this update; native Decky visual validation and identity migration remain open.

## Re-Gear 0.3.5 icon selection — 2026-09-04

Supersedes the 0.3.4 artwork with the user's unmodified black gear JPEG,
`docs/images/re-gear-decky-black-gear.jpg`, in the list and header. White
background is retained. No runtime or identity changes; the Decky name
migration remains pending. Not installed, uploaded or published by this update.

## Re-Gear 0.3.4 icon candidate — 2026-09-04

Based on the combined 0.3.3 candidate `3c182d6`, this update embeds the
user-supplied monochrome JPEG as the Decky list and panel icon. Original artwork
is retained. Backend, RPC, lifecycle, polling and safety logic are unchanged.
The Decky list still uses the legacy plugin identity; the requested Re-Gear
list rename is deferred pending a tested identity migration (see BRANDING.md).
This candidate is not installed or published and does not close hardware gates.

## Re-Gear 0.3.3 UI integration candidate — 2026-09-04

This isolated packaging branch starts from G1 runtime
`412b9dc8f6b573450e174fc87f15d4e48b56dd66` (0.3.2) and incorporates
the UI-only changes from `75f441f`, `3a54108`, and `b83f324`.
The backend, lifecycle code, RPC contracts, polling, safety conditions, and
runtime journal acknowledgement retirement are preserved. Generated frontend
outputs are rebuilt from this combined source, not copied from the UI branch.

Package and Python versions are 0.3.3; the archive is `Re-Gear-0.3.3.zip`.
Legacy Decky identity and internal `HandheldDockMode` directory are unchanged.
Offline Play and Auto TDP workstream implementations are intentionally excluded.
This is a local validation candidate, not a published release or installed build.
Actual Decky controller/layout validation and G1-connected shutdown remain
unverified for this candidate. No hardware operations are part of packaging.
The dated observations below remain historical, not current device evidence.

Local integration verification: 884 backend tests (6 skipped), 78 frontend
tests, architecture, compileall, typecheck, fresh build and package checks pass.
The production-action host surrogate passes 240/280/320px layout, keyboard-focus
and disabled-state checks; this is not native Decky/controller proof. Every
non-render statement in Content matches the runtime base; backend, main.py,
RPC contracts and polling files have no differences. The UI regression assertion
now matches the published polish's 32px icon tile and multiline style formatting.

## 0.3.2 local event-loop responsiveness repair — 2026-09-03

The automatic loop constructed its presentation service on the event-loop
thread before passing a bound method to asyncio.to_thread. That uncached
factory scans Gamescope processes and prepares runtime storage on every call.
A blocked factory reproduced event-loop starvation: a queued callback could
not run until the factory was released. Factory construction plus invocation
now run inside the worker for automatic completion/execution, background audio
handoff, and supervised presentation RPCs. Existing transition approvals and
tracked background-operation ownership remain in place.

Regression verifies a callback runs while the factory is blocked off-loop.
Architecture, 884 backend tests (six skipped), and compilation passed.
This is a demonstrated local defect with plausible shutdown-handler impact;
the actual Ally hang is not attributed to it. The local Windows Decky fork
shows SIGTERM scheduling unload on the event loop, but is reference evidence,
not verified installed Linux loader source. Installed Ally remains 0.3.1 and
detached; no runtime changes were made during this investigation.

## Re-Gear 0.3.1 shutdown failed; detached recovery — 2026-09-03

Installed 0.3.1 `62f7333a69ff` was verified on disk and in the startup journal.
The player confirmed working picture/audio/controls with powered G1 attached.
The supervised normal shutdown again left fan/LEDs on beyond one minute;
the player forced poweroff, detached G1 while off, and booted successfully.
Player confirms picture/audio/controls; capture-20260904T053225Z.json shows
Idle and only the internal GPU present. Keep G1 detached during diagnosis.

Version/timestamp correlation is essential: the previous-boot `unload_started`
marker belongs to 0.3.0 being replaced during installation, not the later 0.3.1
shutdown. For the latter, Decky recorded a stop request and response-listener
stop at 1788499653329876/1788499653329992 us, then SIGKILL at
1788499658344191 us. No loader-unload, hook-attempt, or Re-Gear cleanup marker
for that shutdown was retained. Startup confirms 0.3.1 ran; the bounded cleanup
path has not been shown to execute at shutdown. This does not establish why
the backend failed to enter unload, or why the whole machine failed to power off.
Do not infer a particular cleanup await from the mixed-boot aggregate.

Evidence: out/regear-0.3.1-shutdown-timeline.json,
out/regear-0.3.1-failed-shutdown.json, and out/regear-0.3.1-shutdown-live.jsonl.
Live SSH capture ended before any shutdown messages. Aggregate tail reached
2000 rows; whole-boot AER/xHCI counts do not establish shutdown causality.
Next investigate Decky-to-backend stop delivery and event-loop responsiveness
before another code candidate or attached shutdown trial.

## Re-Gear 0.3.1 local shutdown candidate — 2026-09-03

Local cleanup now closes background admission, requests every observer stop
before waiting, and uses a shared one-second observer deadline plus a separate
three-second sleep-guard release deadline. Already-started automatic display
and recovery audio operations remain tracked when their observer is cancelled.
Pending work produces categorical timeout/incomplete checkpoints, never a
successful unload marker. The collector recognizes each new checkpoint.

Regression tests cover blocked cancellation, other observers and guard still
stopping, retained in-flight mutation ownership, closed admission, and a blocked
guard release. Architecture, 883 backend tests (six skipped), compilation,
TypeScript, 77 frontend tests, build and package checks passed. Independent
review found no blocking issue. A lock-blocked watcher close was reproduced
locally; it has not been identified as the observer in the recorded Ally hang.
This does not prove final OS shutdown or live removal safety. Worker ownership
does not guarantee worker completion after Decky retires its process.

Installed hardware remains 0.3.0 `9571a5ca3e5b`. The latest cold G1 attach
enumerated its AMD GPU and requested automatic docking, but failed with
`audio.external_sink_ambiguous` before display switching. The TV was on another
input; its causal role and event-versus-fallback trigger are unproven. HDMI
validation is deferred by the player. No hardware mutation was made for 0.3.1.
Next: detached installation of the candidate, then a separately supervised
shutdown capture. Disconnect only after physical poweroff is confirmed.

## Failed shutdown and detached recovery — 2026-09-03

The supervised ordinary shutdown on installed 0.3.0 `9571a5ca3e5b` again left
fan/power LEDs on after SSH closed. The player used a forced power-button hold,
confirmed poweroff, disconnected G1, and booted detached. Player confirmed Ally
picture/audio/controls; read-only capture confirms Idle, internal display active,
only internal GPU present, and the same installed version.

The shutdown-window journal shows HDM unload_started, Steam stopping in about
2.54 seconds, Gamescope stopping in about 1.42 seconds, then a Decky SIGKILL
entry naming HDM about 5.01 seconds after its unload start. No subsequent HDM
cleanup checkpoint was retained. This establishes incomplete HDM cleanup in
this shutdown, not the cause of final machine poweroff failure. No final
poweroff-stage evidence was retained. Whole-boot PCIe AER/xHCI counts were not
in the shutdown window and must not be attributed to it.

Current-boot logs show observation.events_ready, completion.portable_released,
and completion.idle. Fresh automatic attach is now eligible for supervised
testing after normal readiness gates; this is not proof of successful docking.
Next local shutdown investigation: identify the HDM observer await that prevents
cleanup, reproduce it, and fix only that lifecycle path. Do not widen process
termination or driver-reset authority. Local evidence: out/shutdown-failed-20260904-*.json,
out/shutdown-20260904-window.json, out/shutdown-hdm-and-detached-events.json,
and remote-captures/capture-20260904T045931Z.json.

## Shutdown capture repair — 2026-09-03

Developer-only capture now handles bounded journal byte messages and reports
omitted/ambiguous message coverage explicitly. Fixed current/previous boot and
kernel/service/plugin selections avoid mixed-tail crowding. A bounded live
reader streams validated redacted summaries to the development computer before
SSH closes; it never initiates shutdown or changes remote configuration.
Verification: 21 collector/live tests, architecture, compileall and diff checks
passed. A 30-second live dry run exited cleanly. Separate previous-boot reads
returned 1296 kernel, 1365 service and 1272 plugin rows without malformed rows,
but no final poweroff or HDM unload evidence. Installed Re-Gear remains 0.3.0
`9571a5ca3e5b`; these scripts are not part of the plugin archive. Next: one
player-requested poweroff with live capture, then physical-state confirmation and
retained-log retrieval after a safe boot. SSH loss is not poweroff proof.

## Graceful session experiment — 2026-09-03

On installed 0.3.0 `9571a5ca3e5b`, one explicitly supervised no-force session
stop completed; SteamOS automatically restored the session. Temporary overrides
were removed and native service settings verified. The maintainer confirmed restored Ally picture, audio and built-in controls. This does not resolve
the shutdown hang or authorize unplugging. See the
[experiment record](G1_GRACEFUL_SESSION_EXPERIMENT_2026-09-03.md).

## Re-Gear 0.3.0 packaging checkpoint — 2026-09-03

New candidates use `Re-Gear-<version>.zip`; package.json and pyproject.toml now
agree on 0.3.0. The combined dashboard/event-trigger candidate retains the legacy
Decky installation identity. CI, candidate validation and deployment selection
use the branded name; historical rollback verification accepts either prefix.
Version policy is recorded in RELEASE_PIPELINE.md. Verification passed architecture,
874 backend tests (six skipped), compilation, TypeScript, 77 frontend tests,
build, package and diff checks. This is a local candidate, not installed or
hardware validated. Next: supervised detached install and automatic-dock test.

## Re-Gear branding integration

Re-Gear is the public product name. The runtime branch integrates the UI
workstream's `8067a04` branding/artwork and `20d0749` self-contained image loader
with the `7afa509` lifecycle fixes. The supplied PNG is embedded byte-for-byte;
the journal-idle acknowledgement fix remains intact. Legacy installation IDs,
state paths, GitHub links and checkout paths remain unchanged as documented in
[branding compatibility](BRANDING.md). Combined local gates: 873 backend tests
(six skips), 73 frontend tests, architecture, compile, typecheck, build and package
checks passed. No rebranded build is yet installed or hardware-validated.

## Local automatic-lifecycle candidate — 2026-09-03 late session

The maintainer confirmed TV picture/audio and a Prepare G1 disconnect return to
Ally picture/audio/controls on installed `1981259840ce`. This proves one watched
software cycle, not repeated reconnect or physical removal. The
[automation plan](G1_AUTOMATION_PLAN_2026-09-03.md) tracks local completion receipts,
durable Portable suppression, PCI/DRM event wakeups with fallback, and categorical
logs. Local verification: 873 backend tests (six skipped), 69 frontend tests,
architecture, compile, typecheck, build, package and diff checks passed. These
changes are not installed or hardware-validated. Older state below is historical.

## Shutdown follow-up — 2026-09-03

The latest maintainer report is an incomplete attached-G1 shutdown (fan and LEDs
still on); eventual poweroff is unknown. The
[shutdown review](G1_SHUTDOWN_REVIEW_2026-09-03.md) preserves the other hardware
audit's safety findings. Local code now prevents an already-failed HDM observer
from skipping owned sleep-guard cleanup and adds categorical unload checkpoints.
A developer-only previous-boot journal collector adds no production polling or
remote mutation. This is not a verified fix for the hardware shutdown hang.

## Latest G1 checkpoint — 2026-09-03

See [the package/audio incident record](G1_LIFECYCLE_VALIDATION_2026-09-03.md).
Installed base `3a5d1620ddf8` failed a session restart because the launcher shipped
CRLF. An approved in-place LF repair restored Steam; a subsequent TV picture/audio
and return-to-Ally display/control cycle passed. Return audio remained HDMI and
required manual selection. LF package enforcement, Portable audio baseline guards,
and separate audio-result diagnostics are locally implemented with regression
tests, not yet validated as a new installed build. Older entries below are
historical. No live-removal claim has changed.

Last repository audit baseline: **2026-09-02**. This page records a dated
implementation baseline rather than attempting to name its own containing Git
commit. Re-verify all mutable facts before a build, deployment, merge, or
hardware session:

```text
git status --short --branch
git rev-parse HEAD
git rev-list --left-right --count origin/main...HEAD
```

## Repository

| Field | Audited value |
|---|---|
| Branch | `main` |
| Audited implementation baseline | `a988c0cf1d61376b3450db74a04b6c2c29a373dd` |
| Governance integration | Repository-governance commits follow that baseline locally; inspect `git log` for the live tip |
| Worktree | Clean at the audit baseline; verify live before acting |
| Remote relation | Mutable; run the commands above before relying on it |
| Project version | `0.2.0` from `package.json` |

Do not describe a public CI run, release, or remote branch as hardware
validation. Before integration, fetch, re-check ancestry and worktree state,
run the appropriate verification gate, and obtain explicit authorization before
push or publication.

## Build and deployment truth

- A Decky archive embeds semantic version and full source revision in
  `build_info.json`; dirty source reports `uncommitted`.
- Controlled artifacts bind the archive to `source-revision.txt` and a SHA-256
  manifest. ZIP filenames alone are never provenance.
- No artifact is promoted as current by this page. Build and verify one package
  from the intended clean commit for each validation session.
- The last live observation reports installed HDM `0.2.0`, public revision
  `a988c0cf1d61`, on 2026-09-02. A watched automatic attach first returned to the
  Ally after a black-TV attempt. Kernel evidence showed the G1 PCI function bind
  to `amdgpu` followed by repeated non-fatal PCIe AER recovery failures for the
  G1 USB controller. After the player acknowledged the recovered transition, the
  automatic retry activated the TV. Read-only evidence verified the external
  display active and internal display inactive; the unprivileged collector could
  not read the Gamescope render-selector environment.
- The same automatic retry selected the exact G1 HDMI loopback sink as the default
  audio output, and the subsequent supervised Portable transition activated the
  Ally display while leaving the TV connected but inactive. This hardware run
  therefore validates automatic audio selection and display return for one cycle,
  but not repeatability or physical shutdown.
- Historical candidate and deployment records are snapshots, not current truth.
  See [Operator handoff](OPERATOR_HANDOFF.md) and dated deployment records for
  their exact context.

The repository-to-runtime proof chain is:

```text
repository HEAD
  -> clean build embeds version + full revision
  -> artifact manifest binds revision + ZIP SHA-256
  -> installer validates embedded metadata
  -> installed build_info reports version + revision
  -> runtime diagnostics reports that installed identity
```

Artifact checksum and deployment timestamp are not yet persisted in installed
runtime metadata. That is a Phase 2 provenance gap, not a fact to infer from a
local ZIP.

## Capability summary

- Read-only discovery, exact first-profile identity, diagnostics, health,
  support preview/export, sleep protection, and guarded/supervised foundations
  are implemented to the evidence levels recorded in [Roadmap](ROADMAP.md).
- Deterministic transition/recovery behavior does not by itself prove hardware
  operation.
- Automatic TV/display docking is hardware validated across watched attaches.
  Installed `a988c0cf1d61` initially recovered to the Ally after a black-TV
  attempt, then its acknowledgement-driven retry activated the TV and selected
  G1 HDMI as the default audio sink. The same build subsequently returned to
  verified Portable through **Prepare G1 disconnect**. Unprivileged capture
  could not verify the Gamescope render selector, so this run does not add a new
  render-GPU claim.
- The first-attempt recovery, later successful retry, and intervening USB
  controller AER errors do not prove that a shorter delay is safe. The runtime
  branch keeps 250 ms sampling but requires four distinct consecutive
  fully-ready observations before automatic transition. Repeated samples and
  any identity, EDID, link, session, or game regression reset the quorum. This
  remains locally tested pending supervised timing evidence.
- A locally tested instrumentation update now retains privacy-safe monotonic
  elapsed time for G1 presence/readiness changes, automatic and supervised
  presentation attempts/results, Portable return, and shutdown requests.
  Temporary verbose logging also retains the existing bounded collector timing
  rows instead of only their count. This does not change polling or transition
  authority and remains uninstalled/unverified on hardware.
- One player-directed idle live pull left the Ally backlight black while
  Gamescope and Steam were absent, then SteamOS natively restored Gamescope on
  the internal panel after approximately 80 seconds. The player verified Steam
  and built-in controls after recovery. A local supervisor now binds the last
  exact idle TV-Docked observation, waits for and verifies that native Portable
  recovery, and then restores the captured Portable audio sink. It never
  restarts Gamescope or authorizes removal. This code is implemented/simulated
  and installed as revision `85be5385255a`; it has not been exercised through
  another intentional pull.
- A later attach on that installed revision exposed a distinct reconnect
  failure: USB4 and PCI enumerated the RX 7600M XT, but `amdgpu` did not bind,
  no G1 DRM device or external connector appeared, and HDM correctly remained
  Portable. No driver probe, bind, unbind, or USB4 reset was attempted. This is
  evidence that native Portable recovery does not by itself guarantee a clean
  subsequent reconnect.
- Installed `a988c0cf1d61` exercised the controller-focusable two-stage
  disconnect fallback through verified TV-to-Portable recovery. Its
  acknowledgement incorrectly re-armed automatic docking, requiring the player
  to disable automatic TV docking first. The follow-up implementation persists
  the categorical requested target and suppresses redocking after a Portable
  acknowledgement until the exact G1 disappears.
- The same watched run failed the physical shutdown gate. The fixed power-off
  request removed SSH and ping, but the Ally fan and two top LEDs remained on
  until the player held the power button for approximately twelve seconds. The
  follow-up UI labels command acceptance as physically unverified and provides
  a manual recovery instruction; it does not automate forced power-off. Exact
  attach-settling and correlated-loss observation remain at 250 ms.
- Automatic docking remains behind an off-by-default persistent player opt-in.
  Boosted Handheld and physical
  live eGPU removal are not available. The current G1 policy remains shutdown
  before disconnect.
- A prior live attach exposed a terminal shared journal that automatic docking
  mislabeled as a TV acknowledgement even though both the presentation and
  process-release services rejected ownership. The local correction reports
  the categorical owner, offers exact acknowledgement only for a terminal sleep
  journal, keeps unknown/incomplete journals fail-closed, and re-arms the same
  attachment after a valid owner acknowledgement. That correction is installed;
  the exact presentation acknowledgement and subsequent automatic retry were
  observed on hardware.

## Active ownership

- **Hardware-journey driver:** ASUS ROG Ally X + GPD G1 connect, TV Docked,
  gameplay, return to Portable, sleep/recovery, reconnect, and repetition on
  real hardware.
- **Repository-governance driver:** authority, documentation, Git/version truth,
  diagnostics contract, parity/UI audits, CI, templates, and repository hygiene.

The governance workstream must not deploy, run hardware transitions, or edit the
hardware driver's active runtime path without coordination. Shared documents
must preserve the distinction between implemented, simulated, installed, and
hardware-tested behavior.

## Immediate gates

1. Build and install the target-aware acknowledgement correction with the G1
   absent. Keep the Ally Portable long enough for HDM to capture its current
   default audio sink.
2. Repeat one watched automatic attach and verify TV picture, RX 7600M XT render
   selection, automatic TV audio, and one committed transition.
3. Repeat **Prepare G1 disconnect**, acknowledge while automatic docking remains
   enabled, and verify HDM stays Portable with the shutdown-request control
   available.
4. Validate ordinary attach/return behavior with the installed native-recovery
   supervisor before any separately approved repeat of an unexpected-loss
   scenario.
5. Treat complete physical power-off as failed until the fan stops without a
   forced hold. Never disconnect merely because the request was accepted or the
   network disappeared. Do not perform a powered live pull.
6. Diagnose the observed unbound-G1 reconnect with a separately approved,
   supervised one-shot driver-probe experiment before adding any recovery
   mutation.
7. Design the Phase 2 unified installed diagnostic report and deployment record.
8. Resolve the P0/P1 hardware-coupling findings with narrow profile-driven seams
   and synthetic tests before claiming future-device extensibility.
