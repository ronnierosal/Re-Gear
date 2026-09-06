# Getting started

**Audience:** prospective users and developers<br>
**Reviewed:** 2026-09-06<br>
**Maturity:** development-only; no general public release or supported installer

Check the [README candidate status](https://github.com/ronnierosal/Re-Gear#-current-status), the repository [current state](https://github.com/ronnierosal/Re-Gear/blob/main/docs/CURRENT_STATE.md)
and [deployment validation contract](https://github.com/ronnierosal/Re-Gear/blob/main/docs/DEPLOYMENT_VALIDATION.md)
before using a build.

## Players and hardware testers

Re-Gear is not ready for an ordinary self-service installation. Hardware-facing
builds are provenance-bound and validated in supervised sessions. Do not select
an archive by filename or age, copy an unverified build onto a handheld, or use
development commands as general install instructions.

If you are participating in a coordinated test:

1. Confirm the exact build revision and artifact checksum.
2. Begin from the documented Portable baseline.
3. Keep the GPD G1 disconnected during installation.
4. Use one watched transition at a time with a rollback plan.
5. Shut down before physically disconnecting the G1.

## Developers

The repository uses Python for backend policy/adapters and TypeScript/React for
the Decky frontend. Read `AGENTS.md`, the
[documentation index](https://github.com/ronnierosal/Re-Gear/blob/main/docs/INDEX.md),
and [development workflow](https://github.com/ronnierosal/Re-Gear/blob/main/docs/DEVELOPMENT.md)
before editing.

Start with read-only local tests and fakes. Hardware mutation, deployment, and
support promotion require separate approval and evidence. See
[Development](Development) for the normal verification gates.
