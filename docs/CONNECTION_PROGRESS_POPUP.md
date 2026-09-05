# Live G1 connection progress

0.3.31 is a local UI candidate, not hardware-validated popup delivery.
The existing connection observer now publishes six categorical booleans and
sample age: exact PCI/driver readiness, link, exact G1 HDMI, audio rollback
readiness, Gamescope integration and idle game. No new hardware probing or
transition authority is introduced. Identity tokens are not exposed.

An idle attachment opens a dismissible progress dialog once per observed
connection. It does not cover a running game or an already-docked startup.
The panel retains View progress. Dismissal does not cancel automatic docking.
Only observed disconnection rearms automatic popup delivery. Read-only refresh
uses the existing foreground cadence while the dialog is open; a one-second
local freshness timer exists only while mounted and makes old greens expire.
No extra backend RPC polling loop is added.

Yellow means waiting or unknown, green means a fresh positive result, and red
means a blocker/timeout. Words and symbols accompany colors. Previous-result
clearance is a separate journal check. Older than 15 seconds or failed reads
cannot remain green. Elapsed time is the backend readiness-window age, not
an estimated completion time. The backend window may reset for late detection.
Audio recovery readiness is not TV audio proof; the switch phase explicitly
says it is checking picture and audio. TV completion is reported as backend
status and still needs the player's visible/audio confirmation.

All green does not execute a new action. Automatic docking retains its existing
coordinator. When automatic docking is explicitly off and all checks plus
settling pass, the dialog offers Switch to TV, routed to the existing guarded
approval/execution APIs. No unplug, restart-install, or shutdown authority changes.

Verification includes independent-check, stale/error, game/journal gate, timeout,
manual/automatic routing and subscription-cleanup fixtures. Native Decky layout,
controller focus, automatic appearance, dismissal, and survival across the
Gamescope restart require supervised Ally validation. Keep G1 attached until
physically powered off; install only after detached boot.
