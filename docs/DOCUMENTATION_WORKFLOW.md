# Documentation and project communications

## How this works

Engineering owners finish tasks with concise evidence and one documentation-impact
line. Codex/ChatGPT reviews `hub.ps1 docs-queue`, claims an ordinary documentation
task, verifies the evidence, and updates the appropriate public layer. No separate
tracker, scheduled job, polished engineering write-up or automatic post is needed.

## Ownership and layers

| Layer | Owner and purpose | Update trigger |
|---|---|---|
| README | Codex/ChatGPT: what Re-Gear is; stable project story, platform, modules, getting started, visuals and links | Material verified change to the landing-page summary, entry links or availability; usually infrequent |
| Wiki (`wiki/` reviewed source) | Codex/ChatGPT: how Re-Gear works; detailed module, architecture, compatibility, usage, limitations and validation explanations | Merged behavior/contract change, verified test evidence, corrected status, troubleshooting or navigation |
| Discussions | Codex/ChatGPT: what is happening; concise milestones, factual progress, feedback and testing calls | Meaningful news worth communicating; not every commit or typo |
| Code, tests, technical `docs/`, task evidence | Engineering task owner, primarily Claude | Keep affected implementation contracts and results accurate as part of coding |

README summarizes and links. Wiki explains and cites. Discussions give a dated
update and link to Wiki/evidence rather than copying it. Issues track bugs; hub
tasks track local ownership. Existing Wiki source is a deliberate publication
mirror, not a second independent engineering authority.

For current implementation claims, verify in this order: merged code; validated
tests/artifacts/device evidence; completed task records; technical docs; Wiki;
README; Discussions. Intended safety/product contracts still define required
behavior: a bug in code does not silently change the contract. Never change
engineering behavior merely to match an outdated public page. A `done` task or
a passing simulation alone does not prove merge, installation or hardware safety.

## What Claude (or any implementation owner) records

Keep the existing task title/owner. At completion put a few factual lines in its
`note`: result, important behavior change and known limitations, ending with:

```text
Documentation impact: Wiki
```

Allowed impact values are `none`, `README`, `Wiki`, `Discussion`, `multiple`
(case-insensitive). Use one standalone line. This is a routing hint, not a promise
to publish or a substitute for evidence. Omitted, malformed or conflicting labels
appear as `unassessed`; the docs owner decides, so uncertainty does not block coding.

Use `evidence` for exact commit/PR and merge state, tests and results, and relevant
technical-record links. State unverified behavior plainly. No marketing copy,
README edits, Wiki sync or Discussion post is required from the coding owner.
Internal contract corrections remain part of implementation when necessary.
Copy [completion.example.json](../scripts/agent_hub/completion.example.json) and
replace every placeholder/current revision before applying it through the hub.

## Codex/ChatGPT review

1. At an explicitly started docs session or milestone, read shared status/inbox
   and run `hub.ps1 docs-queue`. There is no background polling. Also inspect
   relevant merged PRs and existing docs tasks, including older tasks labelled
   `none` if a known stale page warrants rechecking.
2. Inspect source-task acceptance, exact commits/PR merge status, tests and
   evidence. Check candidate vs installed vs hardware-tested facts separately.
   If evidence conflicts, record the specific missing proof and a blocker; do
   not promote a capability. Historical reports stay dated historical evidence.
3. Reuse a linked documentation review, or create one in stream `documentation`.
   Use a stable ID such as `docs-<source-id>`, source task in `dependencies`, and
   an exact standalone `Documentation review: <source-id>` line in `note`.
   For long IDs choose a short stable name. Search existing tasks before creation;
   identical-ID creation and claims remain atomic. Multiple source dependencies
   may share one review; add one review line per source. Claim before editing.
4. Choose README, Wiki, Discussion, several, or no public change. The original
   impact is advisory. Record that decision/reason in the review, retaining the
   review marker. Use [review.example.json](../scripts/agent_hub/review.example.json).
5. Validate source links, version/evidence labels, privacy, terminology, navigation
   and exact diff. Preview Markdown where layout changes. Apply `DEVELOPMENT.md`
   and the shared ownership/merge gates. Publish only after referenced repository
   evidence is accessible; record source commit separately from publication proof.
6. Complete the review with affected URLs/revisions and live readback, or an
   explicit no-change/deferred decision with rationale and linked follow-up.
   If publication is intended but blocked, keep `blocked`/`review`; do not claim
   it happened. Old engineering tasks remain immutable. A terminal review with
   that source dependency and marker clears it from `docs-queue`.

The queue includes only completed tasks outside the documentation stream. Docs
stream tasks already constitute the review workload; this prevents recursion.
Active/blocked/review/cancelled reviews remain visible beside their source. A
cancelled review does not clear it: create a linked successor with a new ID.
The queue is read-only and never modifies receipts, owns tasks or publishes.

## Publishing and approvals

`AGENTS.md` delegates routine factual README/Wiki updates and normal development
Discussion posts to Codex/ChatGPT. Typo/link/navigation fixes, verified status or
compatibility corrections, and explanations flowing from merged validated work
need no new human approval. Material readiness changes require human review when
the evidence leaves consequential uncertainty. Do not promise dates or support.
Positioning, personal announcements, licensing, major roadmap commitments and
public promises use the human-review boundaries in `AGENTS.md`. This policy
supersedes older per-update Wiki approval wording, including pending drafts.
It does not bypass tool permissions or delegate release/hardware actions.

**Wiki:** follow the separate-repository synchronization procedure in
[`wiki/README.md`](../wiki/README.md#maintaining-the-published-wiki), under the
standing delegation above. Inspect live edits before copying only reviewed pages;
never bulk overwrite the Wiki, publish its source README, or force-push. Preserve
historical dates and compatibility slugs. Verify live page content/navigation and
record the Wiki commit/URL; a repository commit alone is not publication proof.
Use the exact technical evidence as the version source, not the README summary.

**Discussions:** inspect existing topics/categories and search for duplicates.
Use an existing thread for continuing the same milestone; use an appropriate
existing category for a distinct update. Draft a short factual summary: what
changed, exact evidence links, what remains unverified, and a focused feedback
request if useful. Plans/testing calls must be labelled as such and must not
invite unsafe hardware actions. Do not speak as Ronnie or imply a release from
CI artifacts. Verify the posted content/URL and record it in review evidence.
If topic inventory or publishing access is unavailable, retain a draft and the
specific blocker; do not post blindly or claim there are no existing discussions.
Follow `COMMUNITY_ATTACHMENT_SAFETY.md` when handling community evidence.

## Next documentation work

[Wiki information architecture](WIKI_INFORMATION_ARCHITECTURE.md) records the
approved modular Command Center direction without claiming implementation.
[Cleanup inventory](DOCUMENTATION_CLEANUP.md) captures the one-time reconciliation,
README/Wiki overlap and live-publication gaps. Those are subsequent tasks; this
workflow does not start a README redesign, UI implementation or hardware work.
