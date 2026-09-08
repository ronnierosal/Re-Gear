# Review 01 asset manifest

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
