# Release-candidate pipeline

## Candidate availability and archive preservation

GitHub has published development candidates, including v0.3.57 and v0.3.58.
Their release titles identify the development status; publication is not Decky
Store/channel registration or general hardware support. The maintainer reports only his own legacy test installs; their controlled
cutover and rollback are covered in [the identity migration plan](IDENTITY_MIGRATION_PLAN.md).

For supervised staging on the recorded test handheld, the established ZIP
location is `/home/deck/`. Follow [release coordination](CHAT_COORDINATION.md):
plain immutable archive names, exact provenance/checksums, and no clobbering.
Do not delete historical artifacts as routine pre-staging cleanup. Any separately
authorized cleanup must preserve the required rollback artifacts and evidence.

Re-Gear has a local, publish-ready candidate contract, not an automated release
channel. `package.json` is the semantic-version source. The pipeline rejects a
non-semantic version, a mismatched Python package version, a ZIP whose filename
or embedded package/build metadata disagree, or an invalid source revision.

From a clean validated checkout:

```text
pnpm build
python scripts/check_plugin_package.py .
python scripts/build_plugin.py
python scripts/prepare_release_candidate.py out/Re-Gear-<version>.zip \
  --output out/release-candidate.json \
  --notes-template out/RELEASE_NOTES_TEMPLATE.md
```

The generated JSON records the exact version, full build revision, archive
filename, SHA-256, required release-note fields, and explicit non-publication
status. The Markdown template is the maintainer's starting point for player
changes, known limits, validation evidence, and the final manual publication
record. It contains no device identifier, credential, or secret.

CI repeats this local verification and retains the ZIP, checksum, candidate
manifest, and notes template as a short-lived controlled validation artifact.
It has read-only repository permissions and does not publish a GitHub Release,
contact Decky, register a store channel, deploy, or use publication secrets.

## Candidate versioning

### Development and production profiles

`contracts/build-profiles.json` names two build profiles. Development preserves
all existing development features and their safety checks. Production enables
eGPU connection, Safe Disconnect, brightness and volume. Its command center has
one eGPU tab, live connection status, the plain disconnect action and the existing
left-side brightness/volume sliders. Right-side quick buttons, other tabs,
customization and combined sleep/shutdown actions are hidden. Sliders reuse native
Steam readings and setters; missing capabilities remain unavailable. The backend also
rejects unapproved public mutation calls before dispatch. Internal connection,
sleep protection, pending-operation completion and recovery remain active.
Production connection details and the connection popup are observational. Manual
TV/recovery/setup controls, preference changes and development game-relaunch
requests are not admitted. Existing automatic connection and recovery continue
under their saved consent and lifecycle rules. An unavailable Safe Disconnect
card stays visible without dispatching; pending disconnect status recovery is
independent of starting a new action.

Build and package the same selected profile (PowerShell example):

```powershell
$env:REGEAR_BUILD_PROFILE = "production"
pnpm build
python scripts/build_plugin.py --profile production
```

Omitting the environment variable and package option selects development.
Packaging checks the generated frontend profile stamp and exact bundle SHA-256
before reserving a version. It generates the matching immutable backend profile
inside the archive without modifying the source checkout. A stale bundle or
mismatched profile is rejected. New `build_profile.json` metadata records the
profile, approved feature list, contract digest and bundle digest; the existing
`build_info.json` schema remains unchanged. Candidate preparation checks the
frontend bytes and backend configuration against that record. Historical
archives remain readable by `verify_validation_artifact.py`, but cannot be
retroactively relabeled as new profiled candidates.

Push and pull-request CI runs build and test both profiles in separate jobs.
Manual **Run workflow** selects one profile. Artifact names include profile,
source SHA, run ID and attempt; embedded ZIP names remain plain
`Re-Gear-X.Y.Z.zip`. These are run-scoped validation outputs, not globally
version-reserved public releases. CI retains read-only repository permissions
and does not publish, install or register a channel.

Remaining delivery steps, in order:

1. Complete exact-candidate UI/backend review and supervised hardware acceptance
   for the production feature set, including retained-state recovery and rollback.
2. Add durable, serialized GitHub version reservations for distributed candidates
   (local Git reservations alone cannot coordinate fresh CI clones).
3. Retain the validated production candidate and promote those exact bytes through
   a protected GA publication job. Do not rebuild at promotion or mark a
   development ZIP stable. Decky distribution remains a separate reviewed
   integration.

Use one active plugin installation per device. Profile metadata is build identity,
not permission to bypass hardware, release or installation gates.

New player-facing archives use `Re-Gear-<version>.zip`. The internal archive
folder and new installed directory are `Re-Gear`; the visible manifest label
is also `Re-Gear`. Historical read-only validation accepts either single old
or new root; new release candidates require Re-Gear naming and root. Existing
legacy test installations require the [supervised cutover](IDENTITY_CUTOVER.md)
before new deployment. Persistent settings/recovery paths remain unchanged.

Version 0.3.0 starts the combined dashboard and event-triggered docking candidate.
Bump the patch version for subsequent fix candidates (0.3.1, 0.3.2); bump the minor
version for new feature milestones (0.4.0). Update package.json and pyproject.toml
together before packaging. Do not reuse a version for changed distributed code.
Rebuilding identical source may retain its version. The embedded source revision
and SHA-256 still identify the exact artifact. A version bump does not certify
hardware behavior or authorize installation/publication.

## Manual publication gate

Only after a maintainer has reviewed the candidate, completed the applicable
hardware/certification gates, and finalized release notes may they manually:

1. Create a GitHub Release and attach the exact verified ZIP and SHA-256.
2. Record the Release URL and evidence status in the finalized notes.
3. Complete Decky Store/channel registration and its separate review process.

Decky Store/channel registration is not implemented by this repository or CI.
Until it is explicitly completed, every candidate remains a controlled
validation artifact and not an end-user release.
