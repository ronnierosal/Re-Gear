# Current evidence and development state

The eGPU lifecycle work is merged in `main` `fb334f2` (package version 0.3.153).
The latest build of it is local development artifact **0.3.154**: built and
software-validated, **not installed, released or hardware-tested**. The ordinary Safe
Disconnect journey's hardware baseline comes from earlier builds, listed below.

## For players — no technical background needed

Re-Gear is still in development and has no supported public release.

On the maintainer's single recorded test setup, the ordinary journey — return
to the handheld, **Safe Disconnect**, unplug, plug back in, TV picture returns —
has worked on earlier test builds. The disconnect-and-sleep journey has not yet
worked on an installed build.

Build 0.3.154 adds a first-time device permission popup, step-by-step connection
progress, protection that keeps a disconnected eGPU off while it is still
plugged in, and one-button **Disconnect + Sleep** and **Safe Disconnect +
Shutdown**. None of that has been tried on a handheld yet. The
[eGPU guide](../player/egpu.md) explains what to expect.

A new build number is not the same as a tested build. A built package is not
automatically installed, supported or safe on other hardware.

## Technical details — for advanced users and contributors

Evidence levels are kept separate: **implemented in source**, **included in a
package**, **installed** (read back on the test handheld) and **supervised
hardware result** (an observed outcome on that one configuration). None extends
to other handhelds, docks, graphics cards or builds.

### Hardware results recorded in the authority

From [CURRENT_STATE](../../CURRENT_STATE.md), including its September 24
lifecycle evidence refresh:

| Date | Build | Result | Limit |
|---|---|---|---|
| 2026-09-13 | 0.3.98 (`f6059fa`) | One supervised disconnect, physical unplug and replug cycle succeeded ([checkpoint](egpu-lifecycle.md)) | Preserved reference; repeatability, other hardware and sleep not established |
| 2026-09-21 | 0.3.127 | Maintainer-reported manual journey: TV to handheld, Safe Disconnect, physical unplug, reconnect, return to TV | Version-labelled report; no recorded revision or checksum |
| 2026-09-22 | 0.3.129 (`e8ad848`) | Supervised: automatic TV, both display switches, Safe Disconnect through software-down, physical unplug/reconnect and automatic return to TV passed | Same configuration only |
| 2026-09-22 | 0.3.129 (`e8ad848`) | **Disconnect + Sleep failed**: returned to the handheld but did not reach software-down, the unplug prompt or sleep | Source fixes merged in [PR #383](https://github.com/ronnierosal/Re-Gear/pull/383); not re-proven on hardware |

### Development build 0.3.154

| Field | Value |
|---|---|
| Archive | `Re-Gear-0.3.154.zip`, development profile |
| Revision | `f6be3edd5702f3f4c258465df861edc8f8642373` |
| SHA-256 | `db017e82915f2bf2fb95f03c61bfbcd30cb01815f1d0d2f1c224fbffd18eb860` |
| Composition | `main` `9dcdaff` + [PR #418](https://github.com/ronnierosal/Re-Gear/pull/418) `f98f8d0` + authorization-hold fix `5887900`; that source has since merged as `main` `fb334f2` ([PR #425](https://github.com/ronnierosal/Re-Gear/pull/425)) |
| Software checks | Golden 49/49 (8 contracts); frontend 1,233/1,233; focused eGPU/authorization backend 608 tests + 764 subtests; architecture, compileall, Ruff F82, TypeScript, both profile builds and package integrity passed |
| Status | Local development artifact. Not installed, deployed, released or hardware-tested. Not yet recorded in CURRENT_STATE |

The [lifecycle guide](egpu-lifecycle.md#development-build-03154-built-not-yet-hardware-tested)
breaks every 0.3.154 capability into source, package, previously observed and
awaiting-hardware columns, and lists the exclusions.

Software reconnect stays excluded after the 0.3.92 incident; see
[the lifecycle guide](egpu-lifecycle.md#software-reconnect-decision-and-retained-machinery).
Read-only readiness probes and CI do not execute a disconnect, validate a button
path or establish hardware safety.

### Related records

[Power implementation](../../EGPU_POWER_NEXT.md) separates merged backend and
coordinator code from mounted integration and hardware acceptance.
[Golden preservation](../../GOLDEN_BEHAVIORS.md) defines the regression gate.
Follow the owning PRs and exact revisions rather than inferring capability from
version ordering. Historical point-in-time records are in the
[archive](../../archive/README.md).
