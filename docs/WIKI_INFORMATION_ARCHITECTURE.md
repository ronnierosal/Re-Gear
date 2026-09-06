# GitHub Wiki information architecture

The Wiki is the human guide; repository docs remain engineering authority. Its
reviewed source lives in [`wiki/`](../wiki/README.md).
Create pages only when useful content exists, and link back to the owning
repository contract rather than duplicating it.

## Current source set

The [live Wiki](https://github.com/ronnierosal/Re-Gear/wiki) was populated with
14 guides and a sidebar on 2026-09-06, including Offline Readiness. Reviewed
source remains in `wiki/`; the separate Wiki repository requires an explicit
publication step. See the [maintenance workflow](../wiki/README.md#maintaining-the-published-wiki).

The source set contains Home, Project Overview, Current State, Issues
Fixed, Getting Started, How HDM Works, Supported Hardware, Safety and eGPU
Handling, Diagnostics and Privacy, Troubleshooting, Development, FAQ, and the
dated Ally X/GPD G1 docking incident. The
combined safety page covers connection, disconnect, and sleep guidance until
each workflow has enough independently proven player content to justify its own
page.

`wiki/_Sidebar.md` defines navigation. `wiki/README.md` records publishing and
authority rules and is not intended to replace the Wiki Home page. Publication
or synchronization to GitHub requires explicit maintainer authorization for
each publishing task.

## Initial publish set

| Page | Purpose | Repository authority |
|---|---|---|
| Home | Product promise, maturity, placements, safe navigation | `README.md`, `PRODUCT.md` |
| Project Overview | Goals, non-goals, workflow, and profile direction | `PRODUCT.md`, `ARCHITECTURE.md` |
| Current State | Evidence-aware implementation and hardware snapshot | `CURRENT_STATE.md`, `ROADMAP.md` |
| Issues Fixed | Selected fixes with proof level and remaining gates | `CURRENT_STATE.md`, audit and validation records |
| Ally X and GPD G1 Docking Incident | Full causal chain, fixes, evidence, and reusable diagnostic lessons | dated incident record, `CURRENT_STATE.md` |
| Getting Started | Current availability, prerequisites, development-only install status | `CURRENT_STATE.md`, `DEPLOYMENT_VALIDATION.md` |
| How HDM Works | Plain-language placement/health/workflow model | `PRODUCT.md`, `ARCHITECTURE.md` |
| Supported Hardware | Compatibility vocabulary and current profile | `HARDWARE_SUPPORT.md` |
| Safety and eGPU Handling | Current connect, sleep, and shutdown-before-disconnect rules | `SAFETY_INVARIANTS.md`, `DEPLOYMENT_VALIDATION.md` |
| Diagnostics and Privacy | Bounded privacy-safe evidence and support sharing | `DIAGNOSTICS.md`, `SUPPORT_BUNDLE.md` |
| Troubleshooting | Symptom-to-diagnostic guidance without raw log dumping | `DIAGNOSTICS.md`, recovery docs |
| Development | Contributor entry point | `CONTRIBUTING.md`, `docs/DEVELOPMENT.md` |
| FAQ | Repeated user questions with links to authority | owning repository documents |

## Add after evidence exists

- Gaming with an eGPU
- Portable Mode
- Boosted Handheld Mode
- TV Docked Mode
- Connecting an eGPU
- Disconnecting an eGPU
- Sleep & Wake
- Controllers
- Display / HDR / VRR
- Audio
- Compatibility Matrix
- ASUS ROG Ally X
- GPD G1

These pages should not be empty placeholders or imply certification before their
workflows have evidence.

## Page rules

- Start with audience, evidence date, and maturity.
- Link to the authoritative repository document near the top.
- Use player language and short procedures.
- Do not reproduce volatile commit/build/deployment values; link to
  `CURRENT_STATE.md`.
- Do not put engineering invariants, secrets, SSH coordinates, raw identities,
  or unpublished recovery procedures only in the Wiki.
- Review Wiki pages when the owning repository contract materially changes.
