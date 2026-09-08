# Getting started

**Audience:** prospective users and developers<br>
**Reviewed:** 2026-09-08<br>
**Maturity:** development-only; no general public release or supported installer

Check [Current State](Current-State), the repository [evidence index](https://github.com/ronnierosal/Re-Gear/blob/main/docs/INDEX.md)
and [deployment validation contract](https://github.com/ronnierosal/Re-Gear/blob/main/docs/DEPLOYMENT_VALIDATION.md)
before using a build.

## Development releases and compatibility

[GitHub releases](https://github.com/ronnierosal/Re-Gear/releases) include
development candidates. Publicly downloadable does not mean supported,
hardware-validated or Decky Store registered. The maintainer reports legacy use only on recent test devices; see the [compatibility note](Project-Overview).
The internal identity cutover is a separate implementation task; this documentation
update changes no installation.

## Players and hardware testers

Re-Gear is not ready for an ordinary self-service installation. Hardware-facing
builds are provenance-bound and validated in supervised sessions. Do not select
an archive by filename or age, copy an unverified build onto a handheld, or use
development commands as general install instructions.

If you are participating in a coordinated test:

1. Confirm the exact build revision and artifact checksum.
2. Begin from the documented Portable baseline.
3. Follow the installation baseline for your exact profile; current eGPU test builds require a powered-off detach before installation.
4. Use one watched transition at a time with a rollback plan.
5. Follow the documented disconnect policy. Current eGPU testing requires complete shutdown before physical disconnection.

## Developers

The repository uses Python for backend policy/adapters and TypeScript/React for
the Decky frontend. Read `AGENTS.md`, the
[documentation index](https://github.com/ronnierosal/Re-Gear/blob/main/docs/INDEX.md),
and [development workflow](https://github.com/ronnierosal/Re-Gear/blob/main/docs/DEVELOPMENT.md)
before editing.

Start with read-only local tests and fakes. Hardware mutation, deployment, and
support promotion require separate approval and evidence. See
[Development](Development) for the normal verification gates.
