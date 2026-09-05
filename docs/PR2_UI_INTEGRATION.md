# PR 2 presentation integration

Baseline: approved ui/mockup-match at d380d37; integration starts from shipped
0.3.44 and staged 0.3.45 lineage, not the older GitHub main. That lineage is
published on codex/compact-branding-ui (PR 3) for separate historical review.

The live path remains src/index.tsx -> startConnectionMonitor ->
showConnectionLivePanel -> LivePanel. LivePanel now renders
ConnectionProgressOverlay from PR 2 through the existing store subscription.
The model accepts existing LiveStatus instead of repeating snapshot readiness
inference. Checking maps to Connecting, switching to Switching, and fresh
complete to Ready. Expiry returns to Connecting with pending rows. Audio
recovery readiness never becomes proof of active TV audio; final sound remains
explicitly player-verifiable. Existing Hide, manual switch freshness guard,
auto-close and monitor lifecycle remain in charge.

Quick Access and action visuals follow PR 2 with native focus buttons, current
SVG assets and one header. The real docked_egpu mode now labels/selects TV Docked.
No backend, connection monitor, live readiness mapper, polling cadence, safe
disconnect or controller shortcut changes are included.

Desktop render smoke: actual overview TSX at 320px and overlay at 640x600 fit
without horizontal overflow. Harness substitutes HTML for the native Decky
button, so this does not prove native controller focus or Steam modal sizing.
Screenshots are under output/pr2-connecting.png and output/pr2-quick-access.png.

Native acceptance remains pending manual installation: inspect Quick Access,
verify controller Hide/B/A, and have the hardware owner supervise one G1 attach
through Connecting -> Switching -> Ready. No physical attach or service
restart was performed by this UI integration task.
