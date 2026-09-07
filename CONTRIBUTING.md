# Contributing to Re-Gear

Re-Gear is an early, safety-conscious SteamOS project. Contributions are welcome
when they keep behavior evidence-based, changes focused, and hardware claims
honest.

Use the Re-Gear display name; preserve legacy technical identifiers as described
in [branding and compatibility](docs/BRANDING.md).

## Before changing code

Read:

- `AGENTS.md`
- [Documentation and authority](docs/INDEX.md)
- [Current state](docs/CURRENT_STATE.md)
- [Development workflow](docs/DEVELOPMENT.md)
- the product, architecture, safety, and hardware documents for your area

Open an issue before a large architecture, state-machine, UI, hardware-profile,
or deployment redesign. A proposal does not imply that hardware behavior is
implemented or supported.

## Changes

- Keep one problem and its tests/docs in each pull request.
- Preserve unrelated worktree changes.
- Add a regression test when fixing a meaningful defect where practical.
- Use targeted checks while iterating and the appropriate integration gate
  before handoff.
- Do not broaden hardware support based on theoretical compatibility or
  simulation.
- Do not include credentials, addresses, raw device identity, private paths,
  support bundles, or unredacted logs.

Pull requests should state the problem, approach, tests, affected workflows or
hardware, evidence level, and documentation impact. Hardware-affecting changes
need a separately coordinated supervised validation plan; a contributor is not
expected to own the maintainer's Ally/G1 session.

## Git and releases

Small local commits are encouraged. Maintainers control branch integration,
pushes, tags, releases, Decky publication, and hardware deployment. Generated
`dist/` outputs are intentional package inputs; `out/` archives are not tracked.

See [Development workflow](docs/DEVELOPMENT.md) for commands and Git rules.
