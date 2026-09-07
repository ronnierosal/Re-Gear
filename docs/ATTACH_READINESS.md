# eGPU attach readiness

Re-Gear's exact topology detector can observe an eGPU attach. A bounded USB4-only
or otherwise incomplete observation may settle into that exact candidate only
after the complete Ally X + GPD G1 profile becomes verified. The attach-readiness
watch binds that candidate to the private exact eGPU identity and waits for a
newer sample before reporting a categorical status. When automatic docking is
enabled, an exact G1 already present when the plugin starts may be armed by the
same later-sample rule; USB4 presence alone cannot arm it.

It may report:

- `settling` when no newer sample exists yet;
- `waiting_for_external_display` when the same exact G1 is present but a
  verified external EDID/display is not ready;
- `waiting_for_link_health` when the exact bridge link is absent, Down, or not
  currently observable;
- `ready_idle` when the exact G1, a verified Gamescope session, one verified
  external display, an observed Up exact bridge link, and an Idle game state
  are observed;
- `game_running` when the same readiness is observed but a game is running; or
- `action_required` for an identity/session/game-state ambiguity.

`ready_idle` by itself is a read-only observation, not an approval to dock. The
automatic-dock coordinator can consume it only after the player has explicitly
enabled the persistent opt-in. It issues at most one request for the attached
G1, and that request independently re-observes the same semantic generation,
exact profile capabilities, prepared integration, idle game state, and durable
journal before using the unified transition engine. `game_running` deliberately
does not request a restart or infer GPU migration.

An Up link only says the exact bridge currently reports nonzero link metrics. It
is not TV activity, render-GPU selection, bandwidth proof, controller/audio
usability, or Safe Undock authority.

The watch and opt-in automatic coordinator are implemented and simulated. A
single backend-owned bounded poll runs only while the opt-in is enabled and
keeps automatic behavior independent of whether Quick Access is open. The UI receives only categorical status and
cannot supply identities, paths, plans, or transition evidence. Hardware
validation still requires player-present before/live/after evidence under
[Deployment and validation strategy](DEPLOYMENT_VALIDATION.md).
