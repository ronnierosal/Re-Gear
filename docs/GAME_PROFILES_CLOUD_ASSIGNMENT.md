# Automatic Per-Game Graphics Profiles: cloud Claude assignment

Status: assignment prepared, cloud execution/acceptance not yet observed.
Primary: `codex-game-profiles-01a0c956`, Ronnie-designated stream
`primary-game-profiles`. Starting base: `e5d6b247f790d9befadb4a9cd723f3474d1f6b8f`.
This is a development contract, not a shipped capability or approved final architecture.

## Ownership and first delivery

Cloud Claude owns initial research, short architecture proposal, and bulk first-adapter
implementation after acknowledging this assignment on the canonical GitHub issue.
Use branch `claude/game-profiles-first-adapter` and one linked draft PR. Record the
cloud session identity, exact base/head and intended paths before implementation.
Refresh policy and search existing branches/PRs before creating duplicates.
Codex owns coordination and read-only review; it will not duplicate these edits.
Cloud Claude has no local hub access and is not represented as locally registered.

First commit a short architecture/research document before large implementation.
Review SteamTinkerLaunch, SteamOS per-game configuration/profile managers and
Proton-aware launch tools using primary sources. Record pinned source revisions,
authors, licenses and reuse type. Cover AppID discovery, multiple Steam libraries,
native paths, compatdata prefixes, backup/restore, launch hooks, Steam Cloud
ordering/conflicts and games rewriting settings on exit. Choose one real game's
documented text schema with synthetic fixtures; if evidence is insufficient,
keep it Advisor and explicitly label a synthetic mechanism demonstration.
No real config reads/writes are needed for this milestone.

Re-Gear is GPL-3.0-or-later, but this assignment does not authorize copying GPL
or other third-party code. Record any proposed reuse for an explicit license
decision; AI rewriting is not proof of independent provenance. Credit material
inspiration under SOURCE_ATTRIBUTION.md when delivering implementation.

## Architecture proposal to establish

- `GameProfile`: versioned semantic Portable, Boosted Handheld and TV Docked intent;
  no power/display/GPU commands or unsupported performance promises.
- `GameSettingsAdapter`: game/AppID/schema-specific translation and owned-key list.
- `ConfigLocator`: bounded discovery under injected Steam-library/user roots;
  native/Proton variants, ambiguity and unsupported shortcuts remain explicit.
- `ProfileResolver`: consume supplied stable observed mode and player preferences;
  reuse `domain/mode_profiles.py` vocabulary without editing its owner contracts.
- `BackupManager`: bounded/versioned original bytes plus integrity and management
  provenance; repeated apply must not replace the original baseline.
- `ProfileValidator`: schema/version/signature, allowed values, path and ownership
  validation before any mutation and readback validation afterward.
- `ApplyResult`: applied/unchanged/advisor/deferred/conflict/failure outcomes,
  clear reason, restoration availability, and launch always allowed.
- Support levels: 0 Unknown, 1 Advisor, 2 Managed. Managed requires an explicitly
  supported schema and all operation evidence; fixture success is not real-game proof.

Keep pure policy in domain, filesystem work in adapters and coordination in
application/ports, consistent with the repository architecture. Proposed new
game_profiles modules/tests/fixtures must be listed in the draft PR; do not edit
main.py, frontend, shared mode/runtime/Steam adapters or another owner's files.

The launch boundary is an injected, bounded pre-launch operation in fixtures only.
No production hook, polling loop, launch delay, process kill/restart or running-game
write. Running or unknown state defers mutation while allowing play with existing
settings. Changed mode during play is a next-launch availability result.
Steam Cloud ordering remains an explicit unresolved production-integration gate;
filesystem atomicity cannot prove cloud or game cooperation.

## Player-data contract and acceptance checklist

- [ ] Demonstrate fake Steam AppID/library detection and fake Proton prefix/native
  path resolution using temporary directories; reject ambiguous/outside-root targets.
- [ ] Discover, read and validate one supported text schema; unknown/missing/malformed
  schema, version or signature stays Unknown/Advisor with unchanged original bytes.
- [ ] Save original bytes and metadata before modification; bound backup count/size
  without deleting the only usable restoration baseline. Define full-store behavior.
- [ ] Modify only adapter-owned keys; preserve unrelated settings, comments/encoding
  where supported, and reject unsupported serialization rather than guessing.
- [ ] Temp-write in the target filesystem, validate, atomic replace, then verify.
  Cover failed/interrupted writes, permissions, read-only files and verification
  failure. Explain crash boundaries and recoverability without claiming impossible
  atomicity across config and backup files. No partial/truncated original.
- [ ] Apply Portable, verify, repeat idempotently, apply TV Docked, verify and restore;
  assert byte-exact restoration when unchanged and explicit semantic comparisons.
- [ ] Test Boosted Handheld translation without inventing measured optimal settings.
- [ ] Detect intentional player edits against last-managed content before apply or
  restore; preserve their newer choice and return conflict. Recheck before replace;
  document external-writer race limits. Never silently rebaseline or overwrite.
- [ ] Test missing/corrupt backups, profile-version mismatch and game-update/schema
  changes. Failed restoration leaves current settings intact and launch allowed.
- [ ] Expose Restore My Settings and define future Stop Managing/Never Manage
  semantics (opt-out plus separately guarded restore, never blind overwrite).
- [ ] Reserve Automatic, target FPS, resolution-auto and Balanced/Smooth/Quality as
  future semantic extensions; no large UI/catalog or additional game adapters.
- [ ] Failure, unsupported state and restore conflict never prevent play; test the
  caller-visible launch decision through the real fixture application entry point.

## Scope overlaps and integration

Live owner inspection on 2026-09-22 found:

| Scope | Owner | Boundary |
| --- | --- | --- |
| Offline Game Mode | codex-offline-primary-01a09b44 | AppID and launch-state read contract; no sync-controller edits (PR #332) |
| eGPU | codex-egpu-review-20260911 | stable observed mode input only; no lifecycle, GPU enumeration or routing changes |
| Auto TDP | codex-auto-tdp-01a097b0-ac26-7e92-915c-b5c68d2a1b13 | preserve Steam-resolution feasibility and manual per-game settings-guide proposals |

Primary game profiles drives only its own integration. Existing scopes retain
their owners. Shared-contract changes require recorded agreement and one driver
with affected owners accepting the same exact head/base. Pending agreement does
not prevent isolated fixture implementation. No binary patching, injection,
anti-cheat bypass, protected-data writes, scraped optimized presets, G1 experiments,
USB4 changes, Gamescope restart, controller/Auto TDP changes or UI redesign.

Owner replies received during setup clarify the read seams. Paths below use the
current `backend/regear` namespace (the replies used historical `backend/hdm`).
The eGPU primary identifies `api.DiagnosticsApi.get_snapshot()` through
`SnapshotService.observe()` and `report_to_public_dict()` as the read-only source
of `inference.mode`. Inject a narrow provider for those categorical values.
Do not use Decky's `Plugin.get_snapshot()` as a new observer: its wrapper also
records topology/readiness and can initiate lifecycle work. Do not reinterpret
`PlacementState`; unknown/degraded selects no automatic profile.

The Offline primary identifies `ports/game_session.py::GameSessionObservationPort`
and `domain/game_session.py` for exact active AppID/runtime evidence, with semantic
generation and per-observation sample identity. Public snapshots expose game state,
not AppID. Focused library tiles and Offline SelectedGame are not active identity.
Exact RUNNING identity permits read-only preview only, never a settings write.
Pre-launch mutation needs an independently identified launch target and known-idle
evidence; IDLE itself supplies no active AppID. The fake library/explicit fixture
target supplies identity in this milestone. Unknown/raced runtime defers writes.
No new production launch identity or privacy contract is approved here.

## GitHub handoff and local transition

The draft PR must contain scope/out-of-scope, base and exact head SHA, changed
files, architecture decisions, focused test commands/results, known limitations,
provenance/licenses, remaining work and `Documentation impact: ...`.
Commit all delivered work; keep the cloud branch/PR. Chat text and uncommitted
files are not a handoff. Architecture review and the first adapter are the stop
point; no release/install/real-game or hardware validation is implied.

When Claude moves local, register its own stable hub identity and reconcile this
issue/PR with one implementation task/claim. A transfer to Codex requires explicit
agreement at a committed exact head, primary sequencing acknowledgement and
accepted hub transfer. Codex reviews before narrow refinements.

During development run focused regression tests and applicable architecture checks.
Before integration refresh origin/main and ownership, independently review the
combined candidate and run exact-head preflight, golden behaviors, architecture,
full backend unittest discovery, compileall and required CI per current policy.
Record rollback and distinguish source/tests, merge, package, installation and
real-game/hardware evidence. No integration acceptance is granted by this document.
