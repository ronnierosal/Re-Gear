# Review 01 asset manifest

## GitHub candidate pack received

Update: the exact received pack is now visually approved under Ronnie's delegated
review instruction. See [ASSET_APPROVAL](ASSET_APPROVAL.md) for sizes, dark-only
wordmark use and evidence. Earlier candidate status below is intake history.

PR [144](https://github.com/ronnierosal/Re-Gear/pull/144), branch
`design/command-center-assets-v1`, exact reviewed commit
`370f39e97023bd4de98f43eab47d2b570104e0d0` supplies ten SVG candidates.
[Pinned source folder](https://github.com/ronnierosal/Re-Gear/tree/370f39e97023bd4de98f43eab47d2b570104e0d0/docs/design/command-center/assets/v1)
and [pinned manifest](https://github.com/ronnierosal/Re-Gear/blob/370f39e97023bd4de98f43eab47d2b570104e0d0/docs/design/command-center/assets/v1/ASSET_MANIFEST.json)
are available to both coding agents. Use this revision, not a moving branch URL.

[Intake evidence](GITHUB_ASSET_INTAKE.json): all ten SHA-256 values match;
bounded XML inspection found only allowed vector/text elements and no external
resources or scripts. Local Edge renders have visible artwork, transparent pixels
and transparent corners. Antivirus was not run; this is passive asset verification,
not a malware-safety certification. Original asset files were not modified.

The uploaded manifest says `candidate-unapproved`. Availability and transparency
are verified; visual approval, small-size acceptance and provenance/license claims
remain separate. This supersedes the earlier statement that no pack was generated;
the original reuse table below remains the review-01 baseline.

Integration notes: currentColor monochrome assets require inline SVG or an
appropriate mask; a plain img does not inherit its parent's color. Preserve each
viewBox/aspect ratio. Namespace repeated title/desc and gradient IDs when inlining
multiple assets. The wordmark uses font-dependent text; check its actual SteamOS
font rendering before approving an exact lettering match. Do not replace the
current review's icons silently or interpret this pack as approval of the layout.

Navigation coordination also received explicit owner agreement: land PR #129
first, then evolve to the labelled Modules stack while retaining its single
showDiagnostics state semantics. The owner confirmed/fixed the unavailable-section
resolver at `4a24d7f29ac282e16443cb52b89b2b17511772d8`. #129 was still open at
this intake; no merge or integration is claimed here.

No new custom artwork is required to review this design. Existing repository
assets are referenced directly, not replaced. Their original author/license
provenance was not independently established in this task; repository inclusion
alone is not a new licensing certification. Public distribution review should
retain/check the original project provenance. No ASUS materials were used.

| Asset / role | Source | Proposed treatment | Approval |
|---|---|---|---|
| Re-Gear wordmark | `src/assets/regear-header-logo.svg`, viewBox 0 0 640 160 | Existing asset at 104x26 in approximate header; no recolor | Reuse pending visual review |
| Portable mode | `src/assets/mode-handheld.svg`, viewBox 0 0 512 512 | Existing SVG at 34x34; decorative next to mode text | Reuse pending visual review |
| TV Docked mode | `src/assets/mode-tv.svg`, viewBox 0 0 512 512 | Existing SVG at 34x34; decorative next to mode text | Reuse pending visual review |
| eGPU module | Connection path from `src/quick-access-nav-row.tsx` | 24-unit vector at 22px, currentColor cyan | Reuse candidate |
| Auto TDP module | Gauge path from `src/quick-access-nav-row.tsx` | Same size/stroke as eGPU | Reuse candidate |
| Controller module | Controller path from `src/quick-access-nav-row.tsx` | Same size/stroke as eGPU | Reuse candidate |
| Troubleshoot | Tools path from `src/quick-access-overview.tsx` | Same size/stroke | Reuse candidate |
| Back, chevron, Stop | Native control glyphs | Text labels remain primary; use Decky/native icon conventions | Native integration review |
| Health/attention | Text, border and a small dot | No custom bitmap; health readable without color | Visual review |
| Modules | Labelled native button | No new custom symbol required | Visual review |
| Boosted Handheld | No custom asset generated | Reuse mode text until a distinct symbol materially helps | Optional future ChatGPT design |
| Restore Portable / disconnect | No custom artwork generated | Existing action label and native icon only if capability is approved | Conditional; no live-removal implication |

Dark background is the target SteamOS context. The fixture uses cyan vectors;
native selected/focused variants must retain contrast and visible focus. Decorative
SVG paths use aria-hidden; mode images have empty alt because adjacent text names
the state. The wordmark has Re-Gear alt text. No icon-only action depends on color.

The controller path in this fixture is a reuse candidate from the current row,
not a newly approved controller icon family. Use the source's authoritative path
when integrating. Original assets remain outside this task's ownership scope.

Custom ChatGPT artwork is optional, not a blocker for a native-control prototype.
If requested later: unified module vectors and an optional Boosted Handheld mark,
with source SVG, viewBox, license/provenance and exact approval revision. Do not
add Safe Disconnect artwork before its corresponding player action is justified.
