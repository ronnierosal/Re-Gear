# Re-Gear 0.3.45 staging

2026-09-05: uploaded `/home/deck/Re-Gear-0.3.45.zip` for manual installation.
Build commit: `724f737` (full revision embedded in build_info.json).
SHA-256, verified locally and at final remote path:
`b6d04e03911d650089f23b7cac8dfe3344a5245992c0c6920770a927156de2da`.

One flat cyan emblem now serves both header and plugin list. Header text is
native. Emblem outline is thicker; mode icons omit blur and gradients.
Existing shapes and transparency are preserved. Backend unchanged.

161 frontend tests passed; 956 backend tests passed with six skips.
Typecheck, build, architecture, compilation and package checks passed.
Installed provenance before staging: 0.3.44, f63927a. No install or restart.
Visual acceptance at actual Steam/Decky scale remains for the maintainer.

Removed the superseded remote 0.3.44 ZIP after verifying 0.3.45. The original
0.3.44 ZIP remains locally under this worktree's out directory for recovery.
Only 0.3.45 remains in /home/deck. Unrelated archives were preserved.
