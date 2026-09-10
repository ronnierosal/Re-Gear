# Wiki troubleshooting and lessons template

Use this template for a recurring symptom or a device-specific investigation
with enough evidence to help readers. It keeps the broad feature guide readable
while preserving what happened, why, and what is actually verified. Copy the
structure into a descriptive `wiki/` page and link it from its feature guide
and the sidebar. Do not publish this template itself or empty placeholder pages.

Authoring rules:

- Use dates, exact test context and evidence links where they affect the claim.
- Distinguish observation, source-backed cause, and hypothesis; say when the cause is unknown.
- Separate source, merged, installed and hardware-tested status. Never infer device proof from code, mocks, a PR state, or another transport/model.
- Record missing evidence explicitly. A filled template is not a live status assertion; retained incident dates remain historical.
- Keep steps safe and useful for players. Link reviewed diagnostics; omit raw device writes, privileged recovery commands, forced shutdown recipes and private identifiers.
- Preserve current safety and approval boundaries. A workaround must not bypass them.
- Link issues/PRs for active work and the original dated record for history. Recheck before changing “fixed” or support wording.

---

# [Symptom or device] troubleshooting

**Audience:** [readers]<br>
**Evidence reviewed:** [date]<br>
**Maturity:** [supported explanation / investigation / bounded validation]

## 1. Scope / who this helps

[Affected users, exact models/transports where relevant, and what is outside scope.]

## 2. Situation (what / where / when)

[Test date, platform/build context, intended action and evidence provenance.]

## 3. Symptoms

[Observed behavior, including what was independently confirmed.]

## 4. Evidence and likely cause

[Original evidence links. Separate confirmed causes from hypotheses and unknowns.]

## 5. What Re-Gear does

[Implemented fixes/guards and intended behavior. Distinguish unfinished work.]

## 6. Steps to try

[Safe user-facing checks and reviewed diagnostic/reporting path. State stop conditions.]

## 7. Verification status

| Evidence level | What is established | What is not established |
|---|---|---|
| Source / tests | [specific result or unknown] | [limits] |
| Merged | [PR/commit or pending] | [limits] |
| Installed | [exact observed build/date or unknown] | [limits] |
| Hardware tested | [exact context/date/result or none] | [limits] |

## 8. Known limits / unresolved work

[Open questions, issue links and the next evidence needed; no promised dates.]

## 9. Related guides / issues / PRs

[Parent feature guide, safety/diagnostic guide, source contract and original incident.]
