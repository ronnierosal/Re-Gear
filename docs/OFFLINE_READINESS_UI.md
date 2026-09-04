# Offline Readiness UI

Status: **Implemented (read-only status and reason guidance); live source and
selected-game delivery wiring required**

Quick Access can present only the existing public Offline Readiness categories:
**Ready to try offline**, **Needs attention**, **Online check needed**, and
**Unknown**. “Ready to try” is deliberately not a promise that a game will
launch or play offline.

The optional payload accepts only schema version, categorical status, and public
reason codes. It has no title, AppID, account, path, timestamp, or collector
command fields. The UI retains only bounded allowlisted reasons and maps them
to fixed player-language guidance. A cloud conflict takes precedence over a
pending update. Unknown strings and oversized reason arrays are discarded;
raw reason text is never rendered. Unknown/missing
delivery remains a fail-closed “Not connected” status.

There is still no Steam/launcher collector, persistence, launch authority, or
new polling loop. A future source must be reviewed, local-only,
identity-minimized, benchmarked, bounded-cost, and freshness-gated before a
read-only adapter may supply this payload.

The application request service now revalidates a private selected-game/session
generation before returning one public result. It is not wired to Decky RPC or
the UI. A future UI owner must bind the request to its selected-game view and
discard the response on navigation, selection/session change, or expiry. Never
put an unidentified game's result into a whole-device readiness summary.

See the [active handoff](OFFLINE_READINESS_HANDOFF.md) for exact implementation,
verification, and remaining production gates.
