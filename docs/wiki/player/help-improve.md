# Help improve Re-Gear

You do not need to write code to help. A clear description of what happened,
plus a report you have reviewed, helps contributors investigate a problem.

## For players — no technical background needed

### Send a useful report

1. Search [open and closed issues](https://github.com/ronnierosal/Re-Gear/issues?q=is%3Aissue)
   for the same symptom. Add relevant information to a matching issue, or create
   a new one if none fits. Keep unrelated problems separate.
2. Describe what you expected, what happened instead, the shortest steps that
   led to it, and how often it happens.
3. Include the details below when available. Missing information is fine; say
   what you could not check rather than guessing.
4. If your build offers **Preview redacted support bundle** under
   **Troubleshoot**, follow [Diagnostics and Privacy](diagnostics-and-privacy.md)
   to review, copy or save a report. Attach only the reviewed report to the
   issue. Saving a report does not send it to GitHub automatically.

| Include | Why it helps |
|---|---|
| Re-Gear version and build revision shown by the installed interface; SteamOS and Decky versions if known | Identifies the software you actually used |
| Relevant handheld, dock/eGPU, display and controller model names | Helps compare setups; omit serial numbers and other private identifiers |
| Whether a game was running, which screen was active, and whether picture, audio and controls worked afterward | Describes the state before and after the problem |
| Optional cropped screenshot with private information removed | Shows an error or confusing control without exposing account information |

For offline-play reports, include the displayed badge/reason and whether a real
offline launch was attempted. A readiness badge does not prove a game launched.
Reports from unfamiliar hardware are useful, but do not establish support for it.

### If you cannot collect a report

If support controls are missing, report your build and symptom anyway. The
controls exist in development source, but availability depends on your installed
build; see [Getting Started](getting-started.md). Do not install an unrelated
candidate just to collect diagnostics. If preview, copy or save fails, use the
[diagnostics troubleshooting steps](diagnostics-and-privacy.md#if-it-does-not-work).

You do not need to repeat a risky hardware failure to make a useful report.
Review any text or screenshot you add yourself as well as the generated report.
Do not post passwords, tokens, account details, network addresses, serial numbers,
private folders or raw system logs.

Maintainers may ask a focused follow-up to resolve missing evidence. A report
helps investigate a fault; it is not permission to disconnect a powered eGPU or
perform a hardware test. Follow [Safety and eGPU Handling](safety.md).

## Technical details — for advanced users and contributors

### Collection interfaces

Prefer the built-in support preview when available: it can include recent
in-memory Re-Gear events. The separate read-only CLI provides a snapshot and
cannot recreate all of that history. Use the
[reviewed CLI instructions](diagnostics-and-privacy.md#interfaces-and-privacy-boundary)
and [diagnostics contract](https://github.com/ronnierosal/Re-Gear/blob/main/docs/DIAGNOSTICS.md)
for source or installed-tree commands. Run diagnostic collection without sudo;
permission-limited values can remain unknown. Decky ZIPs do not install a global
`regear-diagnose` command.

The [community-report helper procedure](https://github.com/ronnierosal/Re-Gear/blob/main/docs/COMMUNITY_REPORT.md)
is a separate guided collection route. Follow its exact reviewed download and
checksum instructions; it is not automatically included in existing Decky ZIPs.
It runs the trusted installed diagnostic module, previews selected information,
and saves only after the user's explicit response. It does not upload the report.

### Evidence and validation limits

Guidance reviewed against merged source `6d315af` on **2026-09-13**. The
[support-bundle contract](https://github.com/ronnierosal/Re-Gear/blob/main/docs/SUPPORT_BUNDLE.md)
and [tests](https://github.com/ronnierosal/Re-Gear/blob/6d315afd9498d8b7cae6c539f79758e0750cb058/tests/test_support_bundle.py)
cover bounded reporting, redaction and preview approval. A report is diagnostic
evidence, not proof that a fix is installed, a feature works on every device or
physical removal is safe. This documentation review performed no installed
collection or hardware trial.

When following up, identify the specific missing observation and preserve the
reported build, setup and timing. Distinguish unknown fields from absent devices,
reported observations from captured evidence, and source fixes from installed
results. Link dated hardware evidence through
[Confirmed Hardware Testing](../technical/hardware-evidence.md); do not turn a community
report into a certification claim.
