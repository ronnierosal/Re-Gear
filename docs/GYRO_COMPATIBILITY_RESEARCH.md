# Handheld gyro research and engineering handoff

Date: 2026-09-08. Task: `controller-gyro-compatibility`.
Status: source research and proposed implementation sequence; no runtime changes,
installation, sensor capture, or hardware validation.

Scope: any gyro-equipped handheld on SteamOS, including ROG Ally X and GPD Win
Mini. Compatibility must be established per model and installed software stack.
Ronnie's Win Mini model is not yet confirmed; its SteamOS installation and testing
are future work. This document does not certify any device.

## Recommended first contribution

Build bounded, read-only gyro diagnostics before adding configuration controls.
Reuse the active input provider where its verified interface permits observation.
Keep sensor presence, provider routing, target motion capability, and successful
Steam/game delivery separate. A controller appearing in Steam proves none of the
last three by itself. This is an engineering recommendation, not an accepted new
runtime authority or a promise that Re-Gear can fix every input stack.

Re-Gear base inspected: `ed47965e818977fedaaf8cf2fa020208f5df1ff6`.
`backend/regear/adapters/steamos/peripherals.py` currently inventories gamepad key
capabilities and returns opaque bindings. It does not inspect motion delivery.
Do not reinterpret its `complete` flag as gyro readiness or widen its existing
controller/audio mutation contract. Follow `docs/DIAGNOSTICS.md` for bounded,
redacted snapshot delivery and `docs/ARCHITECTURE.md` for pure domain boundaries.

## Source evidence and compatibility candidates

Upstream snapshots inspected directly through GitHub source APIs:

- InputPlumber: `0ca9869cfb886fe724801b8694153374cdc08352`.
- Handheld Daemon (HHD): `adbd50ff30614df886a6c76bd8855a64fde5d0b8`.

These are upstream snapshots, not the versions installed in SteamOS or on Ronnie's
devices. Distribution patches and runtime profiles can differ.

| Candidate | Evidence in inspected source | Next verification |
| --- | --- | --- |
| ROG Ally X | InputPlumber profile matches ASUS board RC72LA, includes `bmi323-imu`, and specifies a model-specific mount matrix. Its default targets include `xbox-elite`. [Profile](https://github.com/ShadowBlip/InputPlumber/blob/0ca9869cfb886fe724801b8694153374cdc08352/rootfs/usr/share/inputplumber/devices/50-rog_ally_x.yaml) | Check installed provider/version, effective source and target capabilities, and Steam motion test. Never change target type automatically based on the upstream default. |
| Win Mini G1617-01 | InputPlumber profile matches this DMI product only, accepts `i2c-BMI0160:00` or `bmi260`, and uses a different mount matrix from Ally X. [Profile](https://github.com/ShadowBlip/InputPlumber/blob/0ca9869cfb886fe724801b8694153374cdc08352/rootfs/usr/share/inputplumber/devices/50-gpd_winmini.yaml) | Establish exact model, driver, and effective distro profile. Do not extend a DMI match without verifying the rest of the profile, including input identities. |
| Win Mini 2025 G1617-02 | HHD has a separate model entry. The inspected InputPlumber WinMini profile above does not match this product. This is a profile coverage question, not proof that every installed stack lacks support. | Inspect installed profile set and real sensor identity; distinguish this model from G1617-01. |
| Other gyro handhelds | InputPlumber has IIO driver selection for Bosch/InvenSense-style names and separate HID Sensor Hub `gyro_3d`/`accel_3d` sources. [Driver selection](https://github.com/ShadowBlip/InputPlumber/blob/0ca9869cfb886fe724801b8694153374cdc08352/src/input/source/iio.rs) | Enumerate capabilities first. A sensor family match does not establish device orientation, routing, or successful game input. HID motion paths may not appear as an IIO sensor. |

### Specific Win Mini lead

[HHD issue 314](https://github.com/hhd-dev/hhd/issues/314) reports missing motion
on a 2025 AI 370/G1617-02 running CachyOS Deckify with HHD 4.1.8-1. The reporter
attributes it to lowercase `bmi260` discovery and a missing software trigger,
and reports success after two edits. This is a reporter's hardware result on a
different distribution, not a confirmed SteamOS fix.

Current-source cross-check: the inspected HHD [sensor matcher](https://github.com/hhd-dev/hhd/blob/adbd50ff30614df886a6c76bd8855a64fde5d0b8/src/hhd/controller/physical/imu.py)
still lacks literal lowercase `bmi260` in `IMU_NAMES`; the
[G1617-02 entry](https://github.com/hhd-dev/hhd/blob/adbd50ff30614df886a6c76bd8855a64fde5d0b8/src/hhd/device/gpd/win/__init__.py)
does not set `hrtimer`. However, it now says `wincontrols: v2`, unlike the issue's
older excerpt. Also the [controller loop](https://github.com/hhd-dev/hhd/blob/adbd50ff30614df886a6c76bd8855a64fde5d0b8/src/hhd/device/gpd/win/base.py)
initializes `start_imu = True`: absent `hrtimer` does not itself skip preparation;
it skips creating that software trigger. Whether a trigger is needed depends on
the actual driver and existing configuration. Do not blindly apply the issue's
patch or transplant it into InputPlumber.

The [user-supplied Reddit report](https://www.reddit.com/r/gpdwin/comments/1uio4i8/ive_been_trying_last_steam_os_38_build_on_the_gpd/)
separately reports gyro and L4/R4 failures on Win Mini 2025 HX with SteamOS 3.8.
It establishes a community complaint, not its cause. Gyro and extra-button
investigations remain separate even if they share an input provider.

## Observable boundaries for a first implementation

InputPlumber's pinned [CompositeDevice interface](https://github.com/ShadowBlip/InputPlumber/blob/0ca9869cfb886fe724801b8694153374cdc08352/bindings/dbus-xml/org.shadowblip.Input.CompositeDevice.xml)
provides read properties `Capabilities`, `TargetCapabilities`, `SourceDevicePaths`
and profile metadata. Its [Manager interface](https://github.com/ShadowBlip/InputPlumber/blob/0ca9869cfb886fe724801b8694153374cdc08352/bindings/dbus-xml/org.shadowblip.Input.Manager.xml)
includes `Version`. The [IIO interface](https://github.com/ShadowBlip/InputPlumber/blob/0ca9869cfb886fe724801b8694153374cdc08352/bindings/dbus-xml/org.shadowblip.Input.Source.IIOIMUDevice.xml)
exposes angular velocity/acceleration rates and scales, including writable
properties. Read capability presence is not evidence that fresh samples arrive.

Proposed adapter contract (names are a proposal, not existing RPC/schema fields):

- Provider/version and observation epoch; exact, incomplete, unavailable and
  permission-denied outcomes. Missing permission must not mean no gyro exists.
- Independent sensor discovery, source motion capability, target motion
  capability, and Steam delivery evidence; each may remain unknown.
- Opaque source/composite association, freshness, and stable categorical reason.
  Never infer association merely because two devices are present or named alike.
- Reject stale results after provider restart, topology change or unload; cap
  time, object count and response sizes. Do not export raw D-Bus/sysfs paths,
  persistent identifiers, arbitrary profile YAML or raw logs.

Limit collection to reviewed property reads and bounded local metadata. Do not
call setters, load profiles, inject events, change interception or gamepad order,
restart services, enable IIO buffers, or install another provider. Runtime API
introspection/version checks are required before relying on this upstream schema.
If HHD or another provider is active, initially report unsupported observation
rather than launching InputPlumber alongside it. A provider-specific adapter can
follow after its read interface is independently researched.

The [kernel IIO buffer documentation](https://docs.kernel.org/iio/iio_devbuf.html)
distinguishes discovery from continuous capture. Buffer setup involves channel
layout, enablement, triggers and alignment. A future measurement tool must respect
the existing owner; sampling setup is not automatically a read-only operation.

## Bounded coding sequence for Claude

1. Claim a separate pure evidence-model task. Add typed observations and a pure
   presenter that cannot derive working Steam gyro from source presence alone.
   Fixtures: missing sensor, incomplete enumeration, source-only, source plus
   target capability, unknown Steam delivery, stale epoch and ambiguous sources.
2. Claim an InputPlumber read-adapter task after the contract is agreed. Use fake
   D-Bus transport tests for missing interfaces, malformed types, timeouts,
   oversized results, provider replacement and multiple composites. Verify zero
   writes and no raw identity in serialized diagnostics. No new global poller.
3. Coordinate a presentation task with `qa-controller-page`. Put a concise gyro
   status in the controller module, detailed evidence in Troubleshoot. Keep
   calibration/rate controls absent until backed by a separately validated path.
   Reuse the normal snapshot lifecycle and preserve native focus behavior.
4. Diagnose exact-device gaps from a supervised observation session. Prefer
   focused upstream profile/driver fixes where the defect belongs. Any later
   Re-Gear configuration writer needs explicit scope, rollback and separate tests.

These steps are recommendations for follow-up ownership, not work already
implemented or a transfer of the existing controller-page task.

## Hardware validation and acceptance

Record exact model/firmware, OS/kernel, input-provider and Steam versions, and
effective profile/target identity in a reviewed local record. Begin with normal
controller input and Steam's visible motion behavior; do not install or switch
providers as an implicit diagnostic step.

For each supported configuration, exercise pitch/yaw/roll and sign, stationary
drift before/after warm-up, normal aim, activation/release, controller buttons,
Steam menus, plugin unload/reload and later supervised suspend/resume. Verify
the intended physical sensor controls the intended controller, including with
an external pad present. Record misses and duplicates rather than declaring a
pass from sensor activity alone. Agree numerical drift/latency targets before
certification; this research has not established defensible universal limits.

Test Steam motion visibility and actual game behavior separately. Valve's
[gamepad emulation guidance](https://partner.steamgames.com/doc/features/steam_controller/steam_input_gamepad_emulation_bestpractices)
explains that gyro-to-mouse depends on game support for simultaneous mouse and
gamepad input, with a single-mouse/local-player limitation. A game-specific
mapping problem must not automatically trigger a driver repair.

## Completion evidence

Reviewed pinned upstream profiles, interfaces, matcher and loop excerpts; checked
the current repository inventory and diagnostics contract. Documentation-only
change: no runtime tests or device tests establish new support. Follow-up coding
must run focused model/adapter tests and the normal integration gates. Hardware
acceptance remains pending for every candidate in this report.

Documentation impact: multiple
