# Wiki feature and guide template

Use this structure for substantive feature and guide pages. Start with a short
plain-language summary, then keep the two labelled audience sections below.
Navigation/index pages do not need artificial technical sections. Remove optional
subheadings that add no useful information; do not publish placeholders.

Use actual interface labels from merged code. Preserve demonstrated triggers and
timing. Keep general instructions hardware-neutral; put exact devices, transports,
builds and dates in evidence tables. Link shared explanations instead of repeating
them. Proposed, implemented, installed and hardware-tested are separate claims.
Use [evidence vocabulary](../INDEX.md#evidence-vocabulary) and the
[publication workflow](../../wiki/README.md#maintaining-the-published-wiki).

For investigations, reuse the evidence questions and verification table from the
[troubleshooting template](WIKI_TROUBLESHOOTING_TEMPLATE.md) inside these two
sections. Historical incident records retain their original dates and results.
See [Diagnostics and Privacy](../../wiki/Diagnostics-and-Privacy.md) for a filled example.

---

# [Feature or guide title]

[One or two sentences: what it does and why it helps.]

## For players — no technical background needed

### Availability and limits

[What readers can use today, what is unfinished, and what has not been verified.
Link Getting Started for installation eligibility. Explain any necessary terms.]

### How to use it

1. [Starting point and exact interface label; include relevant timing.]
2. [Next action and expected visible result.]

### If it does not work

[Recognizable symptom, safe next step and linked troubleshooting/reporting guide.
Do not invent a control, workaround, support claim or release date.]

## Technical details — for advanced users and contributors

### How it works

[Relevant architecture, dependencies, configuration and interfaces. Link owning
docs and code rather than copying the full specification.]

### Evidence and limits

| Evidence | What it establishes | Remaining limit |
|---|---|---|
| Merged source and tests: [revision / links] | [Specific behavior] | [What tests cannot establish] |
| Installed / hardware tested: [dated record or not verified] | [Exact context, if known] | [No extrapolation to other setups] |

[Known issues, technical troubleshooting and authoritative docs/tests/issues.
Date volatile claims; keep current task progress in the hub, not this template.]
