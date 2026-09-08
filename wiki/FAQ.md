# Frequently asked questions

**Audience:** players, testers, and contributors<br>
**Reviewed:** 2026-09-08<br>
**Maturity:** answers reflect the current development baseline

## Can I install Re-Gear as an ordinary Decky plugin today?

Not as a supported public release. Current hardware builds use controlled,
provenance-verified deployment and supervised validation. See
[Getting Started](Getting-Started).

## Is Re-Gear limited to one handheld or eGPU brand?

No. Re-Gear is designed as a SteamOS handheld companion across hardware vendors.
General features and hardware-dependent actions have separate requirements.
Broader product scope does not mean every device is tested: see [Supported Hardware](Supported-Hardware)
for exact combinations and [Confirmed Hardware Testing](Confirmed-Hardware-Testing)
for recorded results. Additional devices need their own profile and capability evidence.

## Is the new Command Center available?

The complete rebuild is in development. Existing Quick Access navigation is
implemented; the approved layout and new module foundation have separate
delivery gates. See [Command Center](Command-Center) for status and future
screenshots of the actual interface.

## Are power and controller settings supported on every handheld?

No. [Performance and Power](Performance-and-Power) depends on verified provider
limits and ownership. [Controller capabilities](Controllers) vary by device,
transport and input stack; research and a visible design control do not establish
working support.

## Does TV Docked work now?

Yes, bounded supervised sessions on the documented test profile have activated the TV and selected the external GPU. Automatic docking is experimental and off by default. Repeatable operation, recovery, and audio must still be verified for the exact build. See [Current State](Current-State).

## Can I unplug an eGPU while the handheld is running?

Current Re-Gear validation does not establish safe live removal. Follow the
verified policy for your exact hardware; unknown profiles cannot authorize removal.
Under shutdown-before-disconnect, an accepted shutdown request is not proof of
physical power-off. Keep the eGPU connected if shutdown is incomplete and follow
the device-specific recovery instructions.

## Can Re-Gear move a running game between GPUs?

No. A running workload stays on its current GPU. Transitions requiring a
Gamescope restart are blocked while a game is running or game state is unknown.

## Why can a connected monitor still be unusable?

DRM connection state means a connector detected a sink. It does not prove that
Gamescope selected that output, the expected GPU is rendering, or the display is
showing a usable image. Re-Gear verifies those facts separately.

## What diagnostic data is safe to share?

Use the bounded support preview/export. Do not share raw logs, home paths,
network coordinates, account IDs, or raw device identities. See
[Diagnostics and Privacy](Diagnostics-and-Privacy).

## How can I add another handheld or eGPU?

Begin with a synthetic profile boundary test and exact capability/quirk model,
then gather separately reviewed hardware evidence. Do not add fuzzy product-name
matching or device-order assumptions. See [Supported Hardware](Supported-Hardware).
