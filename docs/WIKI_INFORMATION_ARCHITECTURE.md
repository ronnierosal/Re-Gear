# GitHub Wiki information architecture

The README introduces Re-Gear as a SteamOS handheld companion. The Wiki explains
features and usage. Repository docs own contracts, exact evidence and historical
records. Reviewed Wiki source is in [`wiki/`](../wiki/README.md); publication uses
the separate Git repository and live readback in [the documentation workflow](DOCUMENTATION_WORKFLOW.md).

## Information placement

| Layer | Keep here | Link elsewhere for |
|---|---|---|
| README | Project purpose, platform, short module summary, maturity, entry links, future real screenshots | Detailed mode/support tables, dated PR status, installation procedures and engineering history |
| Wiki | Feature benefits, implementation level, usage, limitations, priority and remaining validation | Exact technical contracts and original device/test evidence |
| Repository docs | Product/safety/architecture contracts, focused technical specifications, immutable dated evidence | Player-oriented explanations and active task ownership |
| Shared hub / GitHub | Task ownership, inbox handoffs, issues and PR state | Permanent engineering contracts and public feature guides |

## Guide map

`wiki/_Sidebar.md` is the navigation inventory. Preserve existing slugs, including
`How-HDM-Works`, so old links continue working. Do not publish `wiki/README.md`.

| Guides | Primary authority |
|---|---|
| Home, Project Overview, Feature Roadmap | PRODUCT, ROADMAP, verified merged/open evidence |
| Command Center | UI_SPEC and approved direction below; implementation PRs |
| eGPU and Docking; Safety and eGPU Handling | PRODUCT, SAFETY_INVARIANTS, HARDWARE_SUPPORT, deployment records |
| Performance and Power | TDP_CONTROL and merged power service/UI evidence |
| Controllers | PRODUCT/UI_SPEC; exact-device research and routing evidence |
| Offline Readiness | OFFLINE_EVIDENCE_SOURCE_REVIEW and OFFLINE_READINESS_UI |
| Current State; Issues Fixed | Dated engineering reconciliation, source and linked PR/test evidence |
| Supported Hardware; Confirmed Hardware Testing; device incident | HARDWARE_SUPPORT and original dated validation records |
| Getting Started; Development | DEVELOPMENT, DEPLOYMENT_VALIDATION, RELEASE_PIPELINE and AGENTS |
| Troubleshooting; FAQ; Diagnostics and Privacy; Help Improve Re-Gear | Relevant feature contracts, DIAGNOSTICS and SUPPORT_BUNDLE |

New guides require useful evidence-backed content. Research can be explained as
research; no empty placeholders, unavailable controls presented as working, or
support promises inferred from architecture.

## Command Center direction and screenshots

The approved layout uses a compact placement/display/game header; quick controls
for FPS, TDP, Auto TDP and display target; a prepared Safe Disconnect tile;
read-only eGPU/controller status links; and a Modules chooser for deeper settings.
This incorporates the later approved tile-grid refinement of the original plan.
It is design direction, not proof of a completed shell or supported backend.

Quick controls and module pages share state and action ownership. Opening status
is read-only. FPS needs a real provider; TDP options come from supported limits;
display actions retain guards. Safe Disconnect stays unavailable until a reviewed
backend capability and validation exist. Controller traversal, activation, Back
and focus restoration require native Decky validation.

The README reserves an HTML-comment location for future actual Command Center
screenshots. Add captures only when the implemented interface is reviewed; link
build/view and native validation evidence from the Wiki guide. Keep private game,
account and diagnostic details out. Prototype mockups remain clearly labelled
design concepts and never substitute for shipped-interface screenshots.

## Maintenance

Start feature pages with audience, evidence date and maturity. Describe benefit,
priority, implementation status and remaining validation. Keep volatile source
checkpoints in the Current State guide and link exact repository evidence;
historical device reports retain their original dates and limitations.

Before publication verify links, terminology, privacy, existing live changes and
the referenced merged source. Record source and Wiki revisions separately. Routine
factual updates follow standing delegation; no release, hardware, licensing or
readiness authority is created by editing documentation.

## Troubleshooting and lessons

Use [the lightweight template](templates/WIKI_TROUBLESHOOTING_TEMPLATE.md) for
who/what/when/where/why, symptoms, evidence, Re-Gear behavior, safe steps,
verification tiers and unresolved work. Dedicated Ally X/GPD G1 and Raikiri II
guides apply it now. Other major sections use the same pattern when concrete
evidence warrants a page; never publish empty placeholders or generic promises.
Link each page from its feature, Troubleshooting and navigation. Original dated
incident records remain independently linked evidence.
