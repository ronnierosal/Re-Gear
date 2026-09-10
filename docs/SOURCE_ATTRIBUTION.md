# Source attribution

Re-Gear credits material external inspiration even when the implementation is
independent. This is the maintainer's transparency preference, not a claim that
every idea carries a legal attribution requirement. Copied or adapted material
also retains its applicable upstream notices and license conditions; an
acknowledgment does not replace them. See [licensing](LICENSING.md).

## During research and implementation

Record the following in the owning technical note or task, and summarize it in
the PR:

- Project and credited author/contributors as identified by the source.
- Source URL and exact revision/file or document section when available.
- The Re-Gear feature or files informed by that work.
- Reuse type: inspiration only, adapted/copied material, or dependency.
- For adaptation: what changed, when, and the applicable notices/license.

Material inspiration means a source that shaped the feature, design, or failure
handling. Routine syntax lookups do not need to become a credits catalog. Do not
invent sources or backfill unsupported claims about old code.

Describe provenance accurately. Reading a source does not automatically make
every later implementation an adaptation, but translating, rearranging, or
asking Codex/Claude to rewrite it does not establish independence. If the reuse
type is uncertain, record the uncertainty and review the actual change before
making an independence claim.

## Before delivery

Add or update [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) for the material
sources behind a delivered feature. State the specific contribution and include
a source link, using an immutable permalink when possible. Preserve file-level
notices for adapted material and trace earlier upstream attribution where relevant.
Keep source links in the owning technical document for detailed evidence.

Research references stay in research notes until there is an implementation to
credit; do not imply that a proposed feature has shipped. Do not imply endorsement
by the source project or claim that all code is original without evidence.

Example of an inspiration entry, only when independence is established:

> The design of [feature] was informed by [project and author], [source link and
> revision]. Re-Gear independently implements [specific behavior]. No source code
> or assets from that project were copied for this feature.

For adapted material, use “adapts [specific source/files]” instead, retain the
applicable notices and terms, and describe the modifications. Review code, tests,
text, assets and bundled dependencies separately where their provenance differs.

## Review check

The PR's Source credit section identifies the source, reuse type, and notice
location, or explicitly states that no material external source was used. Review
that statement against the change and research record. Link/notice checks can
verify recorded evidence; they cannot prove that every external influence was
disclosed or that AI output is independent.

This rule applies equally to Codex, Claude, and human contributions through the
shared [AGENTS.md](../AGENTS.md) contract. Active sessions must reload updated
instructions on resume; merging guidance does not update a running session's
already-loaded context automatically.
