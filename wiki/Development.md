# Development

**Audience:** contributors<br>
**Reviewed:** 2026-09-06<br>
**Maturity:** active development with safety-critical boundaries

Read [Contributing](https://github.com/ronnierosal/Re-Gear/blob/main/CONTRIBUTING.md),
the [development workflow](https://github.com/ronnierosal/Re-Gear/blob/main/docs/DEVELOPMENT.md),
and `AGENTS.md` before changing the repository.

## Working principles

- Keep changes small, reversible, and tied to one concrete problem.
- Preserve pure domain policy: no filesystem, subprocess, network, or OS calls
  under `backend/hdm/domain`.
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

Maintainers control pushes, tags, releases, Decky publication, history rewrites,
and hardware deployment.
