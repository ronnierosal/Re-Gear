# ADR: G1 sleep guard

## Decision

Re-Gear 0.2 owns a login1 `sleep` inhibitor in `block` mode whenever the supported
Ally X observes a G1 candidate. SteamOS's exact `systemd-inhibit` command owns
the returned descriptor. Re-Gear launches it only through an internal helper that
arms Linux parent-death signals before execution; the command's held no-op child
uses the same guard.

This follows login1's native lifetime rule: the inhibitor exists only while the
returned descriptor remains open. See the official
[login1 manager API](https://www.freedesktop.org/wiki/Software/systemd/logind/)
and [systemd-inhibit behavior](https://www.freedesktop.org/software/systemd/man/latest/systemd-inhibit.html).

## Lifecycle

| Observation | Action |
|---|---|
| G1 candidate present, including incomplete identity | Acquire or retain the lease. |
| G1 verified absent on the supported host | Release the lease. |
| Host, DRM, or identity evidence unknown | Hold the current lease state. |
| Plugin unload | Release the lease. |
| Backend crash | Parent-death signals terminate the holder chain; the kernel closes the descriptor. |
| Acquisition failure | Report `sleep_guard_inactive`, retry, and show a critical warning. |

Acquisition and release are idempotent. The controller polls the small
host/DRM/PCI/USB4 evidence set rather than the full process-client snapshot.
The process boundary removes Decky's transient dynamic-loader and Python path
overrides before starting SteamOS's `/usr/bin/python` and
`/usr/bin/systemd-inhibit`; all other environment entries are preserved.

## User experience

Quick Access always shows the current protection state while the G1 is attached.
It also emits a game-aware acknowledgement dialog and explanatory panel. **Never show this
explanation again** stores a frontend-only preference. It cannot release the
lease, hide inactive-protection failures, or alter blockers.

## Boundaries

- Public RPCs remain limited to `get_snapshot`, the separately documented
  preview/token-approved support-bundle flow, and supervised presentation
  preparation. Preparation cannot restart Gamescope or switch display/GPU
  placement.
- No sleep request is initiated by Re-Gear.
- No power-menu interception is treated as the safety boundary.
- No display/GPU transition, process signal, or physical removal is added.
- The original Steam active-session power-menu Sleep path failed acceptance on
  the certified Ally X/G1 profile: login1 refused full suspend, but Steam left
  the handheld backlight lit with a black screen. The Steam-native preflight now
  blocks before preparation and preserved presentation in supervised tests;
  delayed acknowledgement-dialog visibility remains pending.
- Do not repeat that path without the player present. The implemented lifecycle
  and remaining validation gates are defined in
  [ADR: Steam sleep preflight](ADR_STEAM_SLEEP_PREFLIGHT.md).
- Synthetic Steam input and a short physical power-button press did not recover
  presentation. A graceful Steam reboot restored the internal display.
- Physical power-button, idle-sleep, and authorized direct login1 paths still
  require separate supervised hardware validation.
