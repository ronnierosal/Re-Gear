# Supervised one-shot Portable Vulkan launch

Status: installed in Re-Gear 0.3.53; supervised trial returned to Portable,
but external GPU clients remain. Resource release failed its evidence gate.
This is a session launch-policy trial, not eGPU removal or safe unplug support.

Local verification: 1023 backend tests completed (eight platform skips), 181
frontend tests, typecheck, architecture, compilation, build and package contract
checks passed. All 11 store fixture tests also passed on Linux, including the
permission and symlink cases skipped on Windows. Independent bounded review and
real-file journal tests caught and resolved recovery-cancellation and metadata
ordering defects. These local checks preceded the hardware trial below.

## Supervised result - 2026-09-05

Installed source revision: `8d7997fabd3286c4699404b42357a56b1b2edb8d`.
After supervised idle TV docking, the one-shot trial was submitted through the
existing native Decky frontend at approximately 22:26 Pacific. The player
confirmed Steam visible on the Ally with normal built-in controls and audio.
The G1 cable stayed attached throughout.

The privileged installed scanner reported complete observations: ten external
device clients before the restart, three afterward. Gamescope and Steam still
held the external DRM render node; WirePlumber held its audio control device.
Storage count was zero. This does not clear software removal or physical unplug.
The trial record and consumed marker remain retained; do not rearm or replay.
Status remains `portable_trial.application_unverified` with explicit result
acknowledgement required. Player-visible success does not override this gate.

Read-only process inspection found the new Gamescope command line selecting
the observed internal GPU and panel. Its environment was inaccessible to the
unprivileged SSH reader, so complete trial environment application is unproven.
Steam's readable environment contained neither trial Mesa selector variable.

The installed OS launches Steam in `steam-launcher.service`, separately from
`gamescope-session.service`. Steam's unit reads `%t/gamescope-environment`.
The OS `gamescope-session` script forks `read_gamescope_env` before executing
the wrapped Gamescope binary; that helper writes its inherited environment to
the file and signals readiness. Environment changes made later inside the
wrapper cannot propagate back into that helper or into Steam's separate unit.
This establishes a launch-policy coverage gap, not the cause of all retained
GPU references. Gamescope itself still retains an external render reference.

Next engineering work must cover the actual separate Steam launch boundary
with bounded authority, durable recovery and stale/replay tests, then separately
verify remaining Gamescope and audio ownership. Do not modify live service
environment or widen device-removal authority based on this trial.

Local evidence: `out/trial-053-native-before.json`,
`out/trial-053-native-after.json`, `out/trial-053-submission.json`, and
`out/trial-053-return-live.txt` (ignored diagnostic artifacts). The earlier
attachment also logged a correctable PCIe BadTLP event; it was not an error-free
kernel trace. The separately reported Sleep issue remains deferred in
`DEFERRED_SLEEP_BUG.md`; no causal link has been established.

## Bounded milestone

Continue the prepared-disconnect work using the existing presentation owner and
normal Gamescope session restart. No new process signal, driver, PCI, USB4, sleep
or device-removal operation is introduced. Ordinary Portable requests and
automatic transitions do not opt in. A separate developer-supervised approval
RPC issues a short-lived, single-use permit with trial mode bound to that exact
plan and observation generation; the existing Portable execute RPC consumes it.
The trial requires an exact idle TV-Docked source, current original launch
policy and existing verified profile/binding/integration gates.

## Launch and recovery

The mechanism persists the original launch config, expected normal Portable
config, operation, boot/attachment binding, internal identity and a bounded
deadline before changing config or requesting the existing session restart.
The wrapper durably consumes the one-shot record before validation or exec.
It rechecks boot, attachment, config, internal DRM card/connector ownership,
idle game scopes, Mesa layer availability and conflicting routing environment.
It changes only the new child arguments/environment; parent/session-manager
environment is never changed. A rejected or repeated launch uses ordinary
policy. A crash after consumption cannot replay the trial.

Recovery participation is bound to the exact trial-owned transition journal.
Recovery first cancels remaining trial authority, even when observation is
unknown. Restoring the original config and restarting retain existing identity,
idle and integration gates. A conflicting later config is not overwritten.
Records remain retained and block another trial; there is no automatic cleanup
or retrial. A future explicitly reviewed reconciliation step is required.

The only new RPC is `approve_supervised_portable_vulkan_trial`. It accepts no
device paths, commands, PIDs, environment or caller-selected GPU. Execute its
returned token through `execute_supervised_portable_switch`. Do not expose this
experimental approval in normal UI or automatic preferences.

## Evidence boundaries and hardware gate

`portable_trial.application_unverified` deliberately reports that a successful
Portable transition does not prove the trial applied. The consumed marker is
not an exec-success receipt. Explicit acknowledgement remains required and
automatic completion retains the Portable hold. Inspect new-session argv and
environment plus the player-visible Ally display/audio/controller result.
Then capture complete privileged G1 descriptors, mappings, client allocations,
storage and sibling-device evidence. Vulkan restriction is not a DRM sandbox.
No result from this trial can say safe to unplug.

## Follow-on Steam handoff candidate (0.3.54, not activated)

The follow-on candidate uses a separate fixed Steam launcher, leaving the OS
session environment file untouched. Read-only inspection found seven OS units
using that shared file, so moving trial settings into it would broaden scope.
After validation, the Gamescope shim writes an exclusive durable receipt bound
to the exact operation and its systemd invocation. The Steam shim burns a second
exclusive claim before checking that receipt, the currently active Gamescope
invocation, and fresh boot/config/attachment/game/layer evidence. It rechecks
the invocation after collection and scopes selectors to its own exec child.
Failure, early startup, missing receipt, cancellation or replay falls back to
ordinary Steam with both stale trial selectors cleared. The normal Gamescope
fallback now clears both selectors too.

Cancellation burns the Steam claim first, then Gamescope authority. Cancellation
cannot retract a Steam launch that already won the exclusive claim. A receipt
records a validated launch attempt, not successful exec or resource release.
The native Mesa library check does not prove Steam's mixed-bitness components
use the layer. Application remains unverified until process/runtime evidence.

The integration admits only the observed OS unit and launcher
hashes, the exact no-argument command, no competing drop-ins/environment
overrides, and verified detached idle Portable preparation. Its exact
compare-before-restore rollback refuses later modifications. Preparation uses
the existing single-use approval owner and atomic integration store, followed
by daemon reload and exact effective-unit readback. It does not restart Steam.
Two developer-only RPCs approve and prepare this integration. Normal UI and
automatic paths cannot opt into the trial. Trial approval and execution require
verified prepared Steam integration. No live integration has been changed.

After durable engine success, a handoff window waits at most ten seconds or
the existing monotonic expiry for Steam's claim. Failure/recovery cancels
immediately. The finally block always burns remaining authority. An empty
marker during an in-progress exclusive write stays pending within the bound;
it is not treated as a completed claim or an identity failure.

The new executable is packaged with LF line endings and executable permission.
The fixed launch command preserves the verified ordinary search directories
and appends the OS launcher directory. If an older package removes the shim,
the command finds the native launcher. The shim also falls back to the fixed
native launcher if its backend cannot import. A present but otherwise broken
runtime still requires normal recovery; no release-success claim follows.

Local review found and resolved a clock-domain mismatch, marker-write race,
and older-package fallback gap. All 52 Linux fixture tests passed in temporary
files on the Ally, including real executable-search fallback. No live service
was mutated by these tests. The installed build remains 0.3.53 until separately
verified native installation.

### Retained-record reconciliation before another trial

This is a supervised operator gate, not an automatic cleanup API. Keep the
current record and hold while attached. After confirmed shutdown, detach while
off, boot detached and verify idle Portable health. Verify the retained record
belongs to the prior boot and its primary consumed marker matches its operation.
Resolve the prior explicit-result hold through the existing acknowledgement
flow only after confirming no active transition. Preserve the root journal.

Archive only that exact operation's known trial files into a newly created,
exclusive history directory under the same state root. Move markers/receipt
first and the original record last; preserve their contents and sync the
directory. On interruption, stop and inspect: the retained original record
continues to block rearm. Never overwrite an archive, delete a foreign record,
or infer approval to rearm from the archive. A later fresh attached trial still
requires its own one-shot approval. Installation alone does not reconcile,
prepare the Steam integration, restart a session, or run a trial.

Before any supervised run: install a fully verified combined artifact with G1
disconnected, confirm Portable health, then separately supervise attach and
idle TV-Docked readiness. Keep the cable attached throughout launch/recovery
and resource verification. Software removal and physical unplug are separate,
unimplemented milestones. Current policy remains shutdown before disconnect.
