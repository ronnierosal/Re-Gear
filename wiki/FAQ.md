# Frequently asked questions

**Audience:** players, testers, and contributors<br>
**Reviewed:** 2026-09-06<br>
**Maturity:** answers reflect the current development baseline

## Can I install Re-Gear as an ordinary Decky plugin today?

Not as a supported public release. Current hardware builds use controlled,
provenance-verified deployment and supervised validation. See
[Getting Started](Getting-Started).

## Does Re-Gear only support the Ally X and GPD G1?

They are the first exact validated profile, not the intended architectural
limit. Other hardware is not yet certified. Several first-profile couplings
remain open and are being moved behind capability/profile seams incrementally.

## Does TV Docked work now?

Yes, bounded supervised Ally X/GPD G1 sessions have activated the TV and selected the external GPU. Automatic docking is experimental and off by default. Repeatable operation, recovery, and audio must still be verified for the exact build. See [Current State](Current-State).

## Can I unplug the GPD G1 while the handheld is running?

No. Physical live G1 removal is unsupported. Shut down before disconnecting it.
An accepted shutdown request is not proof of physical power-off. If the fan
remains on, keep the G1 connected and hold the Ally power button until the fan
stops; only then remove the cable.

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
