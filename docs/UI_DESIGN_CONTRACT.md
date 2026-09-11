# UI design preservation

This contract applies to Codex, Claude and other contributors changing menu,
popup, styling, icon or navigation code. Codex owns UI implementation and design;
Claude owns backend wiring unless the user assigns otherwise. Shared-file claims
and accepted transfers still apply. Backend wiring is not permission to redesign.

## Baseline and allowed change

The user-supplied [approved Command Center reference](design/command-center-approved.md)
is the current visual target. Its explicit composition supersedes earlier concepts
where they conflict. The source baseline below is historical implementation
evidence, not permission to ignore that target. Compare reference, baseline and
proposed source; document technical deviations rather than silently redesigning.

Before editing, record in the existing task or PR:

- The exact source baseline and owning design document.
- The user-requested change and affected components.
- The visual properties expected to remain unchanged.

Use current source plus the latest explicit user decision, not whichever old
mockup looks most polished. A generated image is a placement/concept reference
unless the user explicitly approves replacing the design. Approval of a new
button does not approve changing typography, colors, icons, header, tabs, panel
dimensions, grid density, footer or unrelated screens. Keep existing components
and tokens where possible. Do not replace the stylesheet as incidental polish.

The earlier compact Command Center correction in PR #274, source `93902f4` and merge
`f95b94d`, anchors the preserved central layout: 53vw by 82vh, compact tabs and
footer, dark surfaces with cyan focus, icon plus label above value and secondary
text. Content-width thresholds are 400/300/280px for four/three/two columns,
with one below 280px. Safe Disconnect spans two columns in four-column mode.
These values identify the correction, not proof of native readability or a ban
on explicitly requested future changes. New side controls must preserve the
central layout unless the user requests otherwise. The current approved reference
specifically places brightness/volume inside the main panel and a detached action
panel near the right screen edge. Do not pin historical pixel/CSS values when
they conflict with this explicitly approved composition and readable scaling.

For intentional changes to these properties, record the user instruction and
update the owning contract and affected checks together. Existing authorization
is sufficient; routine fixes restoring the baseline do not need another approval.
If a feature genuinely requires an unrequested redesign, describe the concrete
tradeoff before changing that design.

## Verification before merge

1. Render the baseline and proposed actual UI source at identical dimensions,
   scale, data and focus state. Include 828x466 CSS pixels for the known handheld
   case and a wider case; use actual content-width breakpoints, not forced columns
   as the acceptance result. Keep before/after images and their source revisions
   with the task/PR evidence. Synthetic host bars must be labeled synthetic.
2. Inspect header/tab separation, intact words, label/value hierarchy, Settings
   visibility, grid density, Safe Disconnect visibility, footer size and focus
   contrast. Check unavailable and long-reason states. New controls must not
   silently displace existing important actions or consume the content area.
3. Run affected layout/navigation regressions, typecheck and build. Preserve
   D-pad, LB/RB, A/B, touch, nested Back and focus restoration. Add or update a
   regression for an observed defect; do not merely change assertions to accept
   drift. Existing checks include `frontend-tests/expanded-command-center.test.mjs`
   and the source browser preview in `scripts/expanded_visual_preview.mjs`.
4. Report what was inspected and any differences from the requested delta.
   Tests and screenshots are complementary: green CI alone is not visual review.
   Browser keyboard fixtures are not native controller proof. Record native
   validation as pending when not performed; do not relabel a mockup as installed.

## Integration and release handoff

Recheck the final combined revision for presentation changes from other PRs.
Include the baseline, intended delta, comparison evidence, tests and remaining
native checks in the release handoff. Keep packaged, installed and hardware-tested
states separate. Preserve safety wording and real/unknown state semantics while
correcting appearance. Do not enable unsupported controls to make a preview look
finished, or present unmounted components as delivered features.

When source changes supersede an old specification, correct the owning document
in the same PR or include the documentation owner's exact correction. Mark old
evidence historical instead of leaving competing sections labeled current.
