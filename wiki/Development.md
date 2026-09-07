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

## Disconnect work review checkpoint

Existing resource-release work is published as draft PRs. Use
[issue #55](https://github.com/ronnierosal/Re-Gear/issues/55) for the dependency map
through #81 and [issue #51](https://github.com/ronnierosal/Re-Gear/issues/51) for
remaining experiment acceptance. The staged 0.3.56 candidate is
[PR #82](https://github.com/ronnierosal/Re-Gear/pull/82); it follows a separate
trial/diagnostics/return-control branch and excludes the experimental filter series.

The September 6 review checked 26 G1/audio drafts in the #53–#82 range: 25 had
successful foundation checks. [PR #62](https://github.com/ronnierosal/Re-Gear/pull/62)
failed committed frontend source-map verification; [issue #59](https://github.com/ronnierosal/Re-Gear/issues/59)
tracks the required repair and installed acceptance. Recheck live CI before review
or integration. Passing against a stacked base is not proof of integration with main.

Publication is complete for the recorded series; review/integration, audio runtime
activation, software removal, and hardware evidence remain separate open work.
The maintainer has prioritized GitHub review and documentation before hardware
continuation. See the [dated review notes](https://github.com/ronnierosal/Re-Gear/blob/codex/disconnect-progress-docs/docs/DISCONNECT_PROGRESS_2026-09-06.md)
for exact candidate provenance, verification scope, and remaining gates.
