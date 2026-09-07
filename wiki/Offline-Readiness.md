# Offline Play Readiness

**Audience:** players, testers, and contributors<br>
**Reviewed:** 2026-09-06<br>
**Maturity:** experimental development; no general public release

Newer Re-Gear development candidates show selected-game readiness guidance using local Steam evidence. See the [current candidate](https://github.com/ronnierosal/Re-Gear#-current-status) and [source review](https://github.com/ronnierosal/Re-Gear/blob/codex/release-batch-2026-09-06/docs/OFFLINE_EVIDENCE_SOURCE_REVIEW.md).

## Where to find it

On a development build containing Offline Readiness delivery, use Re-Gear's Quick Access game check for the selected game. The feature also includes compact game-tile badges in supported Steam views. Availability and presentation depend on the installed build and Steam view; check the build label before comparing it to source or screenshots.

## What the statuses mean

| Status or evidence | How to interpret it |
|---|---|
| Needs attention | A reported condition, such as an update or cloud conflict, needs review |
| Online check needed / unknown / unavailable | Re-Gear lacks sufficient current evidence; do not interpret it as ready |
| Ready to try offline | A cautious readiness label, not proof of a successful launch; limited Steam evidence alone cannot establish it |
| Installed or Steam ready-to-launch | Installation/launch metadata only; not proof that a launcher, entitlement, or network requirement is satisfied |

## Before leaving Wi-Fi

1. Select the game you intend to play and inspect its check and explanation.
2. Resolve reported updates or cloud conflicts while connected.
3. Treat missing or expired evidence as unknown and recheck the same game.
4. A separately performed real offline launch is stronger evidence than a badge; record its exact game/build context before calling it confirmed.

See [Confirmed Hardware Testing](Confirmed-Hardware-Testing) for recorded device results. This Wiki does not claim that every game, or any particular untested game, will work offline.

## Read the reason, not just the badge

A badge summarizes the evidence available for the selected game. Missing, stale, or unavailable evidence must remain uncertain. An installed game or Steam's ready-to-launch flag does not prove entitlement, completed cloud synchronization, launcher readiness, or successful offline play.

Updates, downloads, or cloud conflicts can require attention. Follow the displayed reason while connected, and confirm that the selected game and its local evidence are current. Re-Gear does not guarantee a game will launch without the network.

## When a check is interrupted

The recent focused-refresh correction resumes checks after interrupted activity and bounds retries. If the view still reports unavailable or uncertain evidence, do not interpret that as a positive result. Report the game-view context, Re-Gear build, displayed reason, and what happened before the check stopped through [Troubleshooting](Troubleshooting).

These checks do not authorize automatic game launches, account changes, or hardware transitions. Keep private account details and raw logs out of public reports.
