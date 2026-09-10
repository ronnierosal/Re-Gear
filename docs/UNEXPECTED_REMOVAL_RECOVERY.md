# Unexpected removal recovery assessment

Status: **Implemented (pure evidence contract); Hardware Validation Required**

`regear.domain.unexpected_removal_recovery` compares explicit opaque-bound
before/after observations. It requires a verified docked bridge and topology
before the incident, then a newer matching-binding observation with both bridge
and external topology absent before it can report removal detected.

It separately requires verified internal display, built-in input, and internal
audio before it reports `portable_fallback_verified`. This reports only current
fallback evidence: it does not claim hardware recovery success, game survival,
or a relaunch outcome, and it never starts a recovery action.

Outcome categories are fail-closed:

- `portable_fallback_verified` requires confirmed removal, all three handheld
  fallback signals, and an observed stopped game session.
- `recovery_incomplete` reports confirmed removal where a known handheld
  fallback signal is missing, or loss is not confirmed.
- `needs_supervised_diagnosis` covers stale or changed bindings/generations,
  inconsistent samples, unknown facts, contradictory bridge/topology, and an
  unknown or running game state.

Game output is deliberately limited to `stopped_observed`, `running_observed`,
or `unknown`; none means that a game survived or failed. No collection,
persistence, watcher, action, deployment, or hardware mutation path is added.
