# Target-based frame generation on SteamOS

Research and architecture proposal, checked **2026-09-22**. This is not a
supported-game catalogue, installation guide, or runtime integration.

## Decision

Keep the player's choice at an experience target such as 60 FPS. Resolve native
rendering first, then validated upscaling, then validated frame generation (FG).
Choose a validated lower target or Advisor when none can deliver acceptable
gameplay. Generated presentation FPS is never evidence of base FPS or input
responsiveness.

LSFG-VK is technically relevant, but research does **not** yet establish a
suitable automatically deployable Re-Gear provider. Current licensing, SteamOS
integration, per-game validation, and recovery after in-process injection remain
open. Do not bundle, install, enable, or automatically launch it in this slice.
The first proof of concept below is now implemented as an inert fixture plan,
reusing Claude's PR #381 and unchanged PR #386 engine contract. This simulation
cannot close production gates. Independent configuration of user-installed
components can proceed without redistributing them; the rights question is about
the eventual integration/distribution model, not a blanket prohibition on
implementing configuration-data generation.

The foundation is Claude's [PR #375](https://github.com/ronnierosal/Re-Gear/pull/375),
accepted for architecture and a synthetic first adapter at
`9d48d617763c5157296e8b98d569ed53872028ae`, based on
`661de9406f20773cd54905768c41198251a77a1a`. It remains unmerged and owned by Claude.
Compose with [graphics profiles](../GRAPHICS_PROFILES_ARCHITECTURE.md); do not
replace its schema checks, backup/provenance, conflict handling, or lifecycle.
Codex owns this new research/provider proposal under Ronnie's explicit assignment.

## Current options and evidence

| Option | Evidence and limit | Re-Gear disposition |
| --- | --- | --- |
| Windows Lossless Scaling application | The [developer's Steam listing](https://store.steampowered.com/app/993090/Lossless_Scaling/) identifies a Linux community port. This does not establish that the Windows capture/application path works transparently under Proton. | Do not wrap the Windows app or infer compatibility from its installation. |
| LSFG-VK 2.0.0 | [September 5 release](https://lsfg-vk.dev/blog/release-v2.0.0/) is the current upstream baseline examined; the old GitHub release view is stale after migration. Vulkan layer using separately obtained LSFG components. | External provider candidate; no production admission. |
| Native game FG | [AMD FSR 3 documentation](https://gpuopen.com/fidelityfx-super-resolution-3/) describes engine-integrated FG and DX12/Vulkan support. Game integration, API, hardware and algorithm version matter. | Prefer when validated for the requested experience; configure only documented, versioned game keys through its adapter. |
| OptiScaler | [Upstream](https://github.com/optiscaler/OptiScaler) replaces existing upscaler/FG interfaces; experimental OptiFG includes a DX12 path. Its README explicitly warns of anti-cheat bans. GPL-3.0 project; bundled components require their own review. | Research alternative, not a generic safe fallback. No DLL replacement, installation script execution or game patching here. |
| Gamescope scaling | [Valve's compositor](https://github.com/ValveSoftware/gamescope) provides FSR/NIS scaling and frame limiting. Spatial upscaling is not frame generation. | Potential existing-owner capability, not a new compositor or GPU-selection implementation. |

### Release, licensing and provenance

Read-only `git ls-remote` resolved LSFG-VK tag `2.0.0` to commit
`2333707d55b68ddd8066fd95404c3b7d07e00d3a` (annotated tag object
`6a5450f91f7b2b6b1ad852957a111377d37b9023`). The
[pinned license](https://git.lsfg-vk.dev/lsfg-vk/plain/LICENSE.txt?id=2333707d55b68ddd8066fd95404c3b7d07e00d3a)
is **CC BY-NC-ND 4.0**. The [author's migration announcement](https://lsfg-vk.dev/blog/important-changes-to-lsfg-vk/)
distinguishes historical MIT v1, intermediate GPLv3 v2 development, and the current
license; it invites integrators to contact the author. Historical licensing does
not cover later releases automatically.

The [Creative Commons deed](https://creativecommons.org/licenses/by-nc-nd/4.0/)
permits sharing under its conditions, restricts commercial use, and does not
permit distributing adapted material. This is a release-policy blocker for
assuming unrestricted bundling/modification, not a conclusion that merely
generating environment data is forbidden. Re-Gear's
[GPL/community and commercial terms](../LICENSING.md) do not grant rights to
LSFG-VK or the proprietary Lossless Scaling components. Determine the exact
integration/distribution model and obtain an appropriate rights decision before
shipping; user-owned installation and redistributed dependency are separate cases.
No contact with upstream, permission grant, or license compatibility determination
is claimed here.

Sources informed this proposal: PancakeTAS and LSFG-VK contributors (provider
constraints), Valve (runtime/compositor boundaries), AMD GPUOpen (native FG/base
rate guidance), OptiScaler contributors (alternative/anti-cheat risk), and
Creative Commons (license terms). Reuse is research/inspiration only. No upstream
implementation code, assets, DLLs or dependencies were copied or executed.
Per [source attribution](../SOURCE_ATTRIBUTION.md), research credits remain here;
an implemented provider must carry its material credits into third-party notices.
Mutable documentation links were read on the date above; only the stated LSFG-VK
release pin is immutable. Recheck both documentation and selected binaries before
any implementation that depends on them.

### Runtime and launch requirements

[Current installation documentation](https://lsfg-vk.dev/docs/installation/)
requires a purchased/installed Lossless Scaling copy switched to its `lsfg-vk`
Steam branch. The v2 input is `lsfg-vk.dll`, not a guessed path to historical
`Lossless.dll`. Upstream says SteamOS Big Picture has no official convenient
integration, and points to an unofficial Decky plugin. Flatpak requires layer
installation in its runtime too. A host installation therefore does not establish
availability inside Steam's container, for either application bitness.

Vulkan layer discovery/loading is required in addition to configuration. A future
provider must report exact library/manifest version, accessible DLL, architecture,
container visibility and required Vulkan features. Do not install a global layer,
alter loader order globally, or select a GPU as a side effect of profile planning.

The v2 [environment contract](https://lsfg-vk.dev/docs/configuration/environment-variables/)
supports environment-only configuration with `LSFGVK_ENV=1`, a DLL path,
multiplier and pacing mode. `LSFGVK_CONFIG`/`LSFGVK_PROFILE` are a separate
file-based route. An existing `DISABLE_LSFGVK` is an explicit player override;
never erase it automatically. Do not use old `ENABLE_LSFG` instructions.
The configuration pages disagree about `pacing` versus `pacing_mode` in TOML;
resolve against the selected release before generating files.

Steam launch-option mutation is not established by this research. Preserve the
original launch string byte-for-byte, including wrappers, quoting, `%command%`
and user environment. Do not parse arbitrary shell into an invented argv or
overwrite other launch tools. A future supported launch interception seam should
supply opaque original launch data and a reversible per-launch environment overlay;
otherwise give Advisor instructions. No Steam database writer is proposed here.

### API, Proton, compositor and overlays

Native Vulkan is LSFG-VK's interception surface. [DXVK](https://github.com/doitsujin/dxvk)
translates D3D9/10/11 (and D3D8) to Vulkan, while
[vkd3d-proton](https://github.com/HansKristian-Work/vkd3d-proton) supplies Proton's
D3D12 implementation. These make DX11/DX12 paths plausible, **not** proven for
every title. WineD3D/OpenGL, alternative translation paths, mixed APIs and launchers
need separate evidence. Vulkan support alone does not prove required features,
driver behavior or display presentation compatibility.

Validate the actual Proton version, translation layer, game build, driver and
container, not just an AppID. [Valve's Proton guidance](https://partner.steamgames.com/doc/steamhardware/proton)
also makes anti-cheat support a per-title developer concern; Proton support is
not permission for third-party injection. Unknown external-injection eligibility
means no automatic provider. Do not bypass anti-cheat, disguise DLLs, or treat
absence of a crash/ban during one run as permission.

Gamescope session versus nested Gamescope must be separate compatibility cases.
Do not add a nested compositor to the SteamOS session by default. Record where
the limiter acts: limiting the game's real rendering to 30 is not equivalent to
capping the post-FG compositor to 30. Establish the actual presentation chain
and existing limiter owner before composing a base cap and output target.
No Gamescope flag or GPU-selection change is made in this proposal.

[LSFG-VK overlay documentation](https://lsfg-vk.dev/docs/troubleshooting/performance-overlays/)
warns that Steam/MangoHud layer placement changes the observed FPS. Counter
placement and measurement provenance must identify base versus generated output.
Test Steam overlay opening/closing, input, notifications, MangoHud visibility and
frame-time logging together; an FPS overlay showing 60 does not prove smooth 60.
An upstream development branch is not evidence of a released MangoHud integration.

### Pacing, latency, VRR and useful base rate

[Current LSFG-VK pacing documentation](https://lsfg-vk.dev/docs/configuration/pacing-modes/)
lists only `vsync`, with proper pacing tied to output matching the monitor's
actual refresh. It warns of added latency and VRR problems. Consequently, a
60-output plan on a 120 Hz screen is not admitted merely because 60 <= 120.
Do not silently change refresh or disable VRR to make a provider eligible.
Require a validated refresh/presentation policy for the exact display context.

The requested research points (30->60, 45->90, 60->120) are hypotheses, not
defaults. [AMD's FSR 3 guidance](https://gpuopen.com/fidelityfx-super-resolution-3/)
recommends at least 60 FPS before interpolation. Its newer
[version-specific swapchain manual](https://gpuopen.com/manuals/fsr_sdk/techniques/frame-interpolation-swap-chain/)
discusses different lower-rate artifact thresholds for FSR-SRFG 3.1.6 and FSR-FG
4.0.1. Do not transfer any threshold across algorithm, game or provider versions.
30->60 might be acceptable for one tested game but poor for a latency-sensitive one.

FG consumes resources and does not increase the game's simulation/input update
rate. The stable base requirement must hold **with FG overhead included**, not
just in an uncapped baseline benchmark. CPU limitation can make FG attractive but
does not remove responsiveness or GPU-budget constraints. Native/upscaled 55-60
must not trigger FG on a transient dip; only a declared, validated comparison can
justify it. Otherwise retain the simpler profile and explain the shortfall.

## Proposed architecture: composition, not a second profile engine

This section describes the design; it does not change accepted foundation APIs.
Use an optional, versioned performance intent associated with the existing
`GraphicsProfile`/adapter selection. `ExperienceTarget.SMOOTH_60` already exists;
do not add a parallel game identity, config writer, mode observer or running-game
detector. General numeric targets and their persistence need a reviewed schema
extension; absent intent preserves existing behavior.

| Contract | Required information |
| --- | --- |
| Performance intent | Schema version, requested display FPS (or Auto), upscaling/FG policy (`auto`/`off`), optional player minimum base requirement. Auto resolves only within validated catalogue choices. |
| Supplied context | AppID plus game build/schema, existing observed mode, rendering GPU identity separately from display owner, driver/runtime/API, actual refresh, VRR state/range if known, overlay/compositor/limiter stack, authoritative run state. |
| Compatibility record | Provider ID/revision and supported multipliers; exact game/profile/context match; `unknown`, `unsupported`, `experimental`, `validated`; evidence revision/date, measured base distribution, latency/artifact/pacing assessment and exclusions. |
| Provider description | Availability and reason; compatibility and reason separately; config/runtime requirements; known limitations; rights/distribution decision. No installation or probing in the pure resolver. |
| Decision | Existing adapter/profile reference, chosen method, requested and achievable output, required stable base, multiplier, base limiter requirement, restart/next-launch status, diagnostic reasons and unresolved requirements. |

Keep native game FG, external LSFG-VK and future providers behind the same
capability boundary. Their configuration plans differ: native FG uses declared
game-owned keys, external FG proposes a launch overlay. A provider never gains
authority to write files from returning `available`. Native FG detection requires
a versioned adapter mapping and evidence that those keys actually control FG;
an FSR upscaler option or game title match is insufficient. Native provider
preference is configurable and quality-evidence based, not an unconditional rule.

Suggested pure operations are `describe(context)`, `evaluate(intent, evidence)`
and `plan(selected_candidate)`. Side effects remain with the accepted application
and delivery boundaries. Plans carry no executable shell. Multiple provider
candidates use an explicit deterministic preference order with a stable tie-break,
never discovery order or online trial-and-error.

Admission and selection:

1. Validate intent and exact context/evidence binding. Unknown/degraded mode or
   unknown rendering identity selects no automatic change. Unknown VRR only
   excludes options that need VRR evidence; it must not block an otherwise proven
   native profile or ordinary launch.
2. Choose a validated native candidate capable of the requested target. Otherwise
   choose a validated upscaling candidate that can sustain it without FG.
3. Consider validated FG only if its stable base, multiplier, output presentation,
   quality and latency budgets all pass with headroom. Require per-game eligibility,
   provider availability and rights decision. Experimental is not automatic.
4. If none passes, choose the highest validated lower target allowed by the player's
   quality policy; otherwise return Advisor. State the attainable target honestly.
5. Running or ambiguous game state permits advice/queued intent only. Persist an
   intent for next launch and re-resolve fresh context then, not a stale plan.

Portable, Boosted Handheld and TV Docked are distinct evidence placements, using
existing `OperatingMode` values. An eGPU identity does not imply TV output;
Boosted Handheld can render on the eGPU while presenting internally. Moving to TV
does not migrate a running workload. No new hardware reads, subscription/poller,
Auto TDP controller, display mutation or live feedback controller belongs here.

## Failure and reversibility contract

Ordinary game launch must remain possible with original launch data and settings.
Preflight/provider-planning errors return an unchanged original plan plus a
diagnostic. Do not commit a 30-FPS game setting before deciding whether the whole
60-output plan is usable. Any eventual multi-resource apply requires an explicit
transaction/compensation design around the foundation's provenance checks; never
roll back over a player's concurrent edit.

An injected Vulkan layer may fail inside the game process after launch. Removing
an environment overlay beforehand does not solve that. Research has not proven
transparent initializer-failure recovery; this is an unmet production gate for
the user's launch-continuity requirement. Do not claim unconditional fallback,
repeatedly restart a game, or relaunch after ambiguous success. Quarantine the
failing exact provider/context for later launches and offer an original-settings
launch path through a reviewed launcher contract. That path is proposed, not built.

Disable/Stop Managing removes only Re-Gear-owned intent/overrides, preserves the
original launch behavior and follows the existing settings lifecycle. Restore
must distinguish enrolled-original evidence from historical/unverified backups.
Do not overwrite pre-existing player LSFG configuration, wrappers or environment.

## Recommended first proof of concept

The prototype implements an **inert, synthetic** composition test.
Use an unmistakable fixture AppID, a `GameSettingsAdapter` and its existing
`GraphicsProfile`, supplied `OperatingMode`, fake evidence and fake availability.
No real game becomes Managed/validated from these fixtures. All outputs explicitly
say `execution_allowed: false`; no caller can install or execute the proposal.

The fixture trace should demonstrate requested 60, no native/upscaled candidate,
declared stable 30 with overhead, allowed 2x and a 60 Hz presentation case. The
external configuration data can model this documented v2 contract:

```text
provider: lsfg-vk
revision: 2333707d55b68ddd8066fd95404c3b7d07e00d3a
execution_allowed: false
requested_display_fps: 60
required_stable_base_fps: 30       # fixture hypothesis, not a default
multiplier: 2
base_limiter: unresolved; no Gamescope argument generated
proposed_environment_overlay:
  LSFGVK_ENV: "1"
  LSFGVK_DLL_PATH: "<fixture>/lsfg-vk.dll"
  LSFGVK_MULTIPLIER: "2"
  LSFGVK_PACING_MODE: "vsync"
fallback: original launch data and environment exactly
```

Use a fake provider to exercise selection without pretending LSFG availability,
license eligibility or initialization have been validated. The above is configuration
data, not an executable command. A production
plan with its limiter unresolved must be rejected.

Required tests: native and upscaling precedence; unstable/insufficient base;
near-target native performance; unsupported multipliers; refresh mismatch;
stale game/runtime/provider/driver evidence; missing adapter/schema; experimental
and anti-cheat-unknown rejection; all three known modes plus unknown/degraded;
running/unknown run state; provider failure; original wrappers/environment preserved
exactly on disable; user override conflict; deterministic ordering. Test composition
through the existing adapter, not just isolated arithmetic.

## Supervised validation and next gates

After the inert design is reviewed, choose one consenting, non-anti-cheat game
with verifiable schema and cloud-sync ordering. Obtain provider rights and pin
the full runtime. Record equal-scene native/upscaled/FG comparisons: real-frame
interval distribution and sustained lows, output pacing/dropped frames,
end-to-end input latency (or explicitly labelled proxy), motion/UI artifacts,
CPU/GPU utilization, VRAM, power and temperature where available. Record duration,
warm-up, scene, settings, resolution, limiter placement and measurement uncertainty.
Unavailable thermal/power data is unknown, never zero. Do not fabricate numeric
pass thresholds; agree per-game/experience budgets before the supervised trial.

Retest overlays, menus, focus changes and game exit; verify provider disable and
original launch restore. Investigate 30/45/60 base hypotheses independently. Only
then promote an exact compatibility record. A game, provider, driver or presentation
change invalidates matching evidence rather than inheriting blanket support.

Remaining decisions: exact launcher/fallback seam and its owner agreement;
licensing/integration model; one real game's schema and Steam Cloud behavior;
base-limiter ownership; measured latency/pacing budgets; persistence schema and
future UI. Existing snapshot and game-session owners retain their read seams;
this document authorizes no wiring. Public UI remains a simple target and Auto,
with technical details in diagnostics. No UI work is part of this change.

Documentation impact: none (internal research; no delivered player capability).

## Implemented continuation and engine boundary

The Codex continuation composes PR #381 at `6209014` with PR #386 at `27eeda0`.
Claude's engine, semantic mapping, schema and writer files are unchanged. The
resolver's evidence format is now version 2; older records are refused rather
than silently gaining missing display/scaling assertions. There is no persistent
catalogue migration because none has shipped.

`application/performance_plan_bridge.py::preview_performance` calls the pure
resolver and returns a `PerformancePreview`: selected decision, optional existing
`PerformancePlan`, separate output resolution, inert launch data and reasons.
The selected record carries render resolution and at most one explicit upscaler.
Native FG and external FG are distinguished; provider priority is supplied policy,
and the exact-refresh restriction is provider-specific. Native FG keeps a missing
game-key mapping requirement; its opaque reference does not enable anything.
Compositor upscaling remains capability data and cannot produce an engine preview
until an agreed configuration seam exists. Neither path modifies Gamescope.

For the future caller, use the selected AppID, mode and profile target with the
engine's normal validation. Pass the preview's `game_plan` as its existing
`PerformancePlan` argument; do not apply `Decision.profile` directly. That raw
preset is measurement identity and may contain a different cap. The engine's
existing translation receives the resolved **base** cap and render resolution;
provider revision/configuration and output resolution stay with the outer preview.
No caller is wired, and no engine apply is authorized by a preview. The current
engine maps upscaling mode, not arbitrary upscaler identity. The bridge therefore
requires a separately supplied reviewed `game_upscaler_bindings` entry keyed by
the full `ProfileBinding` (adapter, target, profile/schema versions), naming the
same provider as the selected evidence. Missing or mismatched binding gives no game
plan. This assertion must come from the game-adapter owner; the resolver cannot
derive it from a generic QUALITY enum. The full upscaler identity stays in the
preview's decision record. Only synthetic bindings exist in the tests.

Provider object and returned configuration must both match the evidence identity
and revision. Provider errors/opt-outs discard the game proposal as well as the
launch overlay, and disable removes both. Running/unknown game state returns only
a next-launch indication; the eventual queue must persist intent and re-resolve,
not retain an executable stale plan. In-process failure recovery remains unproven.

Hardware-free tests compose target -> existing adapter -> resolver -> provider ->
engine contract -> existing semantic translation, including 30 base / 2x / 60 output
and 4K output / 1080p rendering. They also cover native/upscaling precedence,
provider priority/availability/validation, low or unstable base, display and VRR
mismatches, conflicting upscalers, stale evidence, player overrides, original-launch
preservation, and deferred mode changes. Values are synthetic, never benchmarks.

Upstream v2 environment and pacing pages were rechecked during this continuation.
The [release notes](https://lsfg-vk.dev/blog/release-v2.0.0/) describe Vulkan 1.2,
FP16 optimizations and 32-bit layer support. These are upstream claims, not an
Ally/RDNA3 or Steam Deck certification: verify required features, driver/container,
bitness and per-game budget. Do not infer external-GPU offload or cross-GPU copies
from the Windows app's feature list. The rendering GPU and display owner remain
separate context values, with no lifecycle changes.

Ronnie selected **Final Fantasy VII Remake Intergrade on Steam (1462040)** as the
first future trial. It still resolves to Advisor without a matching adapter and
evidence. Setup remains user-controlled: guide purchase/install and required Linux
component, recheck supplied availability, then distinguish installed from validated.
Next hardware step is a supervised baseline in a repeatable scene, followed by an
explicitly authorized provider comparison only after setup/recovery requirements
are satisfied. No hardware action is triggered by these tests or this document.
