> **Archived September 14, 2026.** Historical source at `9421c6f`; superseded by the [canonical Wiki](https://github.com/ronnierosal/Re-Gear/tree/main/docs/wiki). Do not use this as current instructions.

# Diagnostics and privacy

Re-Gear can show what it sees and prepare a small support report to help explain
a problem. You review the report before copying or saving it.

## For players — no technical background needed

### Availability and limits

The diagnostic view and support-report controls are implemented in merged
development code reviewed on **2026-09-13**. Your installed build may differ;
see [Getting Started](Getting-Started.md) for availability and installation limits.
This review did not test the controls on an installed handheld.

A **support bundle** is a text report containing selected Re-Gear status and
recent events. **Redacted** means identifying details are removed or replaced.
The report is designed to exclude account details, network addresses, raw device
identifiers, private paths and unrestricted system logs. Review it before sharing.
Creating a report does not fix a fault or establish that hardware can be unplugged.

### Preview, copy or save a report

1. Open Re-Gear in Decky's Quick Access panel and select **Troubleshoot**.
2. In **Support bundle**, select **Preview redacted support bundle**. A
   **Redacted support bundle preview** opens; creating it does not save a file.
3. Review the report, then select **Close preview**. The report uses **JSON**, a
   text format with named fields; you do not need to edit it. Select
   **Review exact redacted JSON** to view the same report again.
4. Choose **Copy reviewed JSON** to copy it, or **Save reviewed bundle to
   Downloads** to approve saving that exact report. Saving approval lasts five
   minutes from preview creation and can be used once.

A successful save reports a file under `Downloads`, named
`Re-Gear-support-<UTC timestamp>.json`; the timestamp records the save time.
Copying or saving does not send it to anyone. See
[Help Improve Re-Gear](Help-Improve-Re-Gear.md) for reporting guidance.

### If it does not work

- If the preview fails, no file was written. Try creating a new preview; if it
  fails again, report the visible error and your Re-Gear version.
- If save approval expires or fails, create and review a new preview before
  saving again.
- If clipboard copying is unavailable, the preview remains unchanged; use the
  save option after reviewing it.
- If these controls are missing, check your build with the maintainer. Do not
  substitute raw system logs or install a different candidate just to follow
  this guide. Continue with [Troubleshooting](Troubleshooting.md).

### Why root permission is requested

**Root** means system administrator access. Decky runs Re-Gear's backend with this
permission for protected system observations and its separately guarded hardware
operations. The visible interface sends specific requests to that backend.
Preparing a support report does not itself change displays, GPUs or sleep state.
See [Safety and eGPU Handling](Safety-and-eGPU-Handling.md) for action limits.

## Technical details — for advanced users and contributors

### Interfaces and privacy boundary

The [Decky UI](https://github.com/ronnierosal/Re-Gear/blob/da60e2127c4bd66e368918d3d83c1829087287a5/src/index.tsx)
calls `preview_support_bundle` and `save_support_bundle` through the
[backend entry point](https://github.com/ronnierosal/Re-Gear/blob/da60e2127c4bd66e368918d3d83c1829087287a5/main.py).
The preview contains exact redacted JSON and an opaque, expiring token. Saving
accepts only that token, consumes it once and writes the reviewed bytes; the
frontend cannot choose the destination or supply replacement content.

The report rebuilds snapshot fields from an allowlist, redacts remaining strings
and enforces size limits. Saving creates a new file exclusively and refuses
symlink following under the resolved Decky user's Downloads directory. See the
[support-bundle contract](https://github.com/ronnierosal/Re-Gear/blob/main/docs/SUPPORT_BUNDLE.md)
for schema, retention, bounds and exclusions. The root request is declared in
[plugin.json](https://github.com/ronnierosal/Re-Gear/blob/da60e2127c4bd66e368918d3d83c1829087287a5/plugin.json).

For source-checkout diagnostics on SteamOS, the reviewed read-only command is:

```sh
PYTHONPATH=backend python3 -m regear.cli --compact
```

Run it from the repository root. A Decky ZIP does not install a global
`regear-diagnose` command. Installed-tree commands depend on the package namespace;
use the [diagnostics contract](https://github.com/ronnierosal/Re-Gear/blob/main/docs/DIAGNOSTICS.md)
with the maintainer rather than guessing an older build's path. CLI output is a
snapshot; it does not reproduce all in-memory Decky event history.

### Evidence and implementation limits

| Evidence | What it establishes | Remaining limit |
|---|---|---|
| Merged source reviewed at `da60e21`, 2026-09-13 | UI labels, preview/copy/save flow and root declaration above | Source review does not establish the installed version or native controller behavior |
| [Support-bundle tests](https://github.com/ronnierosal/Re-Gear/blob/da60e2127c4bd66e368918d3d83c1829087287a5/tests/test_support_bundle.py) | Deterministic coverage for redaction, size bounds, one-use/expired approval and file-write protections | Tests do not certify all devices or prove an installed support journey |
| Installed / hardware-tested support journey | Not verified in this documentation review | Exact build, visible preview, copy/save result and controller navigation still need installed evidence |

The [2026-09-02 privacy audit](https://github.com/ronnierosal/Re-Gear/blob/main/docs/HARDWARE_PRIVACY_AUDIT_2026-09-02.md)
is historical repository evidence, not a fresh scan. It recorded no tracked
credentials in the then-current tree, while noting older reachable history with
private network/path metadata. This page does not claim history was rewritten.
