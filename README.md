<div align="center">

<img src="docs/images/re-gear-readme-logo.png" alt="Re-Gear: handheld today, console tomorrow" width="560">

# Re-Gear

**Safety-first, games-first reliability companion for SteamOS handheld PCs**

Re-Gear aims to make handheld gaming console-simple: status first, low overhead,
and no avoidable surprises. It verifies GPU, display, Gamescope, game, and
hardware state before a guarded dock-mode action.

[![CI](https://github.com/ronnierosal/Re-Gear/actions/workflows/ci.yml/badge.svg)](https://github.com/ronnierosal/Re-Gear/actions/workflows/ci.yml) [![Last commit](https://img.shields.io/github/last-commit/ronnierosal/Re-Gear)](https://github.com/ronnierosal/Re-Gear/commits/main/) [![Development](https://img.shields.io/badge/status-in_development-6f42c1)](#-current-status) ![Platform](https://img.shields.io/badge/platform-SteamOS-1b2838?logo=steam) [![License: GPL-3.0-or-later](https://img.shields.io/badge/license-GPL--3.0--or--later-2ea44f)](LICENSE)

[Wiki / Player Guide](https://github.com/ronnierosal/Re-Gear/wiki) · [Current status](#-current-status) · [Safety](#-safety-first) · [Development](#-development) · [Documentation](#-documentation)

</div>

> [!IMPORTANT]
> Re-Gear is in active development and is not a general-availability release.
> Implemented features include diagnostics, eGPU sleep protection, reviewed
> support bundles, and guarded TV/Portable transitions. Automatic TV docking is
> experimental and requires an explicit, off-by-default player opt-in.
> Supervised successes on the documented test configuration do not establish repeatable operation or
> general hardware support. Physical live eGPU removal remains unsupported.

> [!CAUTION]
> Physical live removal is unsupported on the current certified hardware.
> Restore internal operation and shut the handheld down before disconnecting an
> eGPU. Loss of SSH or an accepted shutdown request is not proof of physical
> power-off; verify that the handheld has actually powered down.

## 📖 About

Re-Gear (formerly Handheld Dock Mode / HDM) is a Decky Loader-native reliability companion for
console-like SteamOS handheld gaming. Its North Star is to reduce PC-gaming
paper cuts by detecting problems, preventing avoidable failures, explaining
state in player language, and safely guiding or performing verified recovery
where authority and evidence allow. Docking is the first domain, not the
product boundary; today’s implemented scope remains deliberately narrower.
Re-Gear presents player-friendly placement and journey status—such as **Portable**
or a **TV Docked** target—instead of DRM connectors, PCI addresses, GPU
selectors, or Gamescope arguments. Current native transition authority remains
intentionally narrow and supervised.

The project is deliberately fail-closed. If Re-Gear cannot prove the exact hardware,
active display, render GPU, game state, or rollback path, it reports the state
as unknown or degraded and blocks the action.

### ✨ What works today

- 🔎 Read-only discovery of the host, DRM devices and connectors, Gamescope,
  Steam game scopes, PCI topology, USB4 topology, and exact eGPU clients
- 🎮 Compact, controller-first Quick Access dashboard with Re-Gear branding,
  placement status, contextual actions, and expandable troubleshooting
- 📺 Guarded TV/Portable transitions through a shared journaled engine, with
  experimental opt-in automatic TV docking for the exact Ally X/GPD G1 profile
- 🔊 Exact G1 HDMI audio selection and Portable audio restoration with
  fail-closed identity and rollback checks
- 🧭 Confidence-aware placement inference without hard-coded card numbers,
  connector suffixes, or PCI bus addresses
- 🛡️ Two-layer sleep protection while a supported eGPU is attached: a bounded
  login1 inhibitor and Steam's native preflight blocker
- 📦 Preview, copy, and token-approved save of a bounded, redacted support bundle
- 📊 Adaptive Decky polling, collection timings, and an optional troubleshooting
  overlay with bounded health, recovery/link explanations, and HDM-overhead
  status that never claims game impact
- 🧭 Compact controller-first Journey status: deferred dock, prepared idle,
  Safe Undock evidence, recovery, and link explanations; newer 0.3.x candidates
  also deliver selected-game Offline Readiness from local Steam evidence
- 🧪 Deterministic transition, rollback, crash-recovery, process-release, sleep,
  compatibility, and failure-injection simulations
- 🔧 Explicitly approved preparation of the reversible Gamescope integration
  used for supervised display validation
- 🧹 Redacted inspect/confirm flow for graceful release of exact eligible
  non-game eGPU clients, with separately confirmed force escalation

Preparation only installs, reloads, and verifies the fixed integration boundary.
It cannot restart Gamescope, switch a display, or select a GPU.

## 🚦 Current status

**Development source: Re-Gear 0.3.58 on `main`** (reviewed **2026-09-08**).
The 0.3.55 release line has been integrated into main. See the
[dated status snapshot](docs/STATUS_SNAPSHOT_2026-09-08.md) for the exact reviewed
revision and the distinction between source, installation reports, and validation.
Re-Gear remains experimental and is not a supported general-availability release.

Main includes compact connection/disconnect status, local Steam Offline Readiness
badges and refresh recovery, and guarded TV/Portable workflows. Quick Access
navigation, Auto TDP, and eGPU release/removal improvements have separate review
and validation gates; an open PR is not part of main merely because its tests pass.

The September 8 operator record reports installed **0.3.58**. This documentation
review did not inspect a device or verify a fresh installed revision or archive
checksum. The separate **0.3.56** graphics-trial candidate remains recorded as
staged and unvalidated; version numbers alone do not order different branch work.
Use exact source ancestry, artifact metadata, and a fresh deployment handoff before
selecting a build.

### Validation and limitations

Individual supervised docking successes do not establish repeatable operation or
support for other hardware. Physical live eGPU removal remains unsupported, and
reliable shutdown, recovery, and repeated transition cycles still need validation.

The September 8 resource-release account reports a clear scan and source-driven
software removal/rescan. Known scan gaps and the absence of an archived capture
prevent treating that report as complete-release proof or unplug clearance.

See the Wiki's [Current State](https://github.com/ronnierosal/Re-Gear/wiki/Current-State)
for feature status and blockers, [Confirmed Hardware Testing](https://github.com/ronnierosal/Re-Gear/wiki/Confirmed-Hardware-Testing)
for capability-specific evidence, and the [dated source/evidence snapshot](docs/STATUS_SNAPSHOT_2026-09-08.md)
for build provenance. Detailed engineering records remain linked from those pages.

## 🕹️ Player-facing placements

Re-Gear keeps observed placement separate from workflow progress so a pending or
failed action can never overwrite hardware truth.

| Placement | Meaning | Current state |
|---|---|---|
| **Portable** | Internal GPU → internal panel | Hardware tested |
| **Boosted Handheld** | Verified eGPU → internal panel | Unproven |
| **Docked-iGPU** | Internal GPU → external display | Read-only observer implemented; placement remains unverified |
| **TV Docked / Docked-eGPU** | Verified eGPU → its directly attached display | Bounded native Ally X/G1 hardware success; handoff remains experimental |

Incomplete or conflicting evidence is surfaced as **Unknown** or **Degraded**.
Workflow phases such as Connecting, Action Required, and Failure remain a
separate axis.

## 🛡️ Safety first

Guarded transitions follow one journaled, verifiable path:

```text
DETECT → VALIDATE → PLAN → PREPARE → APPLY → VERIFY → COMMIT
                                      │
                                      └─ failure → ROLL BACK or retain known-good state
```

The core rules are simple:

- Never migrate a running workload between GPUs.
- Block a Gamescope restart while a game is running—or when game state is
  unknown.
- Treat connector names, DRM card numbers, and PCI addresses as observations,
  never stable identity.
- Revalidate exact hardware and user intent immediately before any approved
  mechanism.
- Require a verified result before declaring a transition complete.
- Preserve a known-good state or execute bounded rollback on failure.
- Never treat cleared software clients as proof that physical eGPU removal is
  safe.
- Redact hostnames, addresses, home paths, and unique hardware identifiers from
  support data by default.

The complete release gates live in [Safety invariants](docs/SAFETY_INVARIANTS.md).

## 🧩 Hardware support

The first certified identity profile is intentionally narrow:

| Component | Profile |
|---|---|
| Handheld | ASUS ROG Ally X running SteamOS |
| eGPU | GPD G1 with AMD Radeon RX 7600M XT (`1002:7480`) |
| Display | TV connected directly to the G1 |

Certification is capability-specific. Exact identity, read-only discovery,
Portable inference, and the sleep guard have hardware evidence; this does not
certify repeatable display/audio handoff, Boosted Handheld, or live removal.
Supervised TV and Portable successes retain their bounded experimental status.
Other hosts, eGPUs,
and SteamOS versions are not promoted by similarity.

See [Hardware support](docs/HARDWARE_SUPPORT.md) and the
[dated validation record](docs/HARDWARE_VALIDATION_2026-08-31.md) for the exact
evidence and known limitations.

## 💾 Installation

There is no public release or supported end-user installer yet. Current builds
are development artifacts for controlled validation through Decky Loader's
native lifecycle. Do not copy files into a running plugin or combine frontend
and backend artifacts from different commits.

Each successful CI run retains one **controlled validation artifact** for 14
days. It contains the ZIP, its SHA-256 manifest, and the exact source revision;
it is not a GitHub Release, public installer, or automatic deployment. Use it
only when its workflow commit, `source-revision.txt`, and the installed QAM
**Re-Gear build** label agree.

After unzipping a downloaded artifact, run
`python scripts/verify_validation_artifact.py <artifact-directory>` from a
source checkout. It verifies the package checksum and its embedded build label
before any Decky installation; it does not contact or modify a handheld.

The CI artifact also contains a local-only release-candidate manifest and
release-notes template. They validate one semantic version, build revision, and
archive SHA-256, but do not publish anything. See the explicit maintainer-only
[release-candidate pipeline](docs/RELEASE_PIPELINE.md); GitHub publication and
Decky Store/channel registration remain separate manual gates.

Hardware validation must follow the staged
[deployment and validation strategy](docs/DEPLOYMENT_VALIDATION.md), beginning
with one clean, provenance-recorded package and the eGPU disconnected.
A historical player-present preparation record is
[Supervised Ally session preparation](docs/SUPERVISED_SESSION_2026-09-01.md);
it is a dated artifact/readiness record, not current deployment authority or a
hardware result. Use a fresh deployment handoff for any supervised session.

## 🛠️ Development

### Prerequisites

- Python 3.11 or newer
- Node.js 24
- pnpm 11.19.0

Install the frontend dependencies:

```bash
pnpm install --frozen-lockfile
```

Run the complete local verification matrix:

```bash
python scripts/check_architecture.py
python -m unittest discover -s tests -v
python -m compileall -q backend tests scripts
pnpm typecheck
pnpm test:frontend
pnpm build
python scripts/check_plugin_package.py .
```

Build the deterministic Decky archive:

```bash
python scripts/build_plugin.py
```

The build script writes `out/Re-Gear-<version>.zip`. The internal Decky directory
remains `HandheldDockMode` for compatibility. Never deploy if a
check fails, the worktree contains unexplained changes, or artifact provenance
cannot be matched to one commit.

### Read-only diagnostics

Emit a local SteamOS snapshot:

```bash
PYTHONPATH=backend python -m hdm.cli
```

Capture bounded, redacted state from an installed handheld without writing a remote
file:

```bash
python scripts/remote_capture.py --host <handheld-ip> --identity-file <ssh-key>
```

The production plugin exposes no general-purpose command endpoint. Privileged
operations remain constrained to documented adapters and approval boundaries,
including guarded presentation and shutdown-before-disconnect workflows.

## 🏗️ Architecture

```text
Decky UI / diagnostics CLI
            │
      application services
       ╱             ╲
read-only snapshot   guarded transition engine
       ╲             ╱
        pure domain policy
          ╱        ╲
 SteamOS adapters  hardware profiles
```

`backend/hdm/domain` is pure policy with no filesystem, subprocess, network, or
operating-system calls. Mechanisms live behind narrow ports, hardware
capabilities come from exact profiles, and public Decky RPCs are checked against
an explicit allowlist.

Re-Gear is a new SteamOS-first implementation. eGPUBridge supplied useful hardware
evidence, but its architecture and behavior are not inherited as proof.

## 📚 Documentation

Start with the **[Re-Gear Wiki](https://github.com/ronnierosal/Re-Gear/wiki)** for
getting started, supported hardware, Offline Readiness, safety, troubleshooting,
and FAQs. Repository documents retain engineering and validation authority.

| Topic | Document |
|---|---|
| Authority and navigation | [Documentation index](docs/INDEX.md) |
| Current repository/build/deployment truth | [Current state](docs/CURRENT_STATE.md) |
| Product scope and placements | [Product definition](docs/PRODUCT.md) |
| Non-negotiable release gates | [Safety invariants](docs/SAFETY_INVARIANTS.md) |
| Components and state model | [Architecture](docs/ARCHITECTURE.md) |
| Evidence and ordered milestones | [Authoritative roadmap](docs/ROADMAP.md) |
| Certified identities and limitations | [Hardware support](docs/HARDWARE_SUPPORT.md) |
| Deployment stages and stop conditions | [Deployment validation](docs/DEPLOYMENT_VALIDATION.md) |
| Redacted diagnostic contract | [Diagnostics](docs/DIAGNOSTICS.md) |
| Support preview and export | [Support bundle](docs/SUPPORT_BUNDLE.md) |
| Remote read-only capture | [Remote validation](docs/REMOTE_VALIDATION.md) |
| Transition safety and recovery | [Experimental transitions](docs/EXPERIMENTAL_TRANSITIONS.md) |
| Sleep request policy | [Sleep workflow](docs/SLEEP_WORKFLOW.md) |
| Verified game-save boundary | [Game save](docs/GAME_SAVE.md) |
| Process-release boundary | [Process release](docs/PROCESS_RELEASE.md) |
| Contributor and Git workflow | [Development](docs/DEVELOPMENT.md) |
| Player-facing UI contract | [UI specification](docs/UI_SPEC.md) |
| eGPUBridge capability preservation | [Parity audit](docs/EGPUBRIDGE_FEATURE_REVIEW.md) |
| Wiki source and maintenance | [Publishing workflow](wiki/README.md) |

Additional design records and compatibility documents are available in
[`docs/`](docs/).

## 🤝 Contributing

Players can help without writing code: follow [Help Improve Re-Gear](https://github.com/ronnierosal/Re-Gear/wiki/Help-Improve-Re-Gear)
for a useful bug report, reviewed support export, and optional read-only diagnostic
commands. See the [Feature Roadmap](https://github.com/ronnierosal/Re-Gear/wiki/Feature-Roadmap)
for our core goal and development priorities.


Contributions should preserve the safety invariants, pure-domain boundary, and
fail-closed defaults. Keep changes narrow, add deterministic regression coverage,
and use verification proportional to the change. Run the full matrix at
meaningful integration, deployment, and release gates.

Hardware-affecting changes require an explicit milestone decision, supervised
execution, rollback coverage, and redacted before/live/after evidence.
See [Contributing](CONTRIBUTING.md) and the
[development workflow](docs/DEVELOPMENT.md).

## 📜 Licensing

Re-Gear's community distribution is licensed under the
[GNU General Public License version 3 or later](LICENSE) (`GPL-3.0-or-later`).
Commercial/OEM integration, redistribution, bundling, customization, support,
or branding under terms outside GPLv3+ requires a separate negotiated license;
see [licensing](docs/LICENSING.md). Third-party notices remain in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
