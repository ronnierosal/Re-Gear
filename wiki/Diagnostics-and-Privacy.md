# Diagnostics and privacy

**Audience:** players, support reviewers, and contributors<br>
**Reviewed:** 2026-09-06<br>
**Maturity:** privacy-safe snapshot and reviewed support export implemented

The authoritative contracts are
[Diagnostics](https://github.com/ronnierosal/Re-Gear/blob/main/docs/DIAGNOSTICS.md)
and [Support bundle](https://github.com/ronnierosal/Re-Gear/blob/main/docs/SUPPORT_BUNDLE.md).

Re-Gear collects enough categorical state to explain hardware and workflow health
without exposing the user's environment by default. The Decky view and support
projection use explicit allowlists instead of dumping raw system data.

## Appropriate diagnostic fields

- Re-Gear version and verified source revision
- placement, health, game-state category, and support tier
- categorical host/eGPU profile resolution
- render, display, link, sleep, and readiness status
- bounded public blocker and evidence codes
- bounded stage timings and recent categorical action outcomes

## Excluded or redacted fields

- usernames, hostnames, home directories, and arbitrary file paths
- IP and MAC addresses or private network coordinates
- raw USB, Bluetooth, EDID, or hardware serial identifiers
- Steam account IDs, game identity, cookies, tokens, and environment variables
- arbitrary process command lines, PIDs, logs, and correlation IDs
- private profile bindings and raw connector or device paths

Support export requires an exact redacted preview and one-time approval before
writing. Do not attach raw logs, captured home directories, or private support
artifacts to public issues.

## Repository privacy status

The 2026-09-02 audit found no tracked credential, private key, API token, Steam
account ID, MAC address, hardware serial, raw EDID, or raw USB4 unique ID in the
current tree. It removed an unnecessary local checkout path and sanitized
fixtures. Older reachable commits still contain a former private LAN address
and local path. Those are metadata rather than credentials, but eliminating
them from Git history would require a separately approved history rewrite.

See the full
[privacy audit](https://github.com/ronnierosal/Re-Gear/blob/main/docs/HARDWARE_PRIVACY_AUDIT_2026-09-02.md).
