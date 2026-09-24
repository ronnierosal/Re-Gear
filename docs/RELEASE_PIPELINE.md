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

### Development and production profile foundation

`contracts/build-profiles.json` names the two build profiles. Current packaging
defaults to `development`; `python scripts/build_plugin.py --profile development`
is the explicit equivalent. It preserves the existing development feature surface,
including experimental functionality and its existing safety checks. This first
step does not introduce feature filtering or change runtime behavior.

New archives include `build_profile.json` with the selected profile, feature
policy and canonical contract SHA-256. The existing `build_info.json` schema is
unchanged. Candidate records and release-note templates carry the profile as well
as the archive checksum and exact source revision. Preparing a new candidate now
requires this profile record; old archives remain readable by the historical
`verify_validation_artifact.py` verifier and are never retroactively relabeled.

`production` reserves the intended `stable_allowlist` policy. Packaging it exits
with `release.production_runtime_enforcement_pending` **before reserving a version
or creating an archive**. The runtime does not yet enforce an approved feature
allowlist at UI, RPC, startup and automatic entry points. A manifest switch cannot
make that runtime production-ready. No existing feature is declared GA-ready by
this foundation, and no new gate applies to ordinary development packaging.

The CI workflow also has a manual **Run workflow** entry with a profile choice.
Push and pull-request runs continue to select development. Manual development
runs execute the same complete CI gates and upload a validation artifact;
production requests report the explicit pending-enforcement error immediately.
Artifact names include profile, source SHA, run ID and attempt; embedded ZIP names
remain plain `Re-Gear-X.Y.Z.zip`. CI artifacts are run-scoped validation outputs,
not globally version-reserved public releases. The job retains read-only repository
permissions and does not publish, install or register a channel.

Remaining delivery steps, in order:

1. Agree the feature inventory/production allowlist with the UI and affected
   backend owners, including exact supported hardware evidence.
2. Enforce that policy through UI, RPC and automatic paths while preserving
   recovery of retained development state; test both profiles and navigation.
3. Add durable, serialized GitHub version reservations for distributed candidates
   (local Git reservations alone cannot coordinate fresh CI clones).
4. Retain and validate the exact production candidate, including supervised
   hardware acceptance and settings/downgrade/rollback coverage.
5. Promote those exact bytes through a protected GA publication job. Do not rebuild
   at promotion or mark a development ZIP stable. Decky distribution remains a
   separate reviewed integration.

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
