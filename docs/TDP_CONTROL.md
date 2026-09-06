# TDP control workstream

Status: **In development, not installed or hardware validated.**

The maintainer requested independent TDP/Auto TDP research, implementation,
testing and remote inspection on 2026-09-04. This workstream owns handheld APU
power management. The G1 connection/disconnection driver continues to own its
hardware journey. TDP work must not incidentally change display, render GPU,
fan curves, controller input, sleep or device lifecycle.

## Product contract

The intended player experience is a manual handheld power limit followed by
optional automatic adjustment toward a player-selected frame-rate target.
Requested limit, observed configured limit and measured package power are
different values. An accepted request is not verified application. No feature
may invent measurements or advertise runtime support from a fixture test.

Manual and automatic requests must share one application service, capability
resolver and power writer. Placement remains independent. A running game's
power policy is not permission to migrate that game to another GPU.

## Research findings and implementation decisions

References below were inspected on 2026-09-04. Upstream availability is not
evidence about the installed Ally kernel or services.

1. [Bazzite's current handheld guide](https://docs.bazzite.gg/Handheld_and_HTPC_edition/Handheld_Wiki/)
   describes SteamOS Manager and OpenGamepadUI/PowerStation TDP paths and calls
   for a single active control mechanism. Bazzite's current stack is not simply
   the historical HHD/Adjustor design.
2. SteamOS Manager source was retrieved from its
   [canonical repository](https://gitlab.steamos.cloud/holo/steamos-manager)
   at `61d9ae7b626b6be0847d5fe7a8716d35215b2db6`. Its
   `data/devices/rog-ally-series.toml` identifies the RC72LA Ally X and selects
   the `asus-armoury` firmware-attribute backend in the performance profile.
   This makes the platform service the first integration candidate, subject
   to actual installed API/driver discovery.
3. At that revision, `steamos-manager-proxy/src/tdp_limit1.rs` and
   `data/interfaces/com.steampowered.SteamOSManager1.xml` define
   `com.steampowered.SteamOSManager1.TdpLimit1`, with unsigned `TdpLimit`,
   `TdpLimitMin`, and `TdpLimitMax` properties. The service/path are
   `com.steampowered.SteamOSManager1` and `/com/steampowered/SteamOSManager1`.
   `steamos-manager/src/manager/user.rs` queues a write; successful property
   assignment does not prove hardware application. Read failures can return
   zero. Re-Gear must reject zero/invalid capability ranges and verify results.
4. `steamos-manager/src/power.rs` reads sustained power from
   `ppt_pl1_spl/current_value`, obtains min/max from that attribute and sets
   sustained, slow and fast values independently. Slow/fast minimums can differ
   from sustained minimums. A firmware property is a configured limit, not a
   wattmeter, and one sustained readback does not prove all three writes worked.
5. [SimpleDeckyTDP](https://github.com/aarron-lee/SimpleDeckyTDP/blob/7172b4990c406e26773a71c58cce3857f2a5393a/py_modules/devices/rog_ally.py)
   demonstrates legacy ASUS WMI and newer firmware-attribute paths, including
   both fast-limit attribute names. Re-Gear's first inventory reports all
   observations and ambiguity; it does not copy upstream hard-coded limits.
6. [PowerControl's backend dispatcher](https://github.com/mengmeet/PowerControl/blob/646e1724078c035ff2e07628d512425f60795c61/py_modules/tdp_backend.py)
   makes backend choice explicit. Its automatic GPU-frequency loop is a
   different feature from FPS-target APU TDP. Its cadence is not a measured
   overhead budget for Re-Gear.
7. [PowerStation](https://github.com/ShadowBlip/PowerStation/tree/8e47b5c2b574a149601e2d6a0e83aa86c94cd827/bindings/dbus-xml)
   supplies a D-Bus alternative, with ASUS support. It is a candidate only if
   discovered on the actual device. Example GPU object numbers must not become
   persistent hardware identity.
8. [HHD's conflict detection](https://github.com/hhd-dev/hhd/blob/a8bd8be17cb9025e4690bee423d90b206f696323/src/adjustor/hhd.py)
   checks for other Decky power plugins. Re-Gear should detect overlap and
   explain ownership, without copying its plugin-moving/service-stop behavior.
9. [The hhd-autotdp fork](https://github.com/luisho24/hhd-autotdp/blob/f15eff21d5594b83724ca2f8554d1d72854b26d2/src/adjustor/auto_tdp.py)
   illustrates FPS-error-based wattage steps, but its demonstrated controller
   lacks sufficient sample freshness, readback and restoration for adoption.
10. [HandheldCompanion](https://github.com/Valkirie/HandheldCompanion/blob/5c94abca83f8711ff5620906871b31a41c76bf05/HandheldCompanion/Managers/PerformanceManager.cs)
    illustrates feedback damping and small power-reduction probes near target.
    Its noncommercial license means it is behavioral study only here; no code
    is copied. Re-Gear's initial policy uses its own simple streak/settling rules.
11. [RyzenAdj](https://github.com/FlyGoat/RyzenAdj/blob/5775fc3e6dbb25c7030ee2d100a1bdd6e8bf2d0a/README.md)
    is lower-level fallback research. Firmware or other managers can overwrite
    its settings. An independent reassertion loop is not controller coordination.

The default direction is to cooperate with an already functioning platform
backend, not install a second system daemon. Direct ASUS writes remain a
fallback candidate requiring explicit backend selection and live evidence.
No automatic backend switching follows a partial write or failed readback.
The actual provider and controller ownership must be resolved before this
choice can become a runtime implementation.

## Auto TDP design requirements

- Use game-bound, fresh frame-time samples and a player target. A GPU utilization
  percentage alone is not an FPS objective; eGPU utilization must never be
  mistaken for the handheld APU's load.
- Keep the control algorithm pure and replayable; use bounded steps, a target
  deadband, settling time and hysteresis. Test saturation, CPU-bound workloads,
  frame caps, loading screens, stale samples and sudden workload changes.
- Thermal, AC/battery and controller-ownership observations constrain the
  decision independently. Do not adopt universal wattage or thermal thresholds
  from another handheld.
- The existing optional telemetry policy defers during gameplay. Auto TDP needs
  a specific measured gameplay contract rather than silently changing that
  shared policy or creating an unbounded background loop.
- Stop issuing adjustments when samples, identity, ownership or readback become
  uncertain. Capture the original setting and define restoration on disable,
  game exit, suspend, unload and failure. Restoration must not overwrite a newer
  external/user setting; use observed ownership/generation checks.
- A feedback algorithm may be implemented and simulated before a real collector
  is available, but remains disabled until its data and actuator are validated.

## Manual provider implementation

The local `SteamOsManagerTdpProvider` now reads the exact Ally X host profile,
boot identity, resolved session user, service owner, TdpLimit1 properties and
all three canonical ASUS firmware registers. It checks D-Bus/sysfs sustained
limit agreement and each register's own range. A simultaneous alternate fast
attribute remains ambiguous; the explicitly selected firmware backend does not
mistake a parallel legacy sysfs view for a separate controller.

`SteamOsTdpCommandRunner` performs only fixed read, service-owner lookup and
unsigned TDP assignment commands. The setter targets the observed unique
D-Bus owner so a restarted daemon is not silently substituted. Calls disable
service auto-start and interactive authorization. Commands are shell-free,
time-bounded and return categorical failures. The accepted-output size check
occurs after subprocess completion; it is not a streaming memory bound.
The command syntax follows [systemd's busctl documentation](https://github.com/systemd/systemd/blob/main/man/busctl.xml).

`TdpControlService` serializes manual or future automatic requests, validates
the target against sustained and boost ranges, persists a pending record before
dispatch, and verifies all three registers. Repeated adjustments preserve the
original baseline. Restore requires the observed setting and context to still
match the last verified application, and will not overwrite an external change.
An accepted command alone never becomes an applied result. Partial readback,
timeout or interrupted verification leaves recovery-required evidence and does
not trigger speculative retries or reverse writes.

SteamOS Manager's scalar setter cannot restore arbitrary independent boost
settings. The first backend therefore requires a baseline representable by its
actual scalar-to-register mapping before changing it; nonrepresentable baselines
report `tdp.baseline_not_restorable`. This is an explicit current limitation,
not a reason to silently flatten the user's original boost settings.

`FileTdpJournal` validates its versioned schema, opaque bindings and baseline/
applied context; writes a private temporary file; flushes it; replaces the fixed
target; and fsyncs the directory on Linux. Corrupt or pending records remain
blocking evidence. The runtime must provide one service owner and a private
state directory; this store is not an interprocess lock. Current filesystem
tests ran on Windows, so Linux directory-fsync and permissions still need
Linux execution evidence.

These components are implemented and simulated, not wired into Decky or
installed. Provider ownership defaults to unverified. An active native manager
is not by itself proof that Steam, a Decky plugin or another daemon will not
change its state. A real ownership resolver, lifecycle integration and user
controls remain necessary before runtime activation.

`GameFrameCollector` and `FrameTimeWindow` add a pure context binding and bounded
aggregation layer. They reject changed, repeated, out-of-order, or stale samples;
they do not discover a game, open a socket, schedule collection, or change TDP.

## Ordered implementation

1. Fix non-finite thermal readings being classified Normal; add regression
   coverage. This does not make the existing assessment a TDP thermal controller.
2. Add bounded one-shot read-only inventory of configured ASUS power limits.
   Preserve absent, invalid, incomplete and ambiguous evidence. No runtime
   polling or writable capability claim from this inventory.
3. Inspect the online Ally: OS/kernel, exact host profile, installed TDP APIs,
   current platform profile, active owners/plugins, configured limits and usable
   measurement sources. Use SSH with the existing key and maintainer-provided
   address. Do not scan the network. The address is currently awaited.
4. Resolve the device-backed provider and write a shared manual apply/verify/
   restore service, with tests for timeout, partial failure and external changes.
   **Implemented/simulated:** command runner, ASUS provider, application service
   and file journal. **Pending:** live provider validation, ownership resolver,
   lifecycle wiring and honest capability/requested/observed panel status.
5. Add the pure Auto TDP policy, replay scenarios and a measured collector;
   integrate only after manual behavior and provider ownership are understood.
6. Run the integration matrix and independent review. Record remote evidence
   separately from visual/gameplay validation and installation provenance.

## Licensing and reuse

This repository is GPL-3.0-or-later. SteamOS Manager is MIT-licensed;
SimpleDeckyTDP and PowerControl use BSD-3-Clause. Inspect the exact file and
dependency license before copying any implementation and preserve required
notices. Current work uses interface/behavioral research and original code; no
upstream code has been incorporated. Further comparative findings will be
recorded here before choosing additional integrations. PowerStation is GPLv3+;
HHD and the examined Auto TDP fork are LGPL-2.1-or-later; RyzenAdj is LGPL-3.0.
HandheldCompanion's inspected LICENSE.md is CC BY-NC-SA 4.0 and its code is
excluded from reuse in this workstream.

## Continuity

- Branch: `codex/tdp-control`, isolated from `main` at `75f441f`.
- Thermal non-finite fix implemented; two thermal tests and architecture check
  pass. No installed behavior changes.
- Read-only inventory implemented; 13 fixture-based tests pass.
- Original pure Auto TDP proposal policy implemented; 11 replay tests pass.
  It has no live scheduler, actuator or runtime integration. Initial defaults
  are development parameters, not hardware-tuned values. Policy supports only
  verified internal rendering; eGPU-backed Auto TDP needs separate design.
- Comparative research and the first backend are recorded above; the current
  Ally address is still required for remote checks.
- No device setting changes, deployment, push or publication performed.
- Independent review found stale decision streaks after observation gaps and
  oversized-integer FPS validation failure. Both corrected with regressions.
- Manual-provider checkpoint: 65 TDP-specific tests passed. Independent review
  led to unique-owner dispatch, journal context validation and categorical
  verification-failure handling, all covered by regressions.
- Integration verification: 882 backend tests passed (5 expected skips);
  architecture, Python compilation and `git diff --check` passed. No frontend
  files or generated package artifacts changed, and no deployment gate is claimed.
