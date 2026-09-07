# Neutral informational focus follow-up

User confirmed0.3.49 D-pad Up visits informational sections correctly. The new
request is to make the gray section-focus highlight invisible, not stronger.

Read-only inspection of installed Steam Field implementation confirms that
focusable controls navigation registration independently of highlightOnFocus,
which adds the native HighlightOnFocus style class. Candidate keeps
focusable=true, forwarded ref and existing onGamepadFocus scrolling unchanged;
sets highlightOnFocus=false and neutralizes background/outline/shadow only on
.rg-section-focus. No global focus selectors or actionable controls are changed.
Section dimensions, semantic group labels and activation-free behavior remain.

174 frontend tests, typecheck and build pass. Diff review confirms no backend,
hardware action, navigation-route, version or package changes. New neutral
appearance still needs native player verification after a separately authorized
manual install. No ZIP staged or installation performed for this follow-up.
