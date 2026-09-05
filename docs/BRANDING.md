# Re-Gear branding and compatibility

The public product name is **Re-Gear**. Use this exact spelling and capitalization
in current UI, product introductions, contributor-facing titles and new prose.
Handheld Dock Mode (HDM) is the former name of the same project, not a separate
application. Dated hardware evidence, quoted logs and historical records retain
their original wording.

## Approved compact UI branding — pending source asset

The approved next header is the supplied cyan outlined Re-Gear R emblem with
white Re-Gear wordmark on transparency, horizontally aligned and compact.
Icon-only surfaces use the emblem alone. No tagline or README artwork belongs
inside the panel. Preserve supplied artwork; do not redraw it in CSS or infer
an official asset from a generated UI concept.

The compact R source file was not attached to the implementation handoff and
is not present in this checkout. The existing asset below remains in use until
the approved SVG or high-resolution transparent PNG is supplied. This is an
outstanding visual acceptance requirement, not a completed branding migration.

## Presentation assets

Current selection (0.3.11): `docs/images/re-gear-decky-white-transparent.png`.
Built-in image editing removed the outer background from the supplied JPEG;
this is a derived asset, not byte-identical original artwork. Actual alpha
was verified. Keep the opaque white inner details and original source JPEG.

Current selection (0.3.5): `docs/images/re-gear-decky-black-gear.jpg`,
the user's unmodified black gear/white background image. It supersedes the
0.3.4 icon below for both Decky list and header. All prior originals remain.
The JPEG's white background is retained; it is not a transparent asset.

The 0.3.4 icon candidate uses the user-supplied, unmodified
`docs/images/re-gear-decky-monochrome.jpg` for the Decky list and panel header.
The earlier PNG artwork is retained. The JPEG is embedded locally in the bundle.
As of 0.3.33, the Decky manifest and exported frontend display name are
`Re-Gear`, so Quick Access uses the current product name. The installed folder,
archive root, RPC/state keys, helper paths, and package names remain unchanged.
This is a scoped display-label migration, not a stored-state migration.

`src/branding.ts` owns the UI display name. `docs/images/re-gear-icon.png` is the
original detailed README artwork; `docs/images/re-gear-decky-icon.png` is the
original simpler Decky artwork. Both are maintainer-approved and retained.
Do not redraw or silently replace the supplied image. Generated `dist` assets
must be built with the runtime and UI from the same clean source revision.

## Keep these identifiers stable

This rebrand does not migrate installed data or change runtime behavior:

| Surface | Compatibility value retained |
| --- | --- |
| Decky visible manifest label | `Re-Gear` |
| Installed plugin/archive directory | `HandheldDockMode` |
| npm and Python distribution name | `handheld-dock-mode-steamos` |
| Python package and diagnostic command | `hdm`, `hdm-diagnose` |
| Helper/state paths | existing `handheld-dock-mode` paths |
| Settings, managed markers and diagnostic codes | existing keys and HDM identifiers |

Decky's plugin list and panel display Re-Gear. Installer internals and technical
logs may still show compatibility identifiers. Changing the installed folder,
package names, RPC/state keys, or helper paths remains outside this label change.

## GitHub and checkout rename — pending maintainer action

The maintainer will rename the GitHub repository when ready. Do not change the
remote URL, badges, repository links, Wiki publication target, checkout folder
or worktree paths in advance. No new repository slug has been assumed here.
After the maintainer supplies the final name, update links and remote mappings
in a focused follow-up and verify redirects, CI and Wiki access. Keep existing
Wiki page filenames/slugs stable unless links are migrated together.

Local source edits do not publish the GitHub README/Wiki, rename the repository,
or install a new build on the Ally. The product name change adds no hardware
support or live-removal claim, and does not change licensing terms.
