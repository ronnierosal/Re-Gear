# Quick Access section navigation candidate

## Follow-up to installed 0.3.48

Player reports Up from Automatic TV docking still jumps directly to Back.
The generic Focusable wrappers did not establish reliable informational leaves
on the device. Candidate now uses native Field with explicit focusable=true,
highlightOnFocus=true, no activation handlers, and forwarded restoration refs.
Regression checks require that explicit contract; they do not simulate Steam's
actual focus router. Typecheck, frontend tests, and build pass. Hardware
confirmation is still required before claiming the reported jump is fixed.

Read-only CDP inspection of installed0.3.48 confirmed the exact cause: native
Focusable sets navigation focusable automatically only for an activation handler
unless explicit navigation options are supplied. Installed SectionFocus supplied
neither; its DOM had no tabindex while Automatic TV docking had tabindex=0.
The Field replacement uses the library's explicit focusable=true contract.
No device source, settings, focus, or input was modified during inspection.
Actual D-pad sequence with the new candidate is still pending installation.

The live QuickAccess viewport measured855x387 CSS pixels, with a268px-wide
information column. Connection popup candidate reduces outer width496 to432,
inner width480 to420, row minimum22 to19 and row padding2 to1px. Body text stays
13px; controls stay32px. This targets roughly10–15% reduction without transforms
or hidden checklist rows. Final native popup fit remains a player check.

Scope: presentation and existing guarded display-action routing only.

- Current state uses compact Health/Game rows and the readiness-card surface.
- Current state, Your setup, and eGPU readiness are distinct native informational
  focus stops. They have visible focus treatment, no activation handlers, and
  scroll into view. The top summary retains the existing focus-restoration anchor.
- The readiness heading and quick-panel waiting text use generic eGPU wording.
  Optional driver-reported model_name is now exposed for presentation only; see
  UI_GPU_NAME.md. Missing/ambiguous/stale names show eGPU. No model is inferred
  from a dock brand or hard-coded.
- The display action says Switch to TV or Switch to handheld, uses the existing
  guarded paths, and owns the Back/View + Y three-second hint. Unknown modes are
  disabled. Shutdown retains its explicit power-off warning.

The proposed combined disconnect guide and X shortcut are excluded. Hardware
owner confirmed that live eGPU disconnect is not supported and shutdown remains
required. Backend changes are limited to optional read-only GPU presentation;
no readiness, polling cadence, controller listener, or disconnect flow changes.

Release gate: baseline is installed 0.3.48. Recheck hardware-owner clearance
before staging; do not install, restart, or run transitions from this task. No new
version or archive is allocated here. Follow focused PR review and the shared
ready/version ledger before producing an immutable ZIP for /home/deck/.

On-device validation remains required: D-pad Up from View full progress should
visit readiness, Your setup, then current state before Back. A must not mutate
anything on informational focus stops; B must retain native navigation. Verify
no clipping or horizontal overflow at actual Decky width.
