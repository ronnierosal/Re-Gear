# Community report helper

`scripts/community_report.py` is a standalone Python 3 helper for SteamOS/Linux
players responding to [discussion #91](https://github.com/ronnierosal/Re-Gear/discussions/91).
It uses the installed, trusted plugin's existing read-only `regear.cli` described in
[Diagnostics](DIAGNOSTICS.md). It does not import the privileged Decky plugin
entry point, install anything, change services, run a hardware test, or upload.
For previously published installations it recognizes the legacy `hdm.cli`
namespace too. A tree containing both namespaces is refused as ambiguous.

## Run and share

1. Download the helper from the exact reviewed commit linked in discussion #91.
   Save it as `community_report.py`; do not run a command that pipes a download
   straight into a shell. The discussion includes the SHA-256 for verification.
2. Open a terminal in the folder containing that file on the handheld and run:

   ```sh
   python3 community_report.py
   ```

3. Read the report printed in the terminal. Type `save` only if you want to save
   those exact JSON bytes in the current folder. Any other answer cancels.
4. Review the saved `Re-Gear-community-report-<timestamp>.json`, attach it to your
   discussion comment, and add model names, what you tried, expected/actual
   results, and whether picture, controls and audio worked afterward.

Run without sudo. The helper looks only in your own
`~/homebrew/plugins/Re-Gear`. If it cannot find the plugin, it still
previews available OS information with `plugin_not_found`. For a different
installation location, a maintainer can confirm the directory; then use
`python3 community_report.py --plugin-root "/path/to/your/trusted/plugin"`.
Do not point it at an unknown downloaded source tree: the helper executes that
tree's diagnostic module. It does not download collector code itself.

## Evidence and privacy limits

- Automatic fields: selected plugin build metadata, allowlisted distribution and
  numeric OS/kernel version, game state, GPU roles/presence/render selection,
  and connected/active display roles from one CLI observation.
- Build metadata describes files, not proof of the running Decky version. Missing
  or unsupported metadata stays unknown; no fallback release version is guessed.
- Hardware model names, Decky version, connection arrangement, actions,
  repeatability, and player-observed results still require user input. The
  helper does not read USB serials or EDID to guess models.
- Arbitrary collector text, names, IDs, paths, environment, errors, and raw logs
  are omitted. Strings from the snapshot pass only fixed categorical allowlists.
  Custom kernel suffixes and nonnumeric version labels are omitted.
- Collection is bounded to 30 seconds and 256 KiB. Failure codes carry no raw
  exception text. On timeout it stops only its own diagnostic child.
- Permission-limited fields remain null/unknown; empty arrays on a failed
  collection do not prove hardware absence. This separate CLI has no in-memory
  Decky history. Prefer the built-in reviewed support export when available.
- Saving requires an interactive `save` response after preview, uses exclusive
  creation, and never overwrites an existing report. Noninteractive runs only
  print a preview. Reports stay local until the player uploads them.
- No result grants physical-unplug clearance or hardware certification. Do not
  reproduce a dangerous failure for a report.

## Validation and delivery

Tracked in issue #94. Focused tests cover allowlisting, malformed fields, metadata,
version redaction, consent, no-clobber saves, missing installs, and Linux child
failure/timeout/output limits. The helper is separately downloadable; it is not
automatically part of existing Decky ZIPs. Check the PR for the exact test/platform
results before recommending it. Hardware collection remains unvalidated until a
real read-only player run is reviewed. Follow [Support bundle](SUPPORT_BUNDLE.md)
and [Help Improve Re-Gear](../wiki/Help-Improve-Re-Gear.md) for public sharing.
