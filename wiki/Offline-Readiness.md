# Offline Play Readiness

**Audience:** players, testers, and contributors<br>
**Reviewed:** 2026-09-08<br>
**Maturity:** experimental development; no general public release

Re-Gear development source includes selected-game readiness guidance using local Steam evidence. See [Current State](Current-State) and [source review](https://github.com/ronnierosal/Re-Gear/blob/main/docs/OFFLINE_EVIDENCE_SOURCE_REVIEW.md).

## Where to find it

On a development build containing Offline Readiness delivery, use Re-Gear's Quick Access game check for the selected game. The feature also includes compact game-tile badges in supported Steam views. Availability and presentation depend on the installed build and Steam view; check the build label before comparing it to source or screenshots.

## What the statuses mean

The selected-game confidence layer uses these labels:

| Status | How to interpret it |
|---|---|
| Needs preparation | Steam reports a preparation or authorization blocker; inspect the explanation |
| Likely offline-ready | Independent local preparation and cached single-player internet-compatibility evidence support trying; no launch guarantee |
| Tested offline | Your explicit report for the matching account/game build, retained only in the current plugin session for at most 24 hours |
| Unverified | Evidence is missing, stale, unavailable, or no longer matches the game context |

The underlying readiness classifier also uses cautious terms such as **ready to
try offline**, **online check needed**, and **needs attention**. These are not
automatic offline-test results. An installed game or Steam ready-to-launch flag
does not prove entitlement, launcher behavior, or network independence.

After you independently reach playable content with the internet disconnected,
the panel can accept a confirmation only after a fresh matching check. It is
your attestation, not a test Re-Gear ran. Use **Forget this offline test** to
remove it; a plugin restart or expired/mismatched context invalidates it.

**Priority:** ongoing offline confidence and usability validation. Native Home,
Library, controller behavior, and exact-game offline launches remain separate
acceptance evidence; the source implementation does not establish those results.

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
