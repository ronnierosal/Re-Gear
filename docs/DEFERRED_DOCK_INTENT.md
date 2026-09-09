# Deferred dock intent

When a player directly requests Dock while the game state is exactly Running,
Re-Gear may retain one pure, bounded desired-action record. It carries only an
opaque player-request ID, source, opaque attach binding, and monotonic expiry.
It does not carry a game identity, hardware identity, display connector, or
transition plan.

The record is rejected for Idle or Unknown game evidence and for automatic
sources. It may be explicitly cancelled. It expires after a bounded interval
and is invalidated if the opaque attach binding changes, game evidence becomes
Unknown, or a fresh idle observation is unavailable.

On a fresh exact Idle result with the same attachment binding, the contract
returns a non-authorizing eligibility handoff containing the new observation
generation. A future owner must independently re-observe, validate capability,
obtain any required player consent, and use the unified transition engine. This
contract has no persistence, scheduler, poller, Decky RPC, remote authority,
display/GPU/audio/controller mechanism, or game-close action.
