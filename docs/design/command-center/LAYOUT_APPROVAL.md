# Layout approval

Ronnie explicitly approved the current layout during the voice session:
"Other than that, layout looks good, approved."

Approved design baseline: review02 through commit `df6a36c`, including:

- Compact placement/display/game status header.
- Two-column FPS, TDP, Auto TDP and Display target quick-control tiles.
- Fifth Safe Disconnect tile, prepared and marked In development.
- eGPU status and Controller status links opening read-only details.
- Top-right Modules chooser opening configuration/action pages.
- Existing approved transparent asset pack at `370f39e` with sizing guidance.

This record supersedes pending-layout wording in earlier review documents for
this baseline. The owning implementation detail is [REVISION_02](REVISION_02.md),
with [ASSET_APPROVAL](ASSET_APPROVAL.md) for approved asset bytes and usage.
The original COMMAND_CENTER_PLAN is the task/dependency map; use these later
approved refinements where its earlier stacked-row hierarchy differs.

Left/right column and up/down row D-pad traversal, A activation, B return and
focus restoration are required implementation behavior. Native Decky/controller
validation is not supplied by the HTML prototype's keyboard checks.

Approval covers layout and intended interactions, not backend capability or
hardware safety. FPS integration needs a real provider contract; TDP options
must come from current device limits; display switching retains guards; Safe
Disconnect stays unavailable until the owning backend supports it. No live
unplug safety, installation, release or production completion is implied.

Next owner: Claude may claim the module foundation after resolving/landing
PR #129 in its agreed integration order. Recheck #50/#62/#82 overlap before
shared index/bundle work. Preserve single diagnostics-state semantics.

Documentation impact: none
