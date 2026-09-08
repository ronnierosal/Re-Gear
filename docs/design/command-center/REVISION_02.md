# Review 02 — quick-control tiles

Ronnie clarified the layout using an Ally Command Center reference: keep the
compact placement/display/game status and Modules navigation, but replace the
stacked first-screen performance block with small selectable icon/value tiles.
This revision implements that instruction in the local mockup only.

- Two columns: FPS target, TDP limit, Auto TDP, Display target.
- Tile activation opens a compact picker; Auto TDP offers Stop while running
  or Configure otherwise. Back restores the invoking tile.
- Compact eGPU and Controller summaries follow the grid; deeper pages remain
  behind Modules. Removed the mock header's unnecessary Decky label.
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
