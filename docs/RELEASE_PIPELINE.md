# Release-candidate pipeline

## Ally ZIP location and cleanup

Every Re-Gear/HDM ZIP transferred to the Ally must be placed directly in
`/home/deck/`. Do not stage ZIP builds in `/home/deck/Downloads/`.

Before transferring a new ZIP, verify the currently installed Re-Gear version
and identify the newest candidate. Then delete superseded Re-Gear/HDM ZIP builds
from both `/home/deck/` and `/home/deck/Downloads/`. Keep the newest required
candidate only. Setup scripts, public keys, and other non-ZIP files may remain
in Downloads when their documented setup flow requires it.

HDM has a local, publish-ready candidate contract, not an automated release
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

New player-facing archives use `Re-Gear-<version>.zip`. The internal archive
folder and installed Decky identity remain `HandheldDockMode` / `Handheld Dock
Mode` to preserve upgrades and settings. Historical rollback validation accepts
both archive prefixes; new release candidates require Re-Gear naming.

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
