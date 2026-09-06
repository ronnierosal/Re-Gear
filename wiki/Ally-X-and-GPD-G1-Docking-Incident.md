# Ally X and GPD G1 docking incident

> Historical September 2 evidence. Statements about pending candidates below describe that session, not the current build. See [Current State](Current-State) for the maintained summary.

**Audience:** developers, maintainers, and supervised hardware testers<br>
**Evidence reviewed:** 2026-09-02<br>
**Maturity:** display/render fix hardware tested once; guarded automatic audio
handoff implemented and simulated

The full engineering record is the repository's
[dated incident note](https://github.com/ronnierosal/Re-Gear/blob/main/docs/ALLY_X_GPD_G1_DOCKING_INCIDENT_2026-09-02.md).
Current capability truth remains in
[Current State](https://github.com/ronnierosal/Re-Gear/blob/main/docs/CURRENT_STATE.md).

## What users saw

The G1 was physically attached and the TV was on the correct HDMI input, but
HDM initially reported incomplete eGPU evidence. Later attempts progressed far
enough to restart Gamescope: the Ally display briefly turned off and the TV
reported a signal, yet the TV stayed black and HDM returned to Portable. Once
the display path was fixed, Steam appeared on the TV and the RX 7600M XT was
selected, but sound initially remained on the Ally.

This was not one detection bug. It was a chain of independent failures revealed
one at a time by the previous fix.

## The root-cause chain

| Stage | Root cause | Correction | Evidence |
|---|---|---|---|
| Readiness | SteamOS supplied negotiated PCIe width in a valid form the parser rejected | Accept that form while preserving strict link validation | Regression tested |
| Transition | HDM had not connected exact G1/TV readiness to the proven Gamescope restart mechanism | Add an off-by-default, one-request-per-attachment automatic coordinator behind existing gates | Implemented and simulated, then exercised during later success |
| Journal | A shared terminal journal was shown without identifying the workflow that owned acknowledgement | Route acknowledgement by categorical owner and re-arm only after an exact valid acknowledgement | Hardware tested for routing and retry |
| Launch binding | Writer used the raw boot ID while the shim re-hashed an already-hashed value | Use raw boot identity only in memory for the private binding; serialize only its hash | Hardware diagnosed; regression tested |
| File access | Root wrote `presentation.json` as `0600`, so the `deck`-owned Gamescope shim could not read it | Make the identity-minimized config root-owned and world-readable (`0644`), retaining launch-time hardware revalidation | Hardware tested once: TV active and RX 7600M XT selected |
| Audio | Display success left the internal SteamOS loopback sink as default | Resolve the exact G1 HDMI loopback's transient node ID just in time, select and verify it, and retain a Portable rollback target | Direct selection hardware tested; automatic path simulated |

## Why “connected” was not enough

These facts must remain independent:

- USB4 device present;
- exact G1 GPU/audio/bridge topology present;
- link observed Up;
- TV connector connected and EDID-ready;
- TV actually active in the new Gamescope session;
- RX 7600M XT actually selected for rendering;
- expected audio sink actually default;
- game state known and safe;
- transition journal owned and resolved.

The black-screen attempts are a useful example. The TV detected a signal, but
the restarted Gamescope session had selected the internal panel. HDM's verifier
correctly rejected that as TV success and recovered to Portable.

## What finally worked

With the readable launch config installed, one supervised attach resolved the
exact Ally X/G1 profile, one EDID-ready TV, an observed-Up link, and Idle game
state. HDM restarted Gamescope, made the TV the only active display, selected
the RX 7600M XT, showed Steam on the TV, and committed the presentation journal.

Read-only PipeWire inspection then located the G1 HDMI output. A supervised
selection moved sound to the TV and the player confirmed it. The follow-up code
now treats audio as a guarded child transaction: capture Portable default,
freshly resolve the G1 sink, switch and verify, and restore it on rollback or
return. PipeWire numeric node IDs are ephemeral and are never persisted.

## Lessons for developers

1. Diagnose the earliest divergence; do not stack speculative fixes.
2. Never equate connector presence with active output.
3. Test privileged-writer to unprivileged-reader handoffs end to end, including
   ownership, mode, binding inputs, and fallback behavior.
4. Keep display, render, audio, controller, game state, and connection state
   independently observable.
5. Never hard-code DRM card numbers, connector suffixes, PCI addresses, or
   PipeWire node IDs.
6. Preserve rollback evidence before mutation and fail closed on ambiguity.
7. Keep installed, simulated, and hardware-tested claims separate.

## Remaining gates

- Install and exercise the guarded automatic audio build with the G1 absent
  during installation, then verify automatic TV sound and Portable restoration.
- Investigate the separate cold-start built-in-controller issue.
- Repeat the full connect, dock, gameplay, return, shutdown/disconnect,
  sleep/recovery, and reconnect journey before certification.
- Continue to shut down fully before physically disconnecting the G1.

## What the later live-pull observation taught us

In one player-directed idle test, the G1 was physically removed while TV Docked.
The Ally backlight returned black, Gamescope and Steam stopped, and the G1
profile became Unknown because stale/incomplete USB4 evidence remained. The
operating system, network, and Decky stayed alive. Roughly 80 seconds later,
SteamOS restarted Gamescope on the internal panel and restarted Steam; the
player confirmed both the interface and built-in controller worked.

That is recovery evidence, not safe-removal certification. HDM's follow-up code
therefore observes the native path instead of racing it with another restart.
It arms only from exact idle TV Docked, waits up to 120 seconds, verifies a
fresh Portable state, and then restores the previously captured Portable audio
sink. Unknown or contradictory evidence and timeout require attention without
display mutation. Shutdown-before-disconnect remains the supported rule.

## What the later reconnect taught us

After the native recovery supervisor was installed, a later G1 attach produced
USB4 and PCI evidence for the RX 7600M XT but no bound `amdgpu` driver, DRM card,
or TV connector. HDM correctly refused to dock. This separates successful
Portable fallback from subsequent driver/tunnel recovery; one does not prove
the other. No driver probe, unbind, or USB4 reset was attempted.

The next local candidate adds a controller-focusable **Prepare G1 disconnect**
workflow. It returns TV Docked to verified Portable through the same durable
transition engine, requires acknowledgement, then allows a separately confirmed
normal shutdown only from fresh idle Portable evidence. Cable removal remains
permitted only after fans and every power LED are off. Attach settling and
correlated unexpected-loss observation tighten to 250 ms, but kernel USB4/PCI
enumeration and Gamescope restart remain independent timing budgets.

## What the first shutdown-before-disconnect test taught us

The 2026-09-02 installed `a988c0cf1d61` run automatically reached the TV on a
second attempt, selected G1 HDMI audio, and returned to the Ally display through
**Prepare G1 disconnect**. Two additional defects were then observed:

- acknowledging the intentional Portable transition re-armed automatic docking,
  so the operator first had to disable automatic TV docking; and
- the normal power-off request removed SSH and ping, but the Ally fan and two
  top LEDs remained on until a roughly twelve-second manual power-button hold.

The follow-up changes persist the categorical transition target so Portable
acknowledgement suppresses redocking until G1 removal. They also rename and
describe shutdown as an unverified request: an accepted system command is not
proof that the Ally reached physical off. The firmware-level hang is unresolved.
Keep the G1 connected if the fan remains on; after 60 seconds use a manual long
power-button hold, and remove the cable only after the fan stops. HDM does not
automate forced power-off.

See [Troubleshooting](Troubleshooting),
[Safety and eGPU Handling](Safety-and-eGPU-Handling), and
[Issues Fixed](Issues-Fixed).
