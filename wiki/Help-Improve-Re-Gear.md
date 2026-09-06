# Help Improve Re-Gear

**Audience:** players on any SteamOS handheld configuration<br>
**Reviewed:** 2026-09-06<br>
**Status:** existing diagnostics and support-preview guidance; packaged one-click diagnostic helper is future work

You do not need to write code to help. Clear descriptions, reviewed diagnostic reports, and feedback about confusing controls help us reproduce problems and improve compatibility. Reports from new configurations are useful even when a feature is unavailable; a report does not automatically certify that hardware.

## What to include

Search [open and closed issues](https://github.com/ronnierosal/Re-Gear/issues?q=is%3Aissue) for the same symptom before creating a report. Keep unrelated problems separate.

- What you expected and what happened instead.
- The shortest steps that led to the problem, and how often it occurs.
- Re-Gear version and build revision from the installed interface, plus SteamOS and Decky versions when available.
- Handheld, dock/eGPU, display, and controller model names relevant to the problem. Model names help reproduce it; serial numbers and private identifiers do not.
- Whether a game was running and whether the internal or external screen was active.
- A reviewed support report and an optional cropped screenshot with private information removed.

For offline-play reports, include the displayed badge/reason and whether a real offline launch was attempted. A readiness badge is not proof of a launch. Do not repeat a risky hardware failure just to obtain a report.

## Easiest option: the built-in support preview

If your installed build exposes support preview/export:

1. Open Re-Gear's troubleshooting/support controls in Decky.
2. Generate the support preview and review the exact report before sharing.
3. Copy the reviewed JSON or approve saving it. The current save flow creates a support JSON file in Downloads; use the relative filename shown by the interface.
4. Attach only that reviewed report to the matching GitHub issue, together with the symptom description.

Labels and availability can vary by build. If the control is absent, report the build and symptom; do not install an unrelated candidate simply to collect diagnostics. Export is local and does not automatically send anything to GitHub.

## Optional terminal check

For users comfortable with a terminal, an existing read-only Python diagnostic module can print a redacted snapshot. From a Re-Gear source checkout on SteamOS:

```sh
PYTHONPATH=backend python3 -m hdm.cli --compact
```

For a Decky-installed copy, have a maintainer confirm the plugin directory for your setup, replace `/path/to/plugin` below with that directory, and run:

```sh
PYTHONPATH="/path/to/plugin/backend" python3 -m hdm.cli --compact
```

These commands print JSON locally; review it before copying it into an issue. They do not upload data, restart services, switch GPUs, close games, or perform a hardware stress test. Run without sudo; permission-limited fields can remain unknown. This separate CLI snapshot does not contain all in-memory plugin events, so the built-in support preview is preferable when available.

The Decky ZIP does not install a global `hdm-diagnose` command. There is no separate public download-and-run diagnostic script yet. A packaged helper should reuse this reviewed collection path, show what it collects, and require review before sharing.

## Privacy and follow-up

The collection contract uses bounded, redacted categorical evidence. Never attach private keys, passwords, tokens, Steam account details, IP addresses, serial numbers, home directories, raw system journals, or unrestricted process dumps. Review screenshots and any text you add yourself too.

Maintainers may request a focused follow-up for an identified evidence gap. A diagnostic report helps explain a failure; it is not permission to run display/GPU transitions, disconnect a powered eGPU, or change system settings.

Authoritative details: [Diagnostics](https://github.com/ronnierosal/Re-Gear/blob/main/docs/DIAGNOSTICS.md), [Support bundle](https://github.com/ronnierosal/Re-Gear/blob/main/docs/SUPPORT_BUNDLE.md), and [Confirmed Hardware Testing](Confirmed-Hardware-Testing).
