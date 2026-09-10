# Interrupted sleep relaunch eligibility

Status: **Implemented (pure policy); Hardware Validation Required**

`regear.domain.sleep_relaunch_eligibility` classifies explicit, fresh,
opaque-bound post-sleep evidence for a possible future relaunch flow. It does
not save or close a game, launch anything, persist a preference, or control
sleep, wake, displays, GPUs, or devices.

The policy can return only:

- `explain_recovery` when recovery, game, risk, binding, or observation
  evidence is incomplete, stale, unknown, inconsistent, or unsafe.
- `no_relaunch` when the current explicit preference is opted out.
- `prompt_preference` after verified handheld recovery, an observed stopped
  game session, and all observed risks clear, when preference is unknown.
- `eligible_for_future_relaunch` with the same evidence only when preference is
  explicitly opted in. This is not launch authority.

Verified handheld display, built-in input, and handheld audio are required.
Update, cloud-sync, launch, and repeat-failure risks must each be verified
clear. A running or unknown game session blocks the future-flow eligibility.
The policy observes only stopped/running/unknown state; it makes no claim about
crash certainty, game survival, saved data, or a successful relaunch.

Any real relaunch requires separately reviewed collection, preference storage,
loop prevention, an action adapter, recovery fallback, and supervised hardware
validation.
