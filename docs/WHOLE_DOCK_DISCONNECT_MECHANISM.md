# Whole-dock disconnect investigation — September 11, 2026

**Current safety hold:** The owner reported excessive G1 heat after a timed-out
software reconnect and disconnected the cable. Further powered reconnect trials
are paused. See "Thermal incident: software reconnect trials paused" below;
earlier trial instructions are historical and do not override this hold.

## Goal and preserved baseline

One player action: return to the internal display, release dock resource users, verify release, execute supported dock-level teardown, then verify the entire relevant connection before offering cable clearance. Keep installed 0.3.82 and tag `checkpoint/0.3.82-auto-tv` unchanged. This investigation contains no device writes or unplug trial.

## Current evidence

Reviewed origin/main 280d760 and existing issue #105. The historical issue records USB-branch ACS violations and xHCI AER recovery failure, separately from successful GPU/audio software removal. It does not establish that a generic USB eject resolves that failure.

A fresh read-only run of the existing removal-capability collector on the attached Ally reports domain deauthorization supported, user security, and an authorized external router. Router identifiers were not published. The collector explicitly leaves GPU-to-router binding unverified. This establishes a available kernel capability, not a writable privileged path or whole-dock removal success.

## Existing code to retain

- `backend/regear/application/live_disconnect.py` and `delivery/live_disconnect_runtime.py`: guarded resource release and GPU/audio removal flow.
- `backend/regear/domain/dock_teardown.py`: existing pure decision contract for the remaining dock; requires removed GPU, complete unused-storage evidence, supported identified tunnel, scoped approval and complete observations.
- `backend/regear/adapters/steamos/dock_branch.py`: read-only USB/storage/tunnel observations. It is not an executor.
- Canonical follow-up task: `egpu-whole-dock-teardown-executor`. Do not replace these contracts with an independent eject path.

## Linux mechanism boundary

The kernel documents Thunderbolt deauthorization as PCIe-tunnel teardown, equivalent to PCIe hot removal. It is a candidate final operation after driver/resource release, not a storage eject and not proof that all USB/DisplayPort paths vanish. USB4 port offline is documented for retimer maintenance, so it is not adopted as a generic eject command.

UDisks drive power-off deconfigures a USB storage device and disables its upstream hub port. Its drive-oriented API is not a verified eject contract for an entire USB4 eGPU dock.

Sources: https://www.kernel.org/doc/html/latest/admin-guide/thunderbolt.html and https://storaged.org/udisks/docs/gdbus-org.freedesktop.UDisks2.Drive.html . Existing repository research: PREPARED_EGPU_REMOVAL_RESEARCH.md.

## Next implementation boundary

1. Bind GPU, audio, sibling USB controller and router using actual topology; never device-name matching alone. Review the existing tunnel observer's domain selection before mutation use.
2. Preflight the final operation before releasing anything: capability, exact target, privileged access, complete storage and topology evidence.
3. Extend the existing serialized removal transaction with remaining-USB and tunnel steps; inhibit automatic recovery/docking for the transaction and preserve that inhibition after partial failure. The new 0.3.82 attachment-recovery policy must not mistake intentional teardown for a new recoverable attachment.
4. Revalidate after each step and record durable progress. A timed-out kernel write is unresolved, not cancelled; never issue competing retries.
5. First verify software teardown with the cable connected, then separately validate physical unplug/reconnect on the supported profile. Unknown, partial, or unverified branches never grant clearance.

No supported universal whole-USB-C eject operation has been established. The current concrete candidate is ordered release followed by exact supported PCIe-tunnel teardown, with explicit verification of any remaining dock functions. Next work belongs to the canonical executor task after topology and current ownership review.

## Initial implementation

`application/whole_dock_teardown.py` now executes the post-GPU sequence through an explicit port: preflight, exclusive durable claim, fresh recheck, USB removal intent/action/readback, fresh tunnel recheck, deauthorization, final readback. It reuses the existing domain decision. Exceptions and partial results retain ownership; no automatic retry or restore is issued. Its result always leaves physical unplug clearance false.

Eight targeted regression tests cover ordering, storage/GPU/idle refusal, attachment changes, late GPU return, unreadable final state, write timeout, journal failure and concurrent/reentrant calls. Architecture and diff checks pass.

This is an executor core with a test port, not a production Linux writer or installed feature. A real port must implement atomic persistent claim/inhibition, full fresh topology and privileged storage observation, immediately revalidated exact sysfs operations and interrupted-operation recovery. Those requirements cannot be replaced by the in-memory test port. Production wiring and supervised hardware validation remain open under the existing whole-dock executor workstream.

## Parallel implementation follow-up

The post-intent USB preflight now repeats after durable I/O. Consent includes attachment binding and generation so a replacement at reused addresses cannot inherit the old approval. Ten transaction tests pass locally.

The Linux writer is confined to fixed controller `remove=1` and router `authorized=0` operations, using pinned directory identities and no-follow descriptor traversal. It is a primitive; the caller must still establish truthful topology and exclusive admission. The durable claim store uses exclusive creation, private root-owned descriptor traversal and fsync, retains claims on failure, and exposes no automatic clearing operation.

A fresh read-only topology inventory shows the PCI dock branch and Thunderbolt router beneath different host PCI paths on the Ally. A common-path guess cannot bind them. The current product-name tunnel lookup must remain diagnostic-only until a verified association is supplied. Existing storage observations do not include all raw block-device users; initial activation must either reject all attached storage or add complete raw-use checks.

Production runtime admission must be shared with automatic docking, recovery and presentation. A separate claim file alone does not stop those existing paths. These integration gates remain unresolved; no new installable version or physical disconnect claim is made.

### Kernel association found

Read-only inspection found a supplier/consumer device link connecting the dock's upstream PCI root port to the USB4 NHI. Linux v6.16 `drivers/thunderbolt/acpi.c`, `tb_acpi_add_links`, creates such links from the firmware `usb4-host-interface` reference. This provides a host association to investigate in the resolver, rather than treating unrelated sysfs path trees as an obstacle or guessing by product name. It still requires unambiguous external-router/branch association and stable attachment evidence before any write.

Source inspection only, no copied kernel code: https://github.com/torvalds/linux/blob/v6.16/drivers/thunderbolt/acpi.c . This source is a mechanism reference; the exact Valve kernel implementation remains a separate verification item.

### Live resolver verification and transaction integration

The new read-only resolver successfully bound the attached Ally/G1 topology and
revalidated its retained anchors on September 11. An initial failure came from
enumerating unrelated global device links; scoping observation to the NHI's
consumer links fixed it. Relevant missing endpoints and ambiguous consumers
still refuse binding. No device write was performed.

The production post-GPU port now joins fresh topology, storage observations,
durable ownership and guarded writes. Initial trials require an empty USB
peripheral branch. Local transaction/runtime tests pass; Linux-only filesystem
and topology fixtures still require verification for this combined revision.

Resource release must acquire the durable claim before starting and retain one
mutation admission scope through final verification. A transaction-local,
single-use continuation will join that release to the post-GPU executor.
Software reconnect remains unfinished; it must verify the same retained router
and freshly enumerated devices before releasing inhibition. There is no new
installable candidate or completed disconnect trial yet.

## 0.3.83 cable-connected trial controls

This candidate adds an explicitly confirmed operator path to the existing
`execute_egpu_disconnect` RPC. Ordinary UI calls retain their existing behavior.
Use `trial_action="whole_dock_disconnect"`, `trial_confirmed=true`, and
`release_display=true` with no relaunch app. Keep the physical cable connected.
Poll `get_egpu_disconnect_status` with `_request="whole_dock_trial"` across the
Steam session restart. Only a verified `software_down` permits the separate
`trial_action="whole_dock_reconnect"` call with the same confirmation flags.

The original plugin process retains the attachment binding; a plugin restart
refuses continuation. Both actions are tracked workers, so losing a browser/RPC
observer does not cancel a kernel operation. A dedicated sleep inhibitor covers
the transaction. Automatic presentation, recovery and native audio recovery
share mutation admission.

Reconnect performs one authorization write and bounded read-only enumeration.
It verifies retained host/router identity, hardware IDs and driver bindings,
then archives the completed claim after a further fresh verification. Only then
are ordinary gated actions available again. This does not verify picture/audio/
controls or authorize physical unplug. Partial outcomes retain the claim and
sleep inhibitor; do not retry writes or reinstall to bypass that state. Capture
the result and use supervised recovery. The preserved0.3.82 remains the rollback.

Current live evidence is read-only topology and driver binding validation on the
Ally/G1. New disconnect/reconnect hardware behavior remains untested.

### Quick Access control follow-up

An isolated whole-dock control component adds an idle-only Disconnect button,
centered native confirmation and verified-down Reconnect action. It polls the
existing trial status and never mutates on mount. Confirmation carries the
opaque attachment token from preview; the backend rejects a changed binding.
A persisted request ID keeps interrupted replies from enabling repeat actions
on a component remount. No physical unplug clearance is displayed.

The expanded shell accepts a native-only disconnectControl slot, mounted by
the native adapter. Its snapshot reader reuses the existing plugin-lifetime
connection monitor and introduces no extra snapshot polling. Missing, future
or older-than-ten-second readings disable actions. Trial-status polling is
read-only; only confirmed clicks dispatch an operation.

In0.3.84, open Command Center > Quick Access > Safe Disconnect > Safely disconnect.
Read the centered confirmation and keep the physical cable attached. After a
verified software-down result, the same detail offers Reconnect eGPU.
The0.3.83 archive is unchanged and does not contain this button.

Browser comparison at828x466 and1280x720 used actual component source with
mocked Decky/RPC. Confirmation centered in both viewports; the shell geometry
and unrelated controls are unchanged. Behavioral fixtures cover cancel,
duplicate confirmation, attachment changes, interrupted replies/remount,
storage failure, unmount and stale response ordering. Native controller and
disconnect/reconnect hardware validation remain pending.

Integration note: this candidate's createExpandedMenu fourth argument is a
readCurrentSnapshot callback from the existing connection monitor. Claude's
unmerged PR276 uses a TileSource fourth argument. Those contracts require
explicit reconciliation before combining branches; do not silently substitute
one for the other. The button change does not integrate the broader PR276 menu.

## 0.3.85 hub-only readiness correction

The installed0.3.84 native attempt returned trial_unresolved. Subsequent read-only
inspection found two pure USB hubs on the G1 branch. The prior empty-device rule
rejects that topology; the generic error does not establish whether this was the
first exception in the recorded attempt. No successful disconnect was observed.

The new classifier accepts only complete, stable hub-only inventories, using
device class, configured interface count, interface classes and hub driver
bindings. It traverses descendants and repeats the observation; peripherals,
composites and missing evidence refuse. Product names do not grant acceptance,
and this does not distinguish internal hubs from external empty hubs. Existing
storage, game, retained topology and mutation guards remain required.

A read-only run of the new classifier on the connected Ally/G1 returned true
with two devices and a complete inventory. This is readiness evidence only.
Selected fixed failure categories now show a specific explanation in Quick
Access. Unknown errors remain unresolved; no retry or cable clearance is added.

## 0.3.86 trial diagnostics

The installed0.3.85 trial again returned generic trial_unresolved. A separate
read-only legacy readiness check found active/protected clients, including
system services. That is not proof of the trial's earliest failure.

This revision preserves the execution guards and records the fixed trial phase
and GPU-release stage, exposing mutation inhibition and unverified release as
specific categories. The read-only whole_dock_record status request returns
only a validated durable stage, none, or unknown; never attachment identifiers.
After install, inspect this record before any repeat operation. A retained
claim must not be deleted to enable a retry. No successful disconnect or
physical unplug clearance is established by this diagnostic change.

## September 11 release integration audit after0.3.86

Two independent read-only reviews confirm that the whole-dock button composes
Claude's existing user-manager filter, SessionUnitRestart, explicit audio
restarts, held-filter removal window, and ownership journal. No missing core
release integration was found.

Root-backed get_snapshot.disconnect_readiness currently reports systemd and
systemd-logind as system clients holding drm_card, alongside expected session
and audio clients. SSH systemctl reports15 logind stored descriptors; this count
alone does not identify which is the eGPU. The durable whole-dock stage remains
release_intent, and no repeat hardware operation was performed.

The modern complete holder scanner includes scope/system holders omitted by the
older September8 engineering account. FilterArmCoordinator rejects unapproved
holders before unit restarts. That is a source-backed candidate explanation for
the intact session, not recovered proof of the earlier exception. The inner
LiveDisconnectService._refused also drops the arm stage/code, so current outer
status cannot reconstruct whether the original refusal was plan, authorization,
enforcement or restart related.

Next: preserve inner arm diagnostics and investigate release of session-broker
DRM descriptors through their owning session/controller. Do not add systemd or
logind to the user-service restart allowlist, ignore their handles, clear the
whole-dock claim, or repeat removal based on the old clients_clear account.

Mechanism research (reference only; no adapted code): systemd v257
src/login/logind-session-device.c shows that pausing a DRM session drops master
but retains the descriptor. A Desktop switch alone is therefore not proof that
all descriptors were closed. Installed-version behavior still needs validation.
https://github.com/systemd/systemd/blob/v257/src/login/logind-session-device.c

## 0.3.87 controller-release capture trial

The actual login1 controller resolves to gamescope-wl in gamescope-session.service.
The target propagates stop to graphical-session.target, which owns that service.
User Linger=no means a user-manager timer is not an adequate independent recovery
if the session and SSH disappear. BrokerCaptureRestoreTimer therefore schedules a
fixed system-level25-second timer that first starts the observed user manager,
then attempts to start that user's Gaming target. Timer activation is not proof
that later presentation restoration succeeds; run the first trial supervised
with the operator available for recovery.
No arbitrary command, unit, or shell is accepted. Timer activation is verified
before timed observation is made available.

The existing execute_egpu_disconnect RPC with trial_action=whole_dock_capture,
trial_confirmed=true and release_display=true holds the dock
mutation lock, requires the retained release_intent claim to match a fresh
attached topology, requires initial idle and complete holder evidence, arms the
restoration timer, and samples holders for35 seconds. It does not stop services,
remove hardware, or alter the retained claim. Poll existing disconnect status
with request release_capture. The returned restore_timer is an ephemeral unit
name for verification, not an attachment identifier.

Trial driver sequence, after installation and explicit operator readiness:
1. Recheck game idle, controller identity and current claim. Start capture.
2. Require a NEW observing result, complete first sample, and no more than5 seconds
   since starting capture. Verify its exact root restore timer is still active.
   If delayed or ambiguous, do not stop anything; let capture finish.
3. Stop only gamescope-session.target through the observed user's systemd manager.
   Keep an independent finally start path as well as the already-active timer.
4. Observe controller disappearance and system broker holders during the stopped
   interval. No PCI/USB/tunnel write and no filter arm are part of this test.
5. Restore/start target; verify session, GPU, picture/audio/controls and capture.
   Preserve claim unchanged. Audio holders may remain because audio is not stopped.

A stop attempted after the timer fires has no watchdog and is forbidden. This is
an operator-captured mechanism trial, not a new Safe Disconnect button action.
It can establish whether controller exit releases broker handles, not clearance
to unplug or approval to ignore those handles. Inner arm refusal stage/code are
also preserved for future release attempts without changing removal decisions.

## 0.3.87 installed trial result — September 11, 2026

Installed version0.3.87 was read back. A35-second capture-only smoke completed,
and its root restoration service journal reported Deactivated successfully.
No session stop was issued during that smoke.

A second capture was started and verified observing inside the fresh5-second
window; its exact restoration timer was active before the approved user target
stop. The stop completed successfully.34 complete holder samples were captured:

| Elapsed seconds | Observed holders |
| --- | --- |
|0.1| Gamescope/mangoapp, Steam, init.scope, systemd-logind, WirePlumber |
|3.3| Gamescope, Steam, init.scope, systemd-logind, WirePlumber |
|4.3| WirePlumber only |
|5.3| Gamescope/mangoapp, init.scope, systemd-logind, WirePlumber |
|6.4| Steam also present again |

This establishes an observed interval where the session and both system broker
holders released the eGPU; it does not establish that every holder cleared.
WirePlumber remained. The session returned before the25-second restoration timer
fired. The source of that automatic return is not yet attributed. Do not claim
the watchdog caused the early return or that the existing filter prevented it:
no filter was armed in this experiment.

The independent restoration service later completed successfully. An explicit
idempotent target start was also issued after capture. The retained claim is
still release_intent; no claim deletion or PCI/USB/tunnel write was performed.
Post-trial backend checks were ready_idle with GPU/link/HDMI/audio/session/idle
all true. Ronnie confirmed TV picture, audio and controls all working.

Local captured evidence: out/0387-stop-trial.json, SHA256
966020525a1b5972be8640a7f906a85d8d979ef74fc2e6ca998aff6b489409e8.
Related evidence: out/0387-timer-smoke.json and out/0387-trial-prestop.json.
Next implementation/test question: keep the controller stopped long enough to
release audio and re-observe, while preventing automatic session reacquisition
and preserving independently verified restoration. No physical unplug clearance.

## Offline held-stop implementation — September 11, 2026

The Ally was turned off by the operator; this work performs no device operations.
The new internal HeldSessionRelease coordinator records intent, requires an
independent restoration mechanism before masks, verifies masks before stopping
approved session/audio units and the audio activation socket, and bounds complete
holder observations. It rechecks ownership and stopped state after a clear scan.
Every attempted intent triggers restoration, including partial failures; uncertain
operations retain their journal. A clear scan never authorizes physical unplug.

RuntimeMaskLease is an internal user-owned directory-descriptor primitive. It
records an exact mask inode before publishing without replacement, preserves
pre-existing entries, and reconciles interrupted quarantine before claiming a
mask absent. The caller must serialize normal/watchdog cleanup and provide the
private directory, durable journal, and exact prior-state restoration.

These components are not connected to the RPC or Safe Disconnect button. The
existing 0.3.87 start-only timer cannot recover a masked session. Remaining work:
implement and test independent owned-unmask recovery and its durable journal,
verify effective unit configuration/activation sources for the detected profile,
then integrate the held-stop capture. Unknown profiles must refuse. The first
hardware trial remains release/observe/restore only, without PCI or USB removal.
No new install package or version is published from these offline components.
Documentation impact: Wiki (after runtime integration and verified trial).

### Recovery executor checkpoint

Added the user-only recovery executor, immutable intent/mask journal, permanent
recovery revocation and separate recovery-worker lock. Recovery removes recorded
mask inodes before daemon reload and restarts only the recorded prior-active
units. It verifies all approved unit states again before recording completion.
A completed operation is checked without replaying reload/start commands. Unknown
state, foreign entries and corrupt evidence remain unresolved. All commands are
fixed, bounded and execute as the observed user, never as root.

The journal lock covers mask publication and producer dispatch against revocation;
the independent recovery lock serializes recovery workers without depending on the
original dock mutation lock. The launcher still needs to bind the current boot,
unit directory and private journal directory identities. Installing/scheduling
that independent launcher and integrating the held-stop producer are NOT done.
The existing 0.3.87 timer remains unchanged; these components are not enabled in
the player button and no new installable version is claimed.

Local full suite during implementation: 3171 tests, 200 expected platform skips.
Additional final focused fixtures cover repeat recovery, concurrent recovery,
corrupt journals and state changes at completion; Linux CI supplies filesystem
execution evidence. Architecture and Python compilation pass locally.
Documentation impact: Wiki after runtime integration and supervised validation.

## 0.3.88 held-stop operator candidate

The operator-only `whole_dock_held_capture` action is now connected through the
existing `execute_egpu_disconnect` RPC. It requires trial_confirmed=true,
release_display=true, initial complete holder evidence, one matching attachment,
a retained release_intent claim and idle game evidence. The existing player Safe
Disconnect action and automatic TV-switching behavior are unchanged.

The helper prepares boot and directory-inode pins plus an exclusive journal under
/run/user/UID/regear-held/TOKEN. It snapshots the Python recovery package there
before arming a system timer. The timer runs the frozen helper as the observed
user, never a root Python interpreter. Timer/service dependencies keep the user
manager required; first restoration is scheduled after90 seconds, with bounded
120-second execution and up to3 attempts separated by30 seconds. An explicit
user-manager stop or reboot is outside this watchdog's survival guarantee.

Only after verifying timer activation and fresh idle evidence does the producer
mask the fixed session/audio units, verify effective masks and stop them. Every
stop checks the durable ownership phase and exact published mask inodes. The
root capture retains dock mutation admission and samples holders for up to10
seconds while the held state remains verified. Its finally path restores using
the same frozen helper; the independent timer remains available after plugin or
SSH exit. Restoration never grants physical unplug clearance and never modifies
the retained whole-dock claim or PCI/USB/tunnel controls.

Trial: keep the cable connected and have the operator available; invoke existing
RPC with trial_action=whole_dock_held_capture, trial_confirmed=true and
release_display=true. Poll get_egpu_disconnect_status with release_capture. Record
clear_observed, session_restored, samples and the exact restore_timer. The expected
success code is release_capture.held_clear_restored; holders remaining with
successful restoration yields release_capture.held_unverified_restored. Confirm
picture, audio and controls afterward. Do not run another install during a trial.
A new candidate is prepared offline; installation and hardware results are separate.
Documentation impact: Wiki after supervised validation.

Packaging correction: local0.3.88 was built concurrently with the final test
suite and its build metadata reported uncommitted. It is retained but must not
be installed/published. Its reservation remains consumed. Use0.3.89 for the
candidate, with tests complete before clean-source packaging. Linux CI for
98bbcaf passed; this is a provenance correction, not a runtime behavior change.

Final candidate is0.3.90. The unpublished0.3.89 package is superseded because the
root watchdog service now also sets RuntimeMaxSec=120s, bounding an already
running helper as well as startup. systemd-run v257 leaves the service type
unspecified by default; TimeoutStartSec alone does not bound the full helper
runtime. Reference: https://github.com/systemd/systemd/blob/v257/src/run/run.c
All older local archives remain unchanged; only0.3.90 is offered for this trial.

0.3.90 publication verified: https://github.com/ronnierosal/Re-Gear/releases/tag/v0.3.90
Source cf60d79e5510a3f226033b699123974894819148. SHA-256
fd8f88078ac2eff0fff131cfd8b092f197b0676b028ff9d8a629fa405ad74fb2
matches the uploaded GitHub asset digest. Final-source Linux CI runs34663328047
and34663328049 both passed. Published as a prerelease, not the latest stable
release. The Ally remained off: no staging, installation or hardware validation.
PR304 remains open for the larger disconnect work; this candidate tests only
held release, complete-holder observation and restoration with the cable attached.

## 0.3.91 abandoned-trial reconciliation

Live0.3.90 readback showed ready_idle with every hardware check true, but an
old release_intent record remained and automatic transition logged an exception.
DockMutationGate intentionally inhibits all presentation writes while this record
exists. The green readiness checks described hardware, not mutation admission.

New explicitly confirmed whole_dock_reconcile operator action archives only
claimed/release_intent records. It holds dock mutation admission, checks the exact
old claim, requires the same dock binding and freshly approved current generation,
reobserves complete topology/drivers, session identity, idle state and a complete
holder scan. Normal session holders are allowed. It refuses ANY inner removal or
filter ownership record and requires all held-session journals settled with no
owned live masks or unresolved quarantine. Missing, unreadable or corrupt evidence
never authorizes archival. Early stage alone is not proof no write occurred.

Archival uses an exclusive aborted-whole-dock audit filename and directory fsync;
failure restores inhibition. No record is silently deleted and no hardware removal
or disconnect completion is claimed. After success the ordinary automatic dock
coordinator is rearmed, retaining its opt-in and readiness rules. The operator
supplies the current attachment_token from whole_dock_trial status and calls the
existing execute_egpu_disconnect RPC with release_display=true,
trial_action=whole_dock_reconcile and trial_confirmed=true.

Hardware guard execution and the resulting TV switch still require live validation.
Documentation impact: Wiki after the reconciliation trial.

Cross-generation handling is deliberate: reboot/replug can change generation.
Reconciliation requires the exact old claim and same dock binding, but the
operator approves the fresh current generation and it is rechecked before
archival. It does not pretend the old generation is still live or reconstruct
missing historical removal evidence. Outstanding inner records still refuse.

## Automatic connection regression and protection

The 0.3.82 automatic recovery scheduler and session restart service survived
unchanged. The regression was introduced at their integration boundary:
DockMutationGate rejected a persistent early disconnect claim before the
automatic scheduler could begin. Reboot preserved that record. The 0.3.91
explicit reconciliation required the GPU to return first, so it could not
resolve the case where session recovery was needed for PCI enumeration.

The correction keeps ordinary admission first. Only an inhibited automatic
session restart can enter the separate connection recovery path. It requires
claimed/release_intent, the exact authorized transport with zero endpoint
functions and two matching observations, no inner removal/filter records,
settled held-session work, fresh idle/internal-only supported host evidence,
unchanged session user, consent and an unowned durable transition journal.
It retains the claim. Partial enumeration, later removal stages, unfinished
held work, changed identity and incomplete observations all refuse.

When the complete dock returns, automatic TV switching may archive the early
claim through the existing fully observed reconciliation. The ordinary mutation
gate is then acquired again, so a new intervening claim still inhibits switching.
The existing display transition checks its expected generation and consent.
Archival does not reset either recovery budget. No automatic path removes PCI,
USB or tunnel devices, and no automatic recovery grants unplug clearance.

Release acceptance must cover interaction with retained state, not only each
feature separately. Required fixture cases live in
tests/test_main_dock_mutation_gate.py and tests/test_whole_dock_topology.py:
normal unclaimed recovery; matching early claim; failed or pending inner work;
changed transport/user/claim; partial enumeration; failed archival; and exactly
one dispatch after admission. Existing automatic recovery tests retain absence
arming, ten-second settling/cooldown, two attempts, consent, idle guards and
no new attempt from a plugin reload while attached.

Preserve checkpoint/0.3.82-auto-tv and its immutable archive. New features ship
as separate candidates and must pass the connection matrix before promotion:
cold boot without dock then attach with TV on; attach with TV off then turn it
on; and the same connection after an aborted disconnect and reboot. Record
picture, audio, controls, source and package hash for each. Safe live disconnect
remains experimental until release, software removal, restoration, subsequent
auto connection and physical unplug have their own verified results.

The new connection exception is implemented and fixture-tested; hardware
recovery from the retained record remains a candidate validation gate.
Documentation impact: Wiki.

## Portable-first disconnect trial on 0.3.92

The owner confirmed automatic TV connection on 0.3.92. Its artifact and source
6c638a81607bd2b16f9976cc3d6723b00dfe34c7 remain the auto-connect rollback point.

The first Command Center disconnect refused before GPU release with
arm_sequence.unapproved_holder. A complete scan included init.scope and
systemd-logind.service alongside approved session/audio services. A separately
authorized held-session capture observed a complete empty holder set. Its
restoration report was false even though the services had returned: this host
sets RefuseManualStart on gamescope-session.service. Direct start returned exit
4; starting gamescope-session.target succeeded. Recovery must start the target
and verify its service dependency, not manually start that service. The active
session was verified and its exact held-recovery journal settled through the
existing descriptor-bound recovery, without deleting records or removing hardware.

The owner then requested Portable first, release, USB4 deauthorization. After
the normal supervised Portable transition, fresh observation verified internal
rendering and internal output. Protected broker holders disappeared. The normal
whole-dock path then reported GPU/audio removed and reached tunnel_remove_intent.
Linux reported the retained router authorized=0; a later read-only observation
matched the original binding and generation, verified host/router relationships,
and found zero downstream PCI functions. The owner reported the TV had no signal.
The owner then confirmed Gaming Mode picture, handheld audio and controls all
worked on the Ally after the software disconnect.
The app's terminal result remained unresolved, so neither physical unplug
clearance nor verified software reconnect is claimed.

The candidate correction performs the verified Portable transition under the
existing dock admission and sleep inhibitor before creating teardown intent.
It rechecks user and full attachment identity, rebuilds the release runtime,
and preserves all holder, display, filter and removal checks. Explicit Portable
return suppresses automatic TV switching for that attachment; only verified
reconnect rearms it. Final tunnel settling retries only the exact observed
PCI-branch-remains condition for up to ten seconds, with no repeated writes.
This addresses a plausible asynchronous final-observation race; the old trial
did not retain the precise exception, so the cause still needs candidate proof.

Tests cover dependency-only session startup, Portable-before-claim ordering,
changed identity and failed transition refusal, and bounded settling without
write replay. The current 0.3.92 trial remains inhibited at tunnel_remove_intent;
its installed reconnect requires software_down and the original runtime. Do not
install over this trial or silently promote its record. Plan explicit recovery
before another install, and retain the successful-removal evidence separately
from the remaining completion/reconnect gap.

## Thermal incident: software reconnect trials paused

During the 2026-09-11 local evening trial (2026-09-12 UTC), the owner reported
that the GPD G1 became "really hot" and physically disconnected it. Treat this
as a potential hardware-safety issue, including possible hardware damage risk,
and a blocker for further software reconnect trials. Damage has not been
reported or established; neither a measured temperature nor fan telemetry was
captured, and causation by the software sequence is not established.

The installed plugin was 0.3.92, source
6c638a81607bd2b16f9976cc3d6723b00dfe34c7. After verified software removal and
user-confirmed usable handheld display/audio/controls, the owner locally ran
the completion helper from fce439af442871b1871557494d5f45803b433180. It returned
record_completed with hardware_write=false; plugin readback was software_down.
One existing-runtime software reconnect request
724ba159bd3d4fea90f267b1ad88ee06 then timed out after 30 seconds. Fresh kernel
readback showed router authorized=1 but no external GPU/audio/USB PCI functions.
The retained claim was reauthorize_intent. No reconnect replay was issued.
The overheating report followed this unresolved, still-powered state.

Software removal/deauthorization does not power off the dock. A reconnect
timeout must not be treated as a benign idle state or evidence of thermal
safety. Preserve this incident alongside functional results; do not describe
the overall trial as successful. The owner was advised to disconnect dock power
and allow cooling. The location of the heat, fan behavior, and any physical
damage remain unknown. Physical cable removal means the previous live attachment
assumptions must no longer be used.

Next: investigate failure-state behavior and available thermal/fan evidence
without another powered reconnect trial; define and review thermal stop and
recovery criteria before proposing resumed supervised hardware testing. This
incident supersedes instructions below to keep the cable connected or preserve
a live runtime when doing so conflicts with stopping an overheating device.

Documentation impact: Wiki. Publication and hardware validation remain separate.

## Operator completion-record recovery (historical trial procedure; paused)

For the still-running 0.3.92 trial, a source-pinned operator zipapp can complete
the retained tunnel_remove_intent record without replacing the plugin. This is
not another disconnect, a software reconnect, a generic claim-clear command or
permission to unplug. The original plugin runtime must remain alive for the
subsequent normal reconnect and original function-identity verification.

The helper requires the exact binding AND generation embedded at build time,
the single retained deauthorized router, supported user-security domain, zero
downstream PCI devices including bridges, a verified idle Portable session,
unchanged session user and settled held-session journals. Under dock admission,
the claim store locks and rechecks the exact record and fresh proof before
atomically advancing only tunnel_remove_intent to software_down. It retains
inhibition and the original operation. Other stages, changed generation,
partial observations and uncertain users refuse. No kernel attribute is written.

Build scripts/build_dock_completion_helper.py from clean committed source with
the observed binding/generation. Its immutable filename includes the source
revision and its SHA-256 is recorded. Run --observe without privilege first.
After Linux fixture validation and matching live observation, the operator runs
the same archive with local sudo authentication and --confirm. A successful
record_completed result must be read back through the running plugin before
requesting its normal whole_dock_reconnect operation. Do not reinstall, reboot,
physically cycle the cable or adopt another trial during this sequence.

## Auto-connect and disconnect isolation requirements

Updated September 11, 2026 local time (September 12 UTC). These are acceptance
requirements for ongoing work, not a claim that the fixes are implemented.

- Preserve the hardware-verified auto-TV checkpoint and its recovery behavior.
  Disconnect changes must pass auto-connect regression coverage before release.
- Serialize connection and disconnect operations through shared admission checks,
  while keeping their operation state separate. Intentional teardown suppresses
  automatic connection so the two operations cannot fight each other.
- After physical reconnection, verify a fresh attachment and reconcile the old
  operation with evidence before restoring automatic connection. Never silently
  delete a failure record or bypass unknown-state guards; an old failure must
  not silently block a valid new connection indefinitely.
- Keep powered software reconnect trials paused following the thermal concern.
  This is a testing hold, not a claim that every installed build disables the action.

Required regression scenario: intentional disconnect, failed software reconnect,
physical reconnection, then guarded automatic TV restoration. Include changed
attachment identity, unresolved teardown, running/unknown game state, and duplicate
request refusal. Passing these code checks does not establish thermal safety.

The preserved 0.3.82 recovery used a Gaming-session restart, not an implemented
Desktop-to-Gaming round trip. Manual Desktop switching producing a TV picture is
separate evidence and must not be described as that automatic code path.

In the supervised trial, the owner confirmed a usable handheld screen, audio and
controls after software teardown. Subsequent software reconnect timed out. The
owner then reported unusual dock heat and disconnected it. Temperature and fan
telemetry were not captured; software causation and hardware damage are unknown.
Potential hardware damage risk blocks further powered software reconnect trials
pending investigation and reviewed stop/recovery criteria. Software removal does
not power off a dock, and these observations do not validate live physical unplug.
