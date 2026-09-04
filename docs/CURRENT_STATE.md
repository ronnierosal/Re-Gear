# Current state

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
