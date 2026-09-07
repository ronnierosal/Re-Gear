# Power and link health

## Current implemented slice

Re-Gear currently observes the exact eGPU bridge's **current PCIe link state** and,
when the kernel exposes them, current GT/s and lane width. The Quick Access
Troubleshooting view shows those values as diagnostics only; it does not call
them throughput, cable quality, charging headroom, performance, removal safety,
or certification.

The player-facing policy is deliberately small:

- the first eGPU-relevant link observation is silent;
- a changed Down or Unknown observation opens one non-blocking instability
  episode;
- all subsequent Down/Unknown samples in that episode, including a materially
  changed reason, are suppressed until recovery;
- a later observed Up state produces one compact recovery notice; and
- eGPU absence resets the episode without a notice.

Notices say Re-Gear is preserving the current setup and advise against disconnecting.
They never diagnose a cable fault, claim recovery, or execute an action. They
remain non-blocking during a game. A player-requested unsafe action retains its
own explicit confirmation and fail-closed checks.

The compact Quick Access Connection row also fails closed: a current applicable
Down or Unknown link sample cannot be presented as `TV Docked` or `Ready to
dock`. `Ready to dock` additionally requires one currently exact G1 profile,
one verified present external GPU, and one current observed-Up link; a stale
display row or required sleep guard cannot substitute for that evidence.
Verified absence says `eGPU not detected`; unknown profile or link evidence says
`eGPU evidence unavailable` or `eGPU link needs verification`. It adds no
collector or transition authority.

## Status vocabulary

The intended Power and Link Health vocabulary is **Healthy**, **Degraded**,
**Action needed**, and **Unknown**. In the current slice, only the link portion
has a live read-only source:

- **Healthy** can mean only that one exact bridge link was observed Up; it is
  not a whole-system or performance conclusion.
- **Degraded** is a known Down link observation.
- **Action needed** belongs to a separate player-requested action when its
  existing transition/readiness checks are blocked; notification alone never
  elevates an observation into an action.
- **Unknown** covers unreadable/ambiguous link evidence and all currently
  unimplemented power evidence.

Automation is unchanged and disabled: attach observation remains monitor-only,
and no transition, Safe Undock, physical removal, or power adjustment is
enabled by this health display. The current G1 profile still requires shutdown
before physical disconnection.

## Not implemented

Re-Gear has no collector for AC/charging state, battery direction, requested or
available power budget, thermals, throttling, fan behavior, or sustained link
churn. The telemetry contract is only an admission policy; it is not a
collector. A future power-health implementation needs a profile-specific
read-only source, bounded units/privacy schema, cost benchmark, event-driven or
measured cadence, and a game-impact gate before it may affect a player status.
It must defer nonessential collection while a game is running and can never
perform power chasing, TDP tuning, or a transition.
