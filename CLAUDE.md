# Claude Code project entry point

Codex, Claude Code, and multiple chats work concurrently on Re-Gear.
Read and follow [AGENTS.md](AGENTS.md) and the shared
[coordination playbook](docs/CHAT_COORDINATION.md) before editing and whenever
resuming work. These are the common project rules for every agent; this file
does not define a separate Claude policy.

Every code change needs a GitHub issue, an explicit owner and file scope,
its own worktree/branch, and a linked PR. Check current claims and overlapping
PRs first. Preserve other agents' work; coordinate shared-file edits and verify
the combined behavior before integration. Never infer merge or hardware
authorization from permission to implement a change.
