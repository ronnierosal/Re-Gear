# Re-Gear Wiki source

This directory is the reviewed source for the Re-Gear GitHub Wiki.
The player guide is published at [Re-Gear Wiki](https://github.com/ronnierosal/Re-Gear/wiki).
It is not the engineering source of truth. Start at [Home](Home.md).

Repository contracts own product, safety, architecture, support, and current
implementation claims. Wiki pages explain those contracts in shorter player and
contributor language and link back to them. When a Wiki page conflicts with a
repository contract, verify current evidence and correct the owning repository
document before updating the Wiki.

## Publishing rules

- Do not publish, push, or sync these pages without maintainer authorization.
- Preserve the evidence labels: designed, implemented, simulated, installed,
  hardware tested, certified, and unknown.
- Never turn a code or simulation result into a hardware-support claim.
- Do not include SSH coordinates, local paths, raw logs, support bundles,
  account identifiers, or stable hardware identifiers.
- Re-review a page whenever its linked authority materially changes.
- Publish only useful pages; do not create empty feature placeholders.

The planned information architecture and review rules are recorded in
[the repository Wiki plan](../docs/WIKI_INFORMATION_ARCHITECTURE.md).

## Maintaining the published Wiki

The initial 14 guides and sidebar were published on 2026-09-06. GitHub keeps
the live Wiki in a separate Git repository; changes here do not sync automatically.

For an authorized documentation update:

1. Review the owning documents and exact candidate branch, then update these pages.
2. Preserve historical incident dates and link version details to the README.
3. Check page links, evidence labels, and private-data exclusions.
4. Clone or pull `https://github.com/ronnierosal/Re-Gear.wiki.git`, inspect live
   edits, and copy reviewed page Markdown plus `_Sidebar.md`. Do not publish this
   README as a Wiki page or overwrite unrelated live changes.
5. Commit with a public GitHub no-reply identity, push without force, and verify
   live content and navigation. Keep these repository sources synchronized.

Release and player-visible behavior changes should include a review of affected
guides. GitHub Issues owns bug tracking; the Wiki explains behavior and links to
evidence. No automatic publication job is configured.
