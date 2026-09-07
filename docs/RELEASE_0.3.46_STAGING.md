# Re-Gear 0.3.46 UI integration candidate

Staged 2026-09-05 for manual installation at `/home/deck/Re-Gear-0.3.46.zip`.
Revision: `efddaa7d5d3318e1de69044ae533a4b16a5f4d6a`.
Local and final remote SHA-256:
`5a00c8630de5b5acbe75c4db128e8afe8e901c189e99ce0806151ba3048d7eb0`.

PR 5 targets the separately published shipped baseline in PR 3. Neither was
merged by this task. Approved PR 2 visuals are wired to the existing popup's
LiveStatus store; see PR2_UI_INTEGRATION.md for mapping and rendering evidence.
All four previously registered workstreams plus pr2-ui are included.
165 frontend tests and 956 backend tests passed (six skips), together with
typecheck, production build, architecture, compile and package checks.

Installed readback before staging remained 0.3.44 at f63927a. No install,
restart or hardware transition performed. Native controller and modal layout
acceptance, auto docking, and Connecting -> Switching -> Ready validation
remain pending supervised testing after the maintainer installs manually.

Removed the superseded remote 0.3.45 ZIP after final hash verification.
Its local out/Re-Gear-0.3.45.zip remains available for recovery.
