# Asset visual approval — v1

Approved on 2026-09-08 by Codex, exercising Ronnie's explicit instruction:
"Review and approve if looks good". This records delegated visual approval,
not a claim that Ronnie personally inspected each image.

Scope: all ten SVGs in PR [144](https://github.com/ronnierosal/Re-Gear/pull/144)
at exact commit `370f39e97023bd4de98f43eab47d2b570104e0d0`.
Use the hashes in [GITHUB_ASSET_INTAKE.json](GITHUB_ASSET_INTAKE.json).
The uploaded manifest's older candidate-unapproved label is superseded for
these exact bytes by this dated approval record; newer bytes need reassessment.

## Review and approved use

[Actual-size comparison](captures/asset-size-review.png) shows each asset on
dark, light and checkerboard surfaces. Hashes were rechecked before rendering.
The previously recorded alpha checks confirm transparent backgrounds.

- The three module icons have distinct silhouettes and a consistent thin-line
  treatment. Use **24 CSS px** and retain the adjacent text label. The fan detail
  is secondary; it need not be individually recognizable at that size.
- Use **48–56px width** for the detailed mode illustrations where their eGPU/iGPU
  distinctions matter. At 32px they work only as supporting symbols next to
  explicit mode text; do not rely on their small secondary shapes alone.
- Restore Portable is approved at **24px with a text label**, never as an
  unlabeled safety instruction or a claim of safe removal.
- The established mark is recognizable at 24px. The wordmark is approved at
  **about 160px width or larger**, maintaining its 4:1 aspect ratio, on **dark
  backgrounds only**. At 104px the lettering is unnecessarily small. Its fixed
  near-white lettering is not approved for light backgrounds.
- Monochrome icons can use cyan/near-white on dark and a dark tint on light.
  No opaque backgrounds, checkerboard pixels, edge halos or clipping were
  observed in this review. Existing asset proportions and artwork stay intact.

## Implementation contract

Use inline SVG or a mask for currentColor assets; plain img does not inherit tint.
Namespace title/description/gradient IDs when repeated inline. Preserve viewBox
and aspect ratio; let native controls supply focus/disabled treatment. Check the
wordmark's font-dependent lettering on SteamOS. Do not redraw it silently.

This approves the asset pack for implementation. It does not approve a release,
hardware action, PR merge, unsupported backend capability, or the entire review-01
screen layout. Native SteamOS rendering/controller checks remain required later.

Documentation impact: none
