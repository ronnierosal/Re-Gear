# Review 02 — quick-control tiles

Ronnie clarified the layout using an Ally Command Center reference: keep the
compact placement/display/game status and Modules navigation, but replace the
stacked first-screen performance block with small selectable icon/value tiles.
This revision implements that instruction in the local mockup only.

- Two columns: FPS target, TDP limit, Auto TDP, Display target.
- User follow-up explicitly adds a fifth **Safe Disconnect** tile, prepared for
  Claude's upcoming backend work. It displays **In development** and opens an
  informational placeholder with no disconnect operation. Do not invent a sixth
  tile merely to fill the grid. Production enablement requires the owning
  backend's verified capability, readiness and confirmation flow; this mockup
  neither asserts safe live removal nor changes current shutdown guidance.
- Tile activation opens a compact picker; Auto TDP offers Stop while running
  or Configure otherwise. Back restores the invoking tile.
- Compact eGPU and Controller summaries follow the grid; deeper pages remain
  behind Modules. Removed the mock header's unnecessary Decky label.
- User follow-up: label these rows **eGPU status** and **Controller status**.
  They open read-only status detail, not the configuration module. The top-right
  Modules button opens the module chooser for configuration/actions. Back returns
  to the invoking status row. Preserve this distinction during implementation.
- Approved gauge/eGPU artwork is used on relevant tiles; monitor/lightning
  reuse existing simple vector vocabulary. No ASUS artwork copied.

[Updated preview](review.html) and [screen overview](captures/review02/review-02.png).
Earlier review-01 captures remain historical; use the review02 folder for current
layout review. Full new layout sign-off remains pending.

The FPS picker is a proposed new capability, not the existing Auto TDP target FPS.
All displayed choices are illustrative. TDP choices in production must come from
device limits and preserve existing manual-apply/session guards. Display selection
requests an existing guarded transition; it never bypasses checks or pretends a
missing display is available. Production must omit/disable unsupported controls.
Do not use these fixture choices as backend defaults or safety permissions.

Verification: 72 local layout cases, local FPS/TDP selection, Auto Stop/Start,
Modules/Back, focus return, short-height scroll and unknown-state recovery passed;
zero browser errors. Native SteamOS/gamepad and backend integration remain untested.
This changes design artifacts only and does not claim Claude's production scope.

Documentation impact: none
