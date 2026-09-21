> **Historical checkpoint.** Retained from source `9421c6f`; statements describe that dated session, not current availability.

# Hardware coupling and privacy audit — 2026-09-02

Baseline: `8d96b9c398f77c26ebbef50b5fb1c7d402695169` on local `main`.
The worktree was clean when the audit began. A separate documentation/governance
workstream appeared during the audit; its files are not included as changes from
this audit and must not be overwritten or staged accidentally.

This report covers tracked source, frontend, generated frontend output, tests,
fixtures, scripts, packaging, CI, documentation, image metadata, ignored build
outputs, and practical Git-history searches. Exact profile knowledge is not a
defect merely because it names the first certified hardware.

## Summary

| Severity | Count | Meaning |
|---|---:|---|
| P0 | 2 | Current or historical maintainer-environment disclosure |
| P1 | 4 | Runtime architecture blocks safe addition of another profile |
| P2 | 6 | Incremental coupling/configuration issue |
| P3 | 2 | Low-risk hygiene/generalization cleanup |
| P4 | 4 | Intentional profile, fixture, platform, or attribution data |

No private key, password, API token, bearer token, webhook secret, SSH key,
Wi-Fi identifier, MAC address, hardware serial, raw USB4 unique ID, raw EDID,
Steam account ID, or credential file was found in tracked HEAD. Commit metadata
uses a GitHub no-reply address. The tracked JPEG contains only technical image
properties; no author, location, camera, or GPS metadata was found.

## Findings

### PRIV-001 — real local checkout path in current documentation

- **Location:** `docs/OPERATOR_HANDOFF.md:9`
- **Category / severity:** G — Privacy / Environment Leak, **P0**
- **Current behavior:** Names the maintainer's Windows profile and local project
  directory.
- **Why it matters:** It is unnecessary for operation and directly identifies a
  development environment.
- **Recommended action:** Replace it with a repository-relative command or a
  generic `C:\path\to\...` example.
- **Status:** Fixed in `3f0e9fa`; the handoff now resolves the checkout root at
  runtime instead of naming a Windows profile.

### PRIV-002 — private LAN address and local path remain in Git history

- **Location:** historical `docs/OPERATOR_HANDOFF.md`, introduced by `b5bf6cb`
  and changed by later handoff commits
- **Category / severity:** G — Privacy / Environment Leak, **P0**
- **Current behavior:** HEAD no longer contains the LAN address, but reachable
  commits contain an exact private-network target and the real local checkout
  path.
- **Why it matters:** Removing the value from HEAD does not remove it from public
  Git history.
- **Recommended action:** Treat the address as exposed network metadata. It is
  not a credential, so rotation is not applicable. Decide separately whether to
  rewrite published history with `git filter-repo`, coordinate force-pushes and
  clone replacement, and invalidate stale documentation links. Do not rewrite
  history automatically.
- **Status:** Requires explicit maintainer decision.

### HC-001 — central discovery recognizes only Ally X and GPD G1

- **Location:** `backend/hdm/adapters/steamos/discovery.py`
- **Category / severity:** C — Architectural Coupling, **P1**
- **Current behavior:** Imports the Ally matcher and G1 matcher directly; GPU
  role, link health, client scanning, sleep state, blockers, and combination
  support are built around the one G1 match object.
- **Why it matters:** Adding a runtime catalog entry is insufficient; another
  host/eGPU requires edits throughout central discovery.
- **Recommended action:** Introduce one narrow observed-profile result consumed
  by discovery. Keep the current exact matchers as the first implementations and
  prove the seam with one synthetic alternate profile.
- **Status:** Open; coordinate with the runtime hardware-journey owner.

### HC-002 — sleep protection is device-name/topology wired, not capability wired

- **Location:** `backend/hdm/adapters/steamos/sleep_inhibitor.py`,
  `backend/hdm/adapters/steamos/discovery.py`, `main.py`
- **Category / severity:** C — Architectural Coupling, **P1**
- **Current behavior:** The production presence observer knows only exact Ally X
  plus G1, while snapshot sleep requirement is derived from G1 detection.
- **Why it matters:** A future profile with the same unsafe sleep behavior would
  not automatically receive the guard, and two paths can disagree about whether
  protection is required.
- **Recommended action:** Resolve sleep behavior from the exact profile result,
  then feed one capability-neutral presence contract to the existing pure
  policy. Preserve fail-closed behavior for incomplete G1 evidence.
- **Status:** Open; safety-critical and requires coordinated targeted tests.

### HC-003 — internal GPU/panel classification assumes boot VGA and eDP

- **Location:** `backend/hdm/adapters/steamos/discovery.py:48-62`,
  `backend/hdm/adapters/steamos/drm.py:55-57`
- **Category / severity:** B/C — Runtime Detection / Architectural Coupling,
  **P1**
- **Current behavior:** `boot_vga` defines the internal GPU and only `eDP-*`
  connectors are internal. The Gamescope wrapper already recognizes eDP, DSI,
  and LVDS, so the two mechanisms disagree.
- **Why it matters:** Other handheld display buses or boot topologies remain
  Unknown or can be misclassified.
- **Recommended action:** Centralize connector-kind detection for eDP/DSI/LVDS
  and make host-profile GPU-role evidence explicit. Never fall back to DRM card
  order.
- **Status:** Open.

### HC-004 — launch and render mechanisms are constructed only for Ally/G1/AMD

- **Location:** `backend/hdm/adapters/steamos/game_render_binding.py`,
  `backend/hdm/delivery/gamescope_wrapper.py`, `main.py:508-525`
- **Category / severity:** C — Architectural Coupling, **P1**
- **Current behavior:** Production wiring directly constructs Ally-internal and
  G1-external resolvers; the launch shim re-matches only G1.
- **Why it matters:** A new catalog profile cannot reach the transition mechanism
  without changing production composition.
- **Recommended action:** Select a profile-owned binding resolver after exact
  runtime resolution. Keep G1 revalidation and its AMD requirements intact.
- **Status:** Open; coordinate with the runtime hardware-journey owner.

### HC-005 — DRM activity adapter requires `amdgpu`

- **Location:** `backend/hdm/adapters/drm_engine_activity.py:146`
- **Category / severity:** C — Architectural Coupling, **P2**
- **Current behavior:** Rejects otherwise valid fdinfo evidence unless the
  driver string is `amdgpu`.
- **Why it matters:** NVIDIA or another DRM driver cannot use the activity
  contract even if its evidence shape is supported.
- **Recommended action:** Make the expected driver part of the private resolved
  render binding or provide a driver-specific adapter. Do not weaken the G1 AMD
  check.
- **Status:** Open.

### HC-006 — player UI names G1 in generic workflow text

- **Location:** `src/refresh-policy.ts:96,103`, `src/index.tsx:92,1319`
- **Category / severity:** C/F — Architectural Coupling / Example, **P2**
- **Current behavior:** Generic readiness and TV-switch UI says G1, and a local
  preference key embeds the model name.
- **Why it matters:** The product contract says player-facing workflow language
  is handheld/eGPU/external-display based.
- **Recommended action:** Use `eGPU` in workflow copy and a model-neutral key;
  retain model names in certification and compatibility surfaces. If the key is
  renamed, read the legacy key for migration.
- **Status:** Fixed in `8a8cb5f`; player copy is generic and the legacy key is
  read only for preference migration.

### HC-007 — support profile check compares one literal host ID

- **Location:** `backend/hdm/application/support_bundle.py:306-307`
- **Category / severity:** C — Architectural Coupling, **P2**
- **Current behavior:** `host.certified` passes only for
  `asus-rog-ally-x` even if a future exact host profile is certified.
- **Why it matters:** Support output would report an incorrect failure for a new
  profile despite valid runtime evidence.
- **Recommended action:** Report generic exact-profile resolution or consume the
  resolved hardware-profile diagnostics instead of a literal ID.
- **Status:** Fixed in `8a8cb5f`; a synthetic alternate exact-host regression
  test proves that the check no longer depends on the Ally profile ID.

### ENV-001 — signed updater and capture payload fix the `deck` home

- **Location:** `scripts/ally_hdm_deploy_helper.py:25-26`,
  `scripts/install_ally_deploy_helper.sh:8-19`,
  `scripts/remote_capture_payload.py:20`
- **Category / severity:** A/F — Legitimate First-profile Tooling / Configuration,
  **P2**
- **Current behavior:** The general PowerShell deploy script accepts user/host/
  port/key inputs, but signed-helper installation and remote capture use
  `/home/deck` and a `deck` sudoers identity.
- **Why it matters:** Another SteamOS account layout requires editing committed
  scripts. These are not personal leaks: `deck` is a platform account used in
  first-profile tooling.
- **Recommended action:** Keep the Ally-named tool if desired, but derive the
  home/plugin root during installation and write a root-owned fixed config for
  the privileged helper. Do not accept arbitrary paths at privileged runtime.
- **Status:** Open; not required before another real target exists.

### DISP-001 — active-display correlation assumes one matching output

- **Location:** `backend/hdm/adapters/steamos/discovery.py:340-387`
- **Category / severity:** B — Runtime Capability Detection, **P2**
- **Current behavior:** Marks an active connector only when exactly one connected
  connector matches Gamescope output preferences.
- **Why it matters:** Multiple active outputs remain Unknown even when their
  individual names are observed. This is fail-closed and correctly avoids
  treating `connected` as active, but it limits multi-display support.
- **Recommended action:** Model active outputs as a set and reject only ambiguous
  duplicate connector identities.
- **Status:** Open.

### DOMAIN-001 — generic recovery facts use G1 names

- **Location:** `backend/hdm/domain/interrupted_docked_sleep.py`
- **Category / severity:** C — Architectural Coupling, **P2**
- **Current behavior:** Generic absence evidence and fact names use `g1`.
- **Why it matters:** Pure workflow policy should describe the bound eGPU, not a
  product model.
- **Recommended action:** Rename during the next coordinated schema/code update;
  preserve serialized compatibility if any value is externally persisted.
- **Status:** Open; no behavior change needed now.

### TEST-001 — privacy tests use maintainer-like names and RFC1918 addresses

- **Location:** `tests/test_support_bundle.py`, `tests/test_remote_capture.py`,
  `tests/test_stage_decky_update.py`
- **Category / severity:** D/F — Test Fixture / Placeholder, **P3**
- **Current behavior:** Intentional redaction tests used a maintainer-like
  placeholder name and RFC 1918 addresses.
- **Why it matters:** They are test data, not proven disclosures, but they look
  like captured maintainer data and obscure history/privacy review.
- **Recommended action:** Use `FixtureUser` and RFC 5737 documentation addresses
  such as `192.0.2.*`.
- **Status:** Fixed across `3f0e9fa` and `8a8cb5f`; fixtures now use
  `FixtureUser` and RFC 5737 documentation addresses.

### HYGIENE-001 — secret-file ignores were incomplete at baseline

- **Location:** `.gitignore`
- **Category / severity:** F — Repository Hygiene, **P3**
- **Current behavior:** Baseline ignored build/state data but not common `.env`,
  PEM, key, or PKCS#12 files.
- **Why it matters:** No such file is tracked, but a future local credential is
  easier to stage accidentally.
- **Recommended action:** Ignore common secret-file patterns while allowing any
  intentionally reviewed public test key by explicit exception.
- **Status:** Fixed by the separate governance workstream before this report was
  committed; the audit did not overwrite that change.

## Intentional hardware-specific data retained

The following are **P4** and should remain unless their underlying evidence
changes:

1. Exact Ally X DMI tuples in `profiles/ally_x.py`: legitimate host profile.
2. Exact G1 GPU/audio/bridge/xHCI/USB4/driver topology in
   `profiles/gpd_g1.py`: legitimate profile and quirk knowledge.
3. Ally X + GPD G1 certification tables and dated validation records: truthful
   compatibility evidence, not a universal claim.
4. Named card, connector, PCI, PID, and G1 fixtures: deterministic test data.
   Production enumerates runtime state and does not hard-code those fixture
   addresses. Raw EDID and USB4 identities are not committed; runtime hashes are
   backend-only and stripped from public/support projections.

SteamOS paths under `/sys`, `/proc`, `/run`, `/dev`, and the root-owned
`/var/lib/handheld-dock-mode` state root are platform-adapter/install contracts,
not maintainer paths. The copyright holder, package author, GitHub repository
owner, and GitHub no-reply commit identity are intentional attribution, not an
accidental environment leak.

## Secret and history disposition

- **Credential rotation:** not indicated; no credential material was found.
- **History cleanup:** optional but required if the goal is literally zero
  retained maintainer network/path metadata in reachable commits. This is a
  separate destructive repository operation and was not performed.
- **Ignored local artifacts:** `out/` is ignored and contains local build/test
  evidence. It is not checked in. Before publishing an archive manually, use
  the existing deterministic package allowlist rather than uploading the whole
  directory.

## Refactor boundary

P0 HEAD cleanup and small capability-neutral P2 corrections are safe in this
audit. HC-001 through HC-004 touch the safety-critical runtime path and should be
implemented as independently tested seams by the hardware-journey owner, not as
one abstraction rewrite. No hardware action, deployment, profile promotion, or
support claim is authorized by this report.
