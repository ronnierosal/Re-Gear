# Fixes and issue tracking

**Audience:** players, testers, and contributors<br>
**Reviewed:** 2026-09-09<br>
**Maturity:** experimental development; no general public release

Use [GitHub Issues](https://github.com/ronnierosal/Re-Gear/issues) for player-reported bugs, current investigation, and verification criteria. Search open and closed issues before reporting a duplicate. A local patch, merged PR, or passing test does not by itself close an installed or hardware problem.

## Selected recorded improvements

| Change | Evidence | Remaining limit |
|---|---|---|
| Gamescope launch binding and config readability | Earlier fixes were followed by a supervised TV/render success | Repeatable hardware journeys remain a separate gate |
| Shared-journal acknowledgement ownership | Correct owner routing and a subsequent retry were observed | Unknown or incomplete journals must remain blocked |
| External HDMI routing on the tested profile | Automatic default-sink selection recorded in a supervised cycle | Readiness and restoration must be verified per build and cycle |
| Focused Offline Readiness refresh recovery | [Integrated source change](https://github.com/ronnierosal/Re-Gear/commit/fd9e30b2b4acd0b98ead62180b21fd9cba0cb58b) resumes interrupted checks and bounds retries | Integration does not imply installation or real offline-launch proof |
| eGPU client scan could never complete on a live system | A descriptor closed between listing a process's descriptors and reading them marked the entire scan incomplete. The guard asked whether the *process* was still alive, and it was; only the descriptor had gone. With Steam running this fired constantly, so a clear device could never be verified ([#187](https://github.com/ronnierosal/Re-Gear/pull/187)) | Found by running the sequence on hardware, not by a test. A second scanner in the same codebase had this fixed in [#137](https://github.com/ronnierosal/Re-Gear/pull/137); the fix was never applied here |
| A device nothing held could not be armed | The restart planner received holder names without whether the scan had finished, so it could not tell "found nothing" from "could not look" and refused both. An idle eGPU is the ordinary state before a disconnect ([#187](https://github.com/ronnierosal/Re-Gear/pull/187)) | The same weakening repaired one layer up in [#174](https://github.com/ronnierosal/Re-Gear/pull/174), still present at the boundary below it |
| The disconnect reported itself as blocking the disconnect | Holding the eGPU's card node open is what keeps the display released; the readiness scan running inside that window counted the descriptor as a blocking client ([#190](https://github.com/ronnierosal/Re-Gear/pull/190)) | Diagnosed from a hardware run rather than a direct reading, and fixed in a way that is correct either way |
| A session-target restart was never waited for | The step waited for `gamescope-session.target` to leave the holder list. Holders are named by their leaf cgroup and a systemd target has no cgroup, so the wait passed instantly and always, without the session having restarted ([#192](https://github.com/ronnierosal/Re-Gear/pull/192)) | Introduced while making restarts verify by observation; the tests covered a service and never a target |

All four eGPU entries above were found by running the sequence on hardware on
September 9. None was caught by the source tests, which numbered over two
thousand and passed throughout. Each was a guard that refused correctly in
principle and, on a live system, refused always. That is the pattern worth
carrying forward: a conservative default is not automatically a safe one if it
can never be satisfied.

The [historical docking incident](Ally-X-and-GPD-G1-Docking-Incident) preserves the earlier causal chain. See [Current State](Current-State) for current capability limits and [Troubleshooting](Troubleshooting) for the information to include in a bug report.
