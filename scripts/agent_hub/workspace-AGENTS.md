# Re-Gear workspace entry point

At start/resume, refresh policy refs with `git -C main fetch origin`, then read
`git -C main show origin/main:AGENTS.md` and
`git -C main show origin/main:docs/AGENT_COORDINATION.md`. The shared checkout can
lag behind merged policy; fetching does not change its checked-out files. If the
remote is unavailable, use the cached ref and record that limitation; if no ref
exists, fall back to `main/AGENTS.md` and its linked lifecycle. Then read the
selected worktree's owning documents. Use the one root `agent-hub/` for status, inbox,
claims and accepted transfers; read its README on first use. Never implement in
shared main or modify another session's checkout. Existing sessions must reload
these instructions on resume. Old `AGENT_NOTES.md` entries are historical context;
verify current hub and issue/PR state before treating them as live claims.
