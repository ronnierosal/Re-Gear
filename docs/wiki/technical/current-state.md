# Current evidence and development state

The current candidate is immutable development-profile **0.3.180**, built and
software-validated at source `d1ee13dc54db1f789eaec683717072ab1090f3a8` against
merged main `cb8f0199f3aa5954a66b1061934fff70c696abdd`. Its source is proposed in
[draft PR #465](https://github.com/ronnierosal/Re-Gear/pull/465); it is **not
installed, hardware-accepted or released**. The last recorded installed build
remains **0.3.173**, with no fresh device readback in this update.
The [technical authority](../../CURRENT_STATE.md#software-validated-candidate-03180--october-3-2026)
records the exact artifact and evidence. Earlier hardware results remain bounded
to their original builds and configuration.

## For players — no technical background needed

Re-Gear is still in development and has no supported public release.

On the maintainer's single recorded test setup, the ordinary journey — return
to the handheld, **Safe Disconnect**, unplug, plug back in, TV picture returns —
has worked on earlier test builds. The disconnect-and-sleep journey has not yet
worked on an installed build.

Candidate 0.3.180 repairs software paths for retained display results, unplug
warnings, sleep-request cleanup and factual Portable GPU status. These software
checks do not establish how the native controls or lifecycle behave on a handheld.
An expired deauthorized sleep request can keep its alarm until correlated physical
absence is verified. The [lifecycle guide](egpu-lifecycle.md#candidate-03180-software-validation-only)
records the remaining supervised checks and separate hardware gates.

A new build number is not the same as a tested build. A built package is not
automatically installed, supported or safe on other hardware.

## Technical details — for advanced users and contributors

Evidence levels are kept separate: **implemented in source**, **included in a
package**, **installed** (read back on the test handheld) and **supervised
hardware result** (an observed outcome on that one configuration). None extends
to other handhelds, docks, graphics cards or builds.

### Candidate 0.3.180: exact software evidence

| Field | Recorded value |
|---|---|
| Source / review base | `d1ee13dc54db1f789eaec683717072ab1090f3a8` / `cb8f0199f3aa5954a66b1061934fff70c696abdd` |
| Immutable archive | `Re-Gear-0.3.180.zip`, development profile, 1,371,670 bytes |
| SHA-256 | `2a36f021f8aa02c036d4192c1f0f61a930bac315589476fa0f39918d619a2c13` |
| Producer evidence | [Artifact/test handoff](https://github.com/ronnierosal/Re-Gear/issues/464#issuecomment-5972496453) |
| Independent software review | [Combined PASS](https://github.com/ronnierosal/Re-Gear/issues/448#issuecomment-5972339102), then [exact final-head PASS](https://github.com/ronnierosal/Re-Gear/issues/448#issuecomment-5972475393) |
| Exact-head required CI | [CI PASS](https://github.com/ronnierosal/Re-Gear/actions/runs/37146099028), [privileged delivery PASS](https://github.com/ronnierosal/Re-Gear/actions/runs/37146099055) |

Producer/reviewer evidence reports both profiles' 5,130 backend tests with 33
skips each, 1,382 frontend tests per profile, 49 golden checks, architecture,
compilation, typecheck, builds and package validation passing. F1–F6 and the
Portable GPU presentation fixes are software-validated. This attribution does
not imply this documentation worker reran candidate runtime acceptance.

[Task #464](https://github.com/ronnierosal/Re-Gear/issues/464) remains Class D,
hardware-required. Native acknowledgement/controller focus, real F6 warning
close/reopen, and exact-candidate lifecycle, boot and power checks require an
approved supervised procedure and hardware acceptance before integration.
Neither 0.3.179 nor 0.3.180 has installed/hardware PASS; source review and CI do
not establish compatibility, safe unplugging or a public release.

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

Historical artifact record; superseded as the current candidate by 0.3.180.

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
