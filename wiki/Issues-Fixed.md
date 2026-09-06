# Fixes and issue tracking

**Audience:** players, testers, and contributors<br>
**Reviewed:** 2026-09-06<br>
**Maturity:** experimental development; no general public release

Use [GitHub Issues](https://github.com/ronnierosal/Re-Gear/issues) for player-reported bugs, current investigation, and verification criteria. Search open and closed issues before reporting a duplicate. A local patch, merged PR, or passing test does not by itself close an installed or hardware problem.

## Selected recorded improvements

| Change | Evidence | Remaining limit |
|---|---|---|
| Gamescope launch binding and config readability | Earlier fixes were followed by a supervised TV/render success | Repeatable hardware journeys remain a separate gate |
| Shared-journal acknowledgement ownership | Correct owner routing and a subsequent retry were observed | Unknown or incomplete journals must remain blocked |
| G1 HDMI routing | Automatic default-sink selection recorded in a supervised cycle | Readiness and restoration must be verified per build and cycle |
| Focused Offline Readiness refresh recovery | [Integrated source change](https://github.com/ronnierosal/Re-Gear/commit/fd9e30b2b4acd0b98ead62180b21fd9cba0cb58b) resumes interrupted checks and bounds retries | Integration does not imply installation or real offline-launch proof |

The [historical docking incident](Ally-X-and-GPD-G1-Docking-Incident) preserves the earlier causal chain. See [Current State](Current-State) for current capability limits and [Troubleshooting](Troubleshooting) for the information to include in a bug report.
