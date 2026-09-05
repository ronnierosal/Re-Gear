# Live G1 connection progress

0.3.31 is a local UI candidate, not hardware-validated popup delivery.
The existing connection observer now publishes six categorical booleans and
sample age: exact PCI/driver readiness, link, exact G1 HDMI, audio rollback
readiness, Gamescope integration and idle game. No new hardware probing or
transition authority is introduced. Identity tokens are not exposed.

An idle attachment opens a dismissible progress dialog once per observed
connection. It does not cover a running game or an already-docked startup.
The panel retains View progress. Dismissal does not cancel automatic docking.
Only observed disconnection rearms automatic popup delivery. The plugin-owned monitor serializes status reads one second after each
completed read, independently of Quick Access mounting. Its first fresh sample
establishes a baseline and cannot open an already-connected popup. A one-second
local freshness timer while mounted makes old greens expire.

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

## Animated presentation

The modal uses a dark bordered card, amber checking rings, 200 ms green check
entrances, and an indeterminate cyan sweep during the backend switching phase.
Reduced-motion preferences disable all three animations. Stale samples show
static waiting icons and never retain a completion or manual-switch state.
Backend docked status plus docked inference and fresh checks show a completion
panel; after 3.5 seconds it revalidates freshness before closing. This is a
reported transition result, not independent player confirmation of picture or
sound. No individual HDMI-audio step is fabricated from pre-switch checks.
Native Decky appearance and focus remain pending hardware validation.
