# HDM 0.1 read-only hardware validation — 2026-08-31

> Historical record: HDM was Re-Gear's former name; original wording is retained.

## Scope

The in-progress HDM 0.1 diagnostics CLI was copied to a unique `/tmp` directory
and run as the normal `deck` user on the reference ASUS ROG Ally X. The test made
no configuration changes, performed no service restart, and did not alter display
or GPU state.

Observed state:

- SteamOS Gamescope session active on `-O *,eDP-1`
- Internal `eDP-1` panel connected and uniquely inferred as active
- Internal AMD GPU `1002:15bf` present
- No external DRM GPU present
- Ally X DMI profile recognized as certified
- A Steam game scope detected, producing `game_state=running`

## Result

Host, DRM, output, and game-scope discovery passed on real hardware. HDM did not
claim Portable mode because the render GPU could not be verified at the CLI's
privilege level.

Although Gamescope runs as `deck`, this SteamOS build exposes
`/proc/<gamescope-pid>/environ` as root-owned mode `0400`. The normal user cannot
read it. The user systemd manager had no visible `MESA_VK_DEVICE_SELECT` value,
but manager state alone does not prove the already-running process environment.
The CLI therefore reported:

- Gamescope confidence: `observed`
- Inferred mode: `unknown`
- Blocker: `gamescope_environment_unreadable`
- Blocker: `render_gpu_unknown`

This is the intended fail-closed result.

## Delivery follow-up

The Decky delivery adapter was implemented around the unchanged
snapshot service. Its manifest requests Decky's root execution flag, and its
only public RPC is the read-only `get_snapshot` operation. When root observes the
Gamescope owner, the game-scope adapter reads that owner's current cgroups and
retains one strictly validated user-systemd query as a fallback. The root
Portable validation is recorded below; TV Docked remains pending.

## Decky root validation

The corrected 0.1 development package was installed through Decky Loader 3.2.6
under the separate `HandheldDockMode` directory. Decky ran `main.py` as root and
left the installed eGPUBridge directories unchanged.

The first root snapshot verified the protected Gamescope environment and
Portable mode, but the root-to-user systemd fallback returned a nonzero status
for the Steam game-scope query. HDM was changed to read the observed Gamescope
owner's cgroup hierarchy first, retaining the strict systemd query only as a
fallback. After reinstall, the live Decky RPC reported:

- mode: `portable`
- game state: `idle`
- support tier: `certified`
- render GPU: `internal-gpu`
- output order: `*,eDP-1`
- blockers: none

The Quick Access Decky page listed **Handheld Dock Mode** beside eGPUBridge, CSS
Loader, and SteamGridDB. This validates the native plugin lifecycle, root
snapshot boundary, frontend registration, and Portable read-only path. TV
Docked validation remains pending until the G1 and TV are naturally connected;
HDM performed no transition or hardware mutation during this check.

## Live G1 disconnect-readiness validation

The schema 2 package was then deployed through Decky's authenticated installer.
With the G1 naturally attached while Gamescope remained in Portable mode, the
first scan failed closed because the captured topology contains several Intel
`8086:15ef` bridge functions plus an identity-less authorized USB4 host-router
record. The original profile had incorrectly required one `15ef` function in
the full GPU ancestry and counted the host-router record as an external device.

The profile was corrected to require one top-level removable `15ef` bridge,
allow downstream PCI bridge functions, and ignore only the identity-less USB4
host-router node. Any additional or unidentified external authorized USB4 node
still blocks certification. Unit fixtures now cover the observed multi-bridge
topology and host-router record.

After reinstall, the live root RPC reported:

- exact G1 identity: verified (raw USB4 identity omitted)
- host/G1 support tier: `certified`
- mode: `portable`; Gamescope remained on the internal GPU and panel
- game state: `idle`
- disconnect scan: complete
- storage routed through the G1: none observed
- exact resource client: `wireplumber`, holding G1 `audio_control`
- client classification: protected SteamOS session process, not close-eligible
- disconnect readiness: blocked

The native Quick Access panel rendered the same blocker and the explicit
read-only notice. No process was signaled, no GPU/display selector changed, and
no disconnect or hardware removal was attempted. TV Docked transition
validation remains pending.

## Live G1 sleep-guard validation

The schema 3 package was installed through the same Decky-native flow while the
G1 remained naturally attached. Decky's temporary dynamic-loader environment
initially prevented the system `systemd-inhibit` binary from starting; the
bounded process adapter was corrected to remove only loader and Python path
overrides before launching the SteamOS system binaries.

After reinstall, three independent observations agreed:

- the root Decky RPC reported `sleep_guard.required=true`,
  `sleep_guard.active=true`, and `confidence=verified`
- `systemd-inhibit --list` showed **Handheld Dock Mode** holding a `sleep` lock
  in `block` mode as root
- the Quick Access panel showed **Sleep protection** and **Blocked while G1
  attached**, with the frontend-only **Never show this explanation again**
  control

The system remained in Portable mode, no game was running, and `wireplumber`
remained the protected audio client blocking disconnect readiness. No sleep
request, process signal, GPU/display change, disconnect, or physical removal was
attempted. Quick Access, physical-button, idle, and direct login1 sleep-request
tests remain separate supervised acceptance work.

## Steam active-session Sleep acceptance failure

With the same exact G1 still attached, Steam's visible **Power → Sleep** menu
item was activated through the live active-session UI. A bounded before/after
capture showed:

- the Sleep menu item was found and invoked in Steam's power menu
- the kernel boot ID remained identical before and after the request (raw value
  omitted)
- uptime advanced continuously from `9520.61` to `9538.91` seconds
- login1 `PreparingForSleep` remained `false`
- the same root HDM inhibitor process remained active
- the internal and G1 DRM card/render device identities remained unchanged
- continuous network reachability showed no suspend/resume interruption
- the user observed a lit backlight with a black screen
- both legacy framebuffer blank controls reported `4` after the request

This validates only that Steam's active-session Sleep request did not enter full
suspend while HDM held the G1 sleep inhibitor. It fails the player-facing
acceptance criterion because Steam's player-facing sleep sequence did not
restore presentation after login1 rejected suspend. Synthetic Steam input and a
short physical power-button press did not restore the display. A graceful
reboot requested through Steam completed normally and restored the visible
internal screen; Gamescope, the exact G1, and the HDM inhibitor returned
successfully.
The legacy framebuffer blank controls still reported `4` with the screen visibly
working after reboot, so that value is not treated as a causal indicator. An
SSH-issued `systemctl suspend` request also returned `Access denied` without
changing state, but that result is not counted as direct-login1 acceptance
because the remote session may have failed active-seat PolicyKit authorization
before inhibitor evaluation.

The installed logind configuration reports `HandlePowerKey=ignore`, so Steam
owns the visible physical-button behavior on this build. Do not repeat the Steam
Sleep action or proceed to physical-button/idle acceptance until HDM can stop the
player-facing sequence before it can leave presentation black. No
inhibitor-bypass option was used.

## Steam preflight non-sleep lifecycle proof

The capability-resolved Steam preflight package was installed through Decky
Loader 3.2.6 while the same exact G1 remained attached. The validation used the
shared Steam suspend store's native blocker count only; it did not call
`RequestSleep`, `OnSuspendRequest`, `SuspendPC`, or any physical power control.

Observed lifecycle:

- before the new frontend loaded, the Steam native suspend-blocker count was `0`
- plugin load acquired exactly one HDM lease, producing count `1`
- repeated probes across multiple three-second snapshot polls remained at `1`
- Decky's frontend unload lifecycle invoked `onDismount` and returned the count
  to `0`
- backend disable also released the root login1 inhibitor and stopped the HDM
  backend process
- backend enable and frontend re-import reacquired both layers; repeated probes
  again remained at exactly `1`
- an existing unrelated-blocker preservation case is covered separately by the
  deterministic frontend test harness

The development deployment WebSocket temporarily became Decky's active event
recipient, so the first backend-only disable did not deliver the frontend event
to Steam and was not counted as an unload proof. The accepted measurement used
Decky's actual `DeckyPluginLoader.unloadPlugin` frontend lifecycle and observed
the expected `1 → 0` release directly.

Phase A therefore passes. Phase B remains blocked until it is deliberately
supervised: one visible Steam **Power → Sleep** request must show HDM's warning,
leave the internal display usable, preserve boot ID and continuous uptime, and
never begin Steam's preparation sequence.

## Steam preflight supervised warning iteration

Three supervised Steam **Power → Sleep** requests were made after phase A. In
all three, Steam logged that the suspend request was ignored because of its
native blockers. The kernel boot identifier stayed unchanged, uptime advanced
continuously, login1 `PreparingForSleep` stayed `false`, Gamescope remained
running, and the internal eDP connector remained connected. The earlier black
presentation failure did not recur.

The first two attempts used a ten-second Decky toast. The player observed that
the toast disappeared too quickly, so these runs pass enforcement and display
safety but fail acknowledgement UX. The third attempt used a synchronous Decky
confirmation modal; no warning was visible after Steam closed its Power menu,
so that attempt also fails the UX criterion. The likely cause is that Steam
discarded the modal with the transient Power menu that was still closing.

HDM now delays the modal by 750 ms, anchors it to Decky's non-popout window, and
requires the player to press **OK**. That exact bundle is installed and its hash
matches the local build. Decky reports one HDM native blocker, the frontend
reload lock is clear, and the root login1 inhibitor is active. A further Sleep
request is intentionally pending until the player is present to confirm that
the delayed modal stays visible; no unsupervised sleep test is authorized.

## Installed backlog build and visible-parent correction

Commit `0c96633` was installed through Decky's native reinstall flow. The Ally
and local SHA-256 values matched for `main.py`, the frontend bundle, support
bundle policy, and fixed export adapter. The live RPC reported Portable, idle,
certified hardware, a verified active sleep guard, a complete blocked
disconnect scan, a 30.462 ms total snapshot, and a bounded redacted support
preview. Preview-only verification wrote no file.

Two supervised attempts then exercised Steam's menu Sleep action and the
physical power button. Steam logged **Suspend request ignored due to suspend
blockers** for both; the device remained awake and visible and the root
inhibitor remained active. Neither attempt displayed the acknowledgement
dialog, so enforcement passed while warning UX failed.

Inspection found both HDM dialogs explicitly passed the plugin's global
`window` to Decky's modal helper. HDM executes in the invisible
SharedJSContext, while Decky's omitted-parent behavior resolves the visible SP
window. The warning and support-preview call sites now omit that invalid parent
and retain the non-popout option. Corrective commit `c49f01a` passed the full
local and GitHub CI matrix and was installed through Decky's native flow. The
installed frontend SHA-256 matched the corrective local bundle, the backend
restarted cleanly, and the root inhibitor reacquired. One later supervised
visible-dialog proof remains pending; the two accepted blocker results do not
count as warning acceptance.

## Remote read-only capture harness proof

The fixed SSH-stdin collector was run against the Ally without installing an
agent or writing a remote file. The local bounded report declared its collector
hash and no-write behavior and returned without collection errors. Its redacted
observations showed:

- installed HDM version `0.2.0` and present critical plugin files
- one Gamescope process and one Decky plugin-loader process, without PIDs
- certified Ally X/G1 profile, idle game state, and attached-G1 disconnect scan
- disconnect readiness blocked

The standalone collector cannot observe the Decky process's login1 inhibitor.
The corrected capture therefore reports that check as `not_observed` and does
not classify the lease as active or inactive. No sleep request, process signal,
service restart, display/GPU change, hardware removal, or remote file write was
performed.

The harness was later extended with an explicit fixed root read-only mode that
can only request `sudo -n /usr/bin/python3 -` and verifies the reported
execution privilege. The full local validation matrix passed. The current Ally
returned SSH status 1 for that non-interactive sudo request, so the wrapper
stopped without prompting, retrying, saving a capture, or running a fallback.
The privileged success path therefore remains UNVERIFIED on hardware; this
failed attempt supplies no additional Gamescope, client, or sleep-lease
evidence and performed no HDM or hardware mutation.

## Supervised presentation preparation and first TV-switch result

The user explicitly authorized cleanup of an eGPUBridge integration that still
owned the Gamescope user-service `PATH` override after its Decky UI uninstall.
The cleanup removed that fixed override and reloaded the user manager without
restarting Gamescope; a recoverable backup was retained. This was a one-time
environment repair, not an HDM automatic-uninstall capability.

HDM's controller-first presentation-preparation flow was then exercised while
Portable and idle. The first Decky request was rejected because the frontend
sent Decky RPC placeholder arguments that the backend treated as actual
arguments. Commit `c2fc911` accepts the framework placeholders only for this
fixed endpoint. After native Decky reinstall, the on-screen confirmation
successfully prepared HDM's reversible integration and reported that no
Gamescope restart or display switch occurred. Read-only verification confirmed
that the prepared integration remained active and the internal display session
was usable.

A later player-watched idle TV-switch attempt was made only after the eGPU and
TV evidence were ready and the game state was idle. It did not move output to
the TV. The known-good internal display remained available. Inspection found
the transition mechanism wrote the shim-facing boot presentation config under
the root-only transaction-journal directory, but the prepared Gamescope shim
reads a fixed directory under the verified Gamescope user's home. Commit
`8c721fb` corrects that location while retaining the journal in root-owned
state.

Result: preparation is hardware-exercised; the first TV-switch acceptance
attempt failed; the correction is implemented and locally tested but **not yet
hardware validated**. No automatic attach behavior is enabled. A new watched
test of the corrected build must collect before/attempt/after evidence and
either verify TV presentation or verify a clean Portable rollback before this
path can advance.

## Gaming-safe read-only capture before the next candidate

At `2026-08-31T15:08:58-07:00`, the fixed unprivileged SSH-stdin collector ran
while the player was using the Ally. It completed with zero collection errors,
wrote only the bounded local capture on the development computer, and reported:

- one Steam, one Gamescope, and one Decky plugin-loader process
- an exact Ally X host profile and known running-game state
- one verified internal GPU and the active internal panel
- no observed external GPU or connected external display in that sample
- Gamescope running, but render selection unverified because the unprivileged
  collector could not read the protected environment

The observation does not establish physical cable state and does not validate a
G1 workflow. The standalone collector again could not observe the Decky-owned
sleep lease. All five installed critical-file hashes differed from current
commit `85b8feb`, although both packages report version `0.2.0`; this proves the
Ally was still running an older 0.2.0 candidate and prevents attributing this
capture to current code. No install, reload, suspend, signal, service restart,
display/GPU change, or hardware action occurred while the game was running.
