# Scripts, tests and CI gates

Different checks answer different questions. A read-only readiness report cannot
prove that a player pressed a button or that a physical disconnect succeeded.

## For players — no technical background needed

You do not need these commands for normal use. Start with
[troubleshooting](../player/troubleshooting.md). A green developer check means its
specific test passed; it does not mean every feature works on your handheld.

## Technical details — for advanced users and contributors

### What the readiness probe actually does

[`probe_safe_undock_readiness.py`](../../../scripts/probe_safe_undock_readiness.py)
is read-only. At the reviewed source, its comment at line 228 explains why it
constructs its own `SnapshotService` at line 232 with
`SteamOsPeripheralObservationAdapter`: `DiagnosticsApi` deliberately wires
discovery only and omits the peripheral observer needed for controller/audio
readiness. The probe observes, describes and prints a report. It does not call
the disconnect RPC or perform a disconnect.

Prior read-only Codex probe runs provide evidence about observation, mechanism
assessment and readiness logic. They do **not** validate the mounted button path,
release/remove execution, or physical unplug. Even `--exit-on removal-safety`
only selects the narrower verdict used for the process exit status; it does not
execute removal. Default zero means full readiness for revalidation, not cable
clearance. Refer to [Safe Undock readiness](../../SAFE_UNDOCK_READINESS.md).

The [0.3.98 checkpoint](../../EGPU_0398_CHECKPOINT.md) separately records an actual
user button press followed by observed teardown and supervised physical unplug/
replug. Do not attribute that stronger evidence to the read-only probe.

### Local checks and their limits

Run from the repository root, in an isolated integration worktree:

| Check | What it establishes | What it does not establish |
|---|---|---|
| `python scripts/check_docs_links.py` | Local Markdown targets and documentation discoverability | Remote URL uptime, factual truth or hardware behavior |
| `python scripts/check_architecture.py` | Enforced source dependency/command boundaries | Complete runtime correctness |
| `python -m unittest discover -s tests -v` | Backend unit and fixture behavior | Device behavior; report platform skips separately |
| `python scripts/check_golden_behaviors.py` | Every required manifest test runs without failure, skip or expected failure | Full lifecycle certification or baseline promotion |
| `python -m compileall -q backend tests scripts` | Python syntax/import bytecode compilation | Every referenced name or execution path works |
| `pnpm typecheck`, `pnpm test:frontend`, `pnpm build` | Frontend type, fixture and bundle checks | Native Steam/Decky mounting, controller focus or installed display behavior |
| `python scripts/check_integration_preflight.py` | Clean integration branch containing current fetched main | Ownership approval, semantic review or hardware clearance |

### CI execution

The authoritative sequence is [`.github/workflows/ci.yml`](../../../.github/workflows/ci.yml).
Its `foundation` job builds the UI before tests that inspect generated `dist/`,
checks architecture, runs backend/frontend tests and compilation, checks selected
undefined/redefined-name errors, and validates package/source hygiene. Golden tests
run through normal unittest discovery; their runner rejects empty or skipped
required suites.

Linux root fixtures exercise privileged filesystem and admission boundaries in
isolated fake trees/chroots. They are not trials against a real dock. The separate
[privileged delivery workflow](../../../.github/workflows/privileged-user-delivery.yml)
must also pass where required. Read the exact run and revision, not an older green
badge. Preserve independent review, current base, rollback and hardware limits in
the handoff; see [Development](../../DEVELOPMENT.md) and
[golden behavior preservation](../../GOLDEN_BEHAVIORS.md).
