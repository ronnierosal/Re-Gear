# Current evidence and development state

Development build **0.3.180 is installed and loaded**, verified against source
`d1ee13dc54db1f789eaec683717072ab1090f3a8` and the unchanged reviewed ZIP.
On the recorded test configuration, two consecutive connection/TV/Safe Disconnect
+ Sleep cycles were user-observed successes. A separate retained request has
instrumented terminal and timing evidence. This is a bounded working checkpoint,
not complete Class D acceptance, general hardware support or a public release.
See the [current-state authority](../../CURRENT_STATE.md#installed-03180-working-checkpoint--october-5-2026-utc).

## For players — no technical background needed

Re-Gear is still in development and has no supported public release.

On the maintainer's recorded setup, the connection, TV picture, Safe Disconnect
and sleep journey worked twice in succession. That result applies to this exact
build and configuration. Shutdown, next-boot cleanup, eligible acknowledgement,
failure recovery and hiding the popup while a request is pending still need
separate checks. Follow the [eGPU player guide](../player/egpu.md) and the exact
supervised build instructions; software reconnect stays excluded.

A new build number is not the same as a tested build. A built package is not
automatically installed, supported or safe on other hardware.

## Technical details — for advanced users and contributors

Evidence levels are kept separate: **implemented in source**, **included in a
package**, **installed** (read back on the test handheld) and **supervised
hardware result** (an observed outcome on that one configuration). None extends
to other handhelds, docks, graphics cards or builds.

### Installed 0.3.180: bounded working checkpoint

The [October 5 UTC checkpoint](https://github.com/ronnierosal/Re-Gear/issues/464#issuecomment-5987964708)
verifies installed disk source, live backend and loaded frontend against the
immutable development-profile `Re-Gear-0.3.180.zip` (1,371,670 bytes), source
`d1ee13dc54db1f789eaec683717072ab1090f3a8`, SHA-256
`2a36f021f8aa02c036d4192c1f0f61a930bac315589476fa0f39918d619a2c13`.
Two consecutive connection/TV/Safe Disconnect + Sleep successes are separately
user-observed. Normal B-close/reopen and controller navigation were confirmed;
four attached/absent GPU-display captures share one boot identity.

The [superseding terminal/timing addendum](https://github.com/ronnierosal/Re-Gear/issues/464#issuecomment-5989274483)
reports `sleep_cycle_observed`, verified physical absence, completed teardown,
**one accepted suspend request**, no retained whole-dock claim, idle journal/no
acknowledgement required, and Portable/internal GPU/eGPU absent/no blockers.
This independently instruments one retained request, not two distinct cycles;
it supersedes earlier unavailable suspend/terminal/timing statements.

| Latest retained-request measurement | Duration |
|---|---|
| Before power verification | 40.9 seconds |
| Dock teardown | 30.9 seconds |
| Portable return | 6.0 seconds |
| GPU release | 3.6 seconds |

Teardown is the largest measured phase. Do not add these potentially overlapping
durations or attribute them to the first cycle without request-identity matching.
No historical latency regression or inner teardown cause is established.
Separate local timing/terminal archive SHA-256:
`a9512da5661e5a2d6f3cf45fb37f3aa7462e21b646a56cb8b715cb11f8f16d53`.
Original ZIP/checkpoint archives remain unchanged; private photos/raw device
records are not published.

Shutdown, next-boot acknowledgement retirement, genuine eligible acknowledgement
activation, failure recovery and Hide-while-pending remain open. Normal
B-close/reopen is not pending-warning F6 or eligible acknowledgement acceptance.
[#464](https://github.com/ronnierosal/Re-Gear/issues/464) remains Class D,
hardware-required, with separate approved-procedure and full exact-candidate
acceptance gates. The residual expired deauthorized sleep alarm remains a
fail-closed limitation until correlated absence; these successes do not qualify
that negative path. Software reconnect is excluded. See the
[technical authority](../../CURRENT_STATE.md#installed-03180-working-checkpoint--october-5-2026-utc)
for milestone #54's accepted successor and the still-open #438/#136/#161
obligations; unresolved PRs are not closed by this checkpoint.

### Candidate 0.3.180: exact software evidence

Historical October 3 software-review snapshot. Installation and bounded hardware
observations are superseded by the October 5 record above; all original software
evidence and outstanding acceptance boundaries are retained below.

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
