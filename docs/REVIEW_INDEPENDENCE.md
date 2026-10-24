# Independent review without a required model provider

Ronnie directed on October 8, 2026 that Claude Code must no longer be a
mandatory code-review dependency. A separate Codex reviewer can review Codex
implementation. Independence comes from a separate reviewer session and its
assessment, rather than a required model family or paid provider subscription.
Historical Claude authorship and review evidence remain attributed accurately.

## Review contract

- The reviewer must be independent of the implementation owner and of anyone
  who authored or executed changes in the candidate. Record stable session
  identity and implementation/executor provenance; a changed label alone does
  not establish independence. Never submit self-approval.
- Review the exact head and comparison base. Record PASS or FAIL, findings,
  evidence URL and reviewer identity. New head/base invalidates old acceptance.
- Software evidence, required CI, ownership checks and protected GitHub approval
  rules remain required. Project review evidence does not replace a formal
  approval required by GitHub protections.
- Class C/D hardware evidence must match the tested source and immutable
  artifact. Class D additionally requires its explicit supervised procedure.
  Software review grants no device, deployment, release or merge authority.
- The policy change itself requires independent review before integration.

## Current and pending enforcement

At main source `88f7f832c2747e40103162e49ed6f5701c2aa1c4`,
`scripts/github_coordination.py` requires a nonempty reviewer identity distinct
from the task owner and exact PASS evidence. It does not require Claude or an
opposite model family. Session independence is a cooperative recorded contract;
the validator does not authenticate model/session provenance.

The unmerged orchestration proposal in PR #458 adds opposite-family routing and
eligibility rules. That proposal must be updated by its owner or an explicitly
accepted successor before activation: replace its mandatory family dependency
with independent-session review, default review routing to available Codex
reviewers, and retain author exclusion, trusted actor checks, exact revisions,
fresh evidence, CI and hardware/procedure gates. Historical agent names remain
valid for records; removing a subscription dependency does not erase history.

Task #481 records this user-directed transition and disjoint current-main
regressions. Task #456 retains ownership of pending orchestration paths until an
accepted handoff. No owned branch, workflow or repository protection is changed
by this document. See [agent coordination](AGENT_COORDINATION.md) and the
[concurrent development runbook](CONTINUOUS_DEVELOPMENT.md).
