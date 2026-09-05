# Quick Access section navigation candidate

Scope: presentation and existing guarded display-action routing only.

- Current state uses compact Health/Game rows and the readiness-card surface.
- Current state, Your setup, and eGPU readiness are distinct native informational
  focus stops. They have visible focus treatment, no activation handlers, and
  scroll into view. The top summary retains the existing focus-restoration anchor.
- The readiness heading and quick-panel waiting text use generic eGPU wording.
  The current GpuPayload has no GPU model/name field; model display is deferred
  until an authoritative read-only model field is available. No model is inferred
  from a dock brand or hard-coded.
- The display action says Switch to TV or Switch to handheld, uses the existing
  guarded paths, and owns the Back/View + Y three-second hint. Unknown modes are
  disabled. Shutdown retains its explicit power-off warning.

The proposed combined disconnect guide and X shortcut are excluded. Hardware
owner confirmed that live eGPU disconnect is not supported and shutdown remains
required. No backend, polling, controller listener, or disconnect flow changes.

Release gate: hardware owner reports installed 0.3.47, exact revision pending
readback, with a supervised attached-G1 shutdown test in progress. Do not stage,
install, restart, or run transitions until that owner clears the test. No new
version or archive is allocated here. Follow focused PR review and the shared
ready/version ledger before producing an immutable ZIP for /home/deck/.

On-device validation remains required: D-pad Up from View full progress should
visit readiness, Your setup, then current state before Back. A must not mutate
anything on informational focus stops; B must retain native navigation. Verify
no clipping or horizontal overflow at actual Decky width.
