# Privacy-safe support bundle

## Purpose

Re-Gear can prepare a bounded JSON report for troubleshooting without exporting an
unrestricted journal or raw hardware/session identity. The player must preview
the exact redacted JSON before copying it or approving a save.

## Approval flow

```text
snapshot + bounded events
          |
          v
redact + allowlist + size bound
          |
          v
visible exact JSON preview
          |
          +--- Copy reviewed JSON
          |
          +--- one-time token ---> fixed Downloads save
```

`preview_support_bundle` has no arguments. It returns the exact JSON plus an
opaque token that expires after five minutes. `save_support_bundle` accepts only
that token, consumes it once, and writes those exact reviewed bytes. The
frontend cannot supply a path, filename, command, PID, hardware identifier, or
bundle content.

The Decky delivery adapter resolves the Decky user's home through Decky's own
runtime value, requires that resolved home to be one direct child of `/home`,
and writes a new `Re-Gear-support-<UTC timestamp>.json` file under the resolved
`Downloads` directory with exclusive-create and no-follow flags. It returns
only the relative `Downloads/...` path to the UI.

## Schema and bounds

- bundle schema: `2`
- structured event schema: `1`
- retained event count: at most `128`
- maximum encoded JSON size: `256 KiB`
- preview retention: at most three tokens for five minutes

Events contain a timestamp, severity, stable event code, component, operation
stage, ephemeral correlation identifier, and bounded categorical details. The
log rotates in memory and is discarded when the plugin process exits. It is not
a general system log or durable audit journal.

The bundle includes:

- Re-Gear, Decky, SteamOS, and kernel versions
- categorical certified-profile checks
- privacy-safe snapshot stage timings
- a reduced current snapshot
- recent Re-Gear-only events
- up to four reduced categorical transition histories with at most 32 recent
  entries each when a dormant/future transition owner explicitly supplies them
- up to eight reduced game and hardware compatibility records of each kind

Transition operation/request IDs, game titles, catalog IDs, evidence IDs, and
raw test artifacts are never included. Optional context defaults to empty in the
current Decky runtime because no live transition or compatibility-test owner is
wired.

## Privacy boundary

The bundle deliberately omits raw USB4 identity, EDID hashes, PCI addresses,
DRM card/render/control numbers, connector suffixes, Gamescope/client PIDs,
process instance fingerprints, output-order arguments, command lines,
environment variables, usernames, hostnames, IP addresses, private filesystem
paths, Steam account data, and the system journal.

Snapshot fields are rebuilt from an allowlist rather than copied wholesale.
Remaining strings pass through deterministic exact-value and pattern redaction,
length limits, collection limits, and final encoded-size enforcement.
Adversarial tests inject Windows and Linux home paths, usernames, hostnames,
addresses, PCI/DRM identifiers, connector names, long hardware-like values, and
oversized events and prove they are absent or truncated.

Support export cannot request Sleep, signal a process, restart a service, change
display/GPU state, or release hardware. A failed or expired approval writes
nothing and requires a new preview.
