# Re-Gear 0.3.47 compact popup candidate

Staged for manual installation: `/home/deck/Re-Gear-0.3.47.zip`.
Revision: `0c77d128711938d8050496bae71e049f6e3eed9c`.
SHA-256 verified locally and remotely:
`f6c74711df25ff149bf2a5a20082bacf91b3eba7c11fc480381eca9d20e16742`.

Removed redundant subtitle, tightened header/phase/list spacing, reduced status
glyphs, and put Hide/manual Switch buttons in one row. Connection-specific
modal padding/width overrides retain space for Steam UI. No clipping or scale
transform is used. Synthetic HTML-control render of actual overlay TSX with
seven rows and both buttons measured 385px tall at 400px and 496px widths.
Native Steam font metrics and controller behavior still need player validation.

165 frontend tests passed; 956 backend tests passed with six skips. Typecheck,
build, architecture, compilation and package checks passed. PR 5 updated.
Installed before transfer: 0.3.46 efddaa7. No installation/restart performed.
Removed remote 0.3.46 ZIP after verification; local out copy retained for recovery.
