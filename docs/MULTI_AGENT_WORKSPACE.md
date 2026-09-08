# Multi-agent workspace layout

Concurrent assistants (Claude, ChatGPT/Codex, and any later worker) share one
Re-Gear repository through separate Git worktrees. This page defines that
on-disk layout and the setup tool. Branch, ready-ledger, and release rules stay
in [chat coordination](CHAT_COORDINATION.md); ownership rules stay in
`AGENTS.md` and [development](DEVELOPMENT.md).

## Layout

```text
<workspace>/Re-Gear/
├── main/     integration checkout tracking main
├── codex/    ChatGPT/Codex dedicated worktree
└── claude/   Claude dedicated worktree
```

One repository, one object store, three checkouts. Refs under `refs/regear/`
are shared by every worktree, so the release ledger works across agents without
a second clone. On Windows the workspace is a normal path, for example
`C:\Users\SLDD\AI-Dev\Re-Gear`; the tool is path-agnostic.

Each agent slot holds a task-specific branch named `agent/<agent>-<scope>`, for
example `agent/claude-dock-telemetry`. No agent works directly on `main` unless
a driver explicitly asks for it.

## Setup tool

`scripts/setup_agent_worktrees.py` inspects the layout and creates only the
slots that are missing.

```text
python scripts/setup_agent_worktrees.py inspect
python scripts/setup_agent_worktrees.py plan  --layout-root <workspace>/Re-Gear
python scripts/setup_agent_worktrees.py apply --layout-root <workspace>/Re-Gear --scope dock-telemetry
python scripts/setup_agent_worktrees.py apply --slot claude
```

`--layout-root` may be omitted when the current checkout already sits in a
`main/`, `codex/`, or `claude/` directory; the parent is then the layout root.
`inspect` and `plan` never write. `apply` creates worktrees and nothing else.

Every run first prints the repository branch, HEAD, clean/dirty state, and the
full worktree list, so ownership is visible before any change.

### Slot states

| State | Meaning | Action |
|---|---|---|
| `registered` | Already a worktree of this repository | None |
| `missing` | Path does not exist | Create worktree on the slot branch |
| `occupied` | Path exists with contents, not a worktree here | None; reported for a human decision |
| `blocked-file` | Path exists as a file | None; reported |
| `branch-elsewhere` | Slot branch is checked out in another worktree | None; reported with the owning path |

The tool is additive by construction. It never deletes, moves, resets, cleans,
force-checks-out, prunes, or rewrites history, and it never reads or edits the
contents of another agent's slot. An existing checkout that is not already in a
slot is reported, never relocated: moving a checkout that may hold uncommitted
work is a human decision, and the safe migration is to add the new slots beside
it and let its owner finish and commit first.

## Multi-agent safety rules

- Inspect branch, worktree list, status, recent commits, and remote state before
  editing anything.
- Work only inside your own slot. Never edit, reset, clean, or delete another
  agent's worktree or branch.
- Never `git clean -fdx`, force-push a shared branch, or rewrite shared history.
- Consume another agent's work only through a committed branch or a reviewed
  diff, never by absorbing their uncommitted files.
- When a task overlaps files another agent is currently changing, stop editing
  the overlapping files and report the conflict instead of overwriting them.
- Merging into `main` requires explicit authorization from the integration
  driver.

## Verification

```text
python -m unittest tests.test_agent_worktrees -v
```

The tests cover slot classification, single-creation idempotency, refusal on an
occupied path with preserved contents, and reporting rather than reclaiming a
branch checked out elsewhere.
