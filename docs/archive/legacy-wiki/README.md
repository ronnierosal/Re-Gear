> **Archived September 14, 2026.** Historical source at `9421c6f`; superseded by the [canonical Wiki](https://github.com/ronnierosal/Re-Gear/tree/main/docs/wiki). Do not use this as current instructions.

# Re-Gear Wiki source

This directory is the reviewed source for the Re-Gear GitHub Wiki.
The player guide is published at [Re-Gear Wiki](https://github.com/ronnierosal/Re-Gear/wiki).
It is not the engineering source of truth. Start at [Home](Home.md).

The repository is named Re-Gear. Existing Wiki slugs, including How-HDM-Works,
are retained for link compatibility. Historical HDM references identify the same
project; see [branding compatibility](https://github.com/ronnierosal/Re-Gear/blob/9421c6f4f33dd22a0fc55857fb544e36d0a43d7f/docs/BRANDING.md).

Repository contracts own product, safety, architecture, support, and current
implementation claims. Wiki pages explain those contracts in shorter player and
contributor language and link back to them. When a Wiki page conflicts with a
repository contract, verify current evidence and correct the owning repository
document before updating the Wiki.

## Publishing rules

- Codex/ChatGPT owns routine evidence-backed publication under the standing
  delegation in [AGENTS.md](https://github.com/ronnierosal/Re-Gear/blob/9421c6f4f33dd22a0fc55857fb544e36d0a43d7f/AGENTS.md#public-documentation). Follow the
  [shared documentation workflow](https://github.com/ronnierosal/Re-Gear/blob/9421c6f4f33dd22a0fc55857fb544e36d0a43d7f/docs/DOCUMENTATION_WORKFLOW.md) for review
  and the narrow human-approval boundaries; do not request approval per update.
- Preserve the evidence labels: designed, implemented, simulated, installed,
  hardware tested, certified, and unknown.
- Never turn a code or simulation result into a hardware-support claim.
- Do not include SSH coordinates, local paths, raw logs, support bundles,
  account identifiers, or stable hardware identifiers.
- Re-review a page whenever its linked authority materially changes.
- Publish only useful pages; do not create empty feature placeholders.

The planned information architecture and review rules are recorded in
[the repository Wiki plan](https://github.com/ronnierosal/Re-Gear/blob/9421c6f4f33dd22a0fc55857fb544e36d0a43d7f/docs/WIKI_INFORMATION_ARCHITECTURE.md).

## Maintaining the published Wiki

The initial 14 guides and sidebar were published on 2026-09-06. GitHub keeps
the live Wiki in a separate Git repository; changes here do not sync automatically.

For a routine delegated documentation update:

1. Review the owning documents and exact candidate branch, then update these pages.
2. Preserve historical incident dates and link exact version/evidence details to
   repository technical records. Publish only after referenced files are on main.
3. Check page links, evidence labels, and private-data exclusions.
4. Clone or pull `https://github.com/ronnierosal/Re-Gear.wiki.git`, inspect live
   edits, and copy reviewed page Markdown plus `_Sidebar.md`. Do not publish this
   README as a Wiki page or overwrite unrelated live changes.
5. Commit with a public GitHub no-reply identity, push without force, and verify
   live content and navigation. Keep these repository sources synchronized.

The README introduces the overall project. Feature guides in this Wiki carry
module details, evidence labels and usage limits; `Home.md` and `_Sidebar.md`
route readers to them. The Command Center guide owns screenshot context; the
README can show reviewed real captures once the interface is validated. Keep
mockups labelled as design work. See the [information map](https://github.com/ronnierosal/Re-Gear/blob/9421c6f4f33dd22a0fc55857fb544e36d0a43d7f/docs/WIKI_INFORMATION_ARCHITECTURE.md).

Release and player-visible behavior changes should include a review of affected
guides. GitHub Issues owns bug tracking; the Wiki explains behavior and links to
evidence. No automatic publication job is configured.

## Troubleshooting authoring

Use [the feature and guide template](https://github.com/ronnierosal/Re-Gear/blob/9421c6f4f33dd22a0fc55857fb544e36d0a43d7f/docs/templates/WIKI_FEATURE_TEMPLATE.md)
for substantive pages: a short plain-language summary, **For players — no
technical background needed**, and **Technical details — for advanced users and
contributors**. Keep sections proportional, use actual interface labels, and link
shared explanations. Navigation pages do not need artificial technical sections.
[Diagnostics and Privacy](Diagnostics-and-Privacy.md) is the worked example.

Use [the repository troubleshooting/lessons template](https://github.com/ronnierosal/Re-Gear/blob/9421c6f4f33dd22a0fc55857fb544e36d0a43d7f/docs/templates/WIKI_TROUBLESHOOTING_TEMPLATE.md)
when a feature has a recurring symptom or enough device-specific evidence for a
useful guide. Link it from its parent feature and `_Sidebar.md`; preserve source,
merged, installed and hardware-tested distinctions. The template stays in the
repository and is never published as a status page.
