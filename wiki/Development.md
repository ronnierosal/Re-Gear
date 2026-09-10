# Development

**Audience:** contributors<br>
**Reviewed:** 2026-09-08<br>
**Maturity:** active development with safety-critical boundaries

Read [Contributing](https://github.com/ronnierosal/Re-Gear/blob/main/CONTRIBUTING.md),
the [development workflow](https://github.com/ronnierosal/Re-Gear/blob/main/docs/DEVELOPMENT.md),
and `AGENTS.md` before changing the repository.

## Working principles

- Keep changes small, reversible, and tied to one concrete problem.
- Preserve pure domain policy: no filesystem, subprocess, network, or OS calls
  under `backend/regear/domain`.
- Put product-specific identity and quirks in profiles or adapters.
- Never persist DRM card numbers, connector suffixes, or PCI bus addresses as
  identity.
- Add a focused regression test for meaningful fixes.
- Keep code/simulation proof separate from installed and hardware-tested proof.
- Do not broaden hardware authority or support claims from theoretical compatibility.

## Verification

Use focused checks while iterating. The minimum backend integration gate is:

```text
python scripts/check_architecture.py
python -m unittest discover -s tests -v
python -m compileall -q backend tests scripts
```

Frontend or package changes also need their documented typecheck, test, build,
and package checks. Documentation changes need local-link review and
`git diff --check`. Hardware-affecting changes require all local gates before a
separately approved supervised session with redacted before/live/after evidence.

## Coordination and publication

Follow [AGENTS.md](https://github.com/ronnierosal/Re-Gear/blob/main/AGENTS.md) and
the [agent lifecycle](https://github.com/ronnierosal/Re-Gear/blob/main/docs/AGENT_COORDINATION.md)
for isolated ownership, current PR claims, and validated routine integration.
Releases, hardware operations, and other high-risk changes retain their separate gates.

README introduces the project; Wiki guides explain it; repository docs own
contracts and exact evidence. The
[documentation workflow](https://github.com/ronnierosal/Re-Gear/blob/main/docs/DOCUMENTATION_WORKFLOW.md)
describes evidence handoffs and the separate Wiki publication/readback step.

## Working from current evidence

Use [Current State](Current-State) for the reviewed merged/open checkpoint and
inspect live PR state before integration. Historical draft-series reviews and
device records keep their dates. Passing against a stacked base is not proof of
combined main behavior, an installable build, or a successful device operation.

The earlier [disconnect review](https://github.com/ronnierosal/Re-Gear/blob/main/docs/DISCONNECT_PROGRESS_2026-09-06.md)
is historical evidence. It does not override newer merged work or authorize
resuming that session's hardware instructions.

## Writing troubleshooting guides

Use the lightweight
[troubleshooting and lessons template](https://github.com/ronnierosal/Re-Gear/blob/main/docs/templates/WIKI_TROUBLESHOOTING_TEMPLATE.md)
for recurring symptoms or device-specific investigations. Link the guide under
its feature and navigation; keep exact dates and evidence, distinguish likely
causes from observations, and preserve safety boundaries. Broader sections such
as performance and Offline Readiness can adopt it when there is a concrete
incident to explain; no placeholder pages are needed.
