# Ally X and GPD G1: 0.3.82 automatic recovery checkpoint

Recorded September 11, 2026. This is a preserved, installed and hardware-tested candidate, not a general release. Runtime PR [301](https://github.com/ronnierosal/Re-Gear/pull/301) remains open. The checkpoint does not imply that its runtime code is merged into main.

## Exact code and artifact

- Source revision: `09ff57128ca6e0526f4b5376af825d87557c0f2e`.
- Annotated source tag: `checkpoint/0.3.82-auto-tv`. Preserve this tag; future changes require a new commit and version.
- Archive: `Re-Gear-0.3.82.zip`.
- SHA256: `c27e48366daa4374d49d02128e40c27e038cafa87488dcf449b3863b1841b06f`.
- [Checkpoint download, checksums and sanitized validation record](https://github.com/ronnierosal/Re-Gear/releases/tag/checkpoint/0.3.82-auto-tv).
- Installed build metadata and five changed runtime/frontend files matched the packaged candidate before testing.

## Problem and implemented behavior

The dock transport could appear immediately while the GPU remained absent from PCI enumeration. A manually requested Gaming Mode restart had previously recovered GPU detection, followed by automatic TV switching. This candidate starts that same guarded recovery automatically after an observed supported attachment and about ten seconds of idle settling.

Topology events wake the observation loop, with polling fallback. Recovery requires separate persisted consent, verified transport identity and prior absence, a supported host, only the verified internal GPU, idle game state, a unique Gaming session and an available transition journal. Fresh checks run before the command. At most two automatic attempts are allowed per attachment; a second waits at least ten seconds after the first finishes. GPU arrival stops recovery. Unknown observations do not replenish the attempt budget. A plugin reload with a dock already attached does not replay recovery.

The ordinary automatic TV transition still checks display, audio and session readiness. Recovery and TV handoff can each restart the session: two observed session cycles do not mean two recovery attempts.

## Supervised hardware evidence

Profile: ASUS ROG Ally X with GPD G1, SteamOS. All three trials used the same 0.3.82 candidate, with automatic docking and the separately authorized automatic-recovery preference enabled. The user did not press Retry. Each trial ended with user confirmation of Gaming Mode picture, audio and controls on the TV.

| Trial | Scenario | Recovery started | GPU trained | TV transition started | Recovery attempts |
|---|---|---:|---:|---:|---:|
| 1 | Detached Gaming Mode, attach with TV on | 10.771 s | 18.500 s | 21.373 s | 1 |
| 2 | Complete shutdown, detach, clean boot, attach with TV on | 10.427 s | 17.648 s | 20.502 s | 1 |
| 3 | Complete shutdown, detach, boot, attach with TV off, then turn TV on | 10.693 s | 17.945 s | 20.844 s | 1 |

Times are native journey elapsed times relative to observed attachment, not stopwatch measurements of visible picture. Bounded capture showed GPU arrival and Gaming Mode restart; native event outcomes recorded recovery and the subsequent TV transition. Full captures are retained privately; the downloadable validation JSON contains sanitized state changes and outcome summaries.

In trial 3, Linux still reported the TV connector connected/enabled while the TV was off. This proves this TV's standby case, not recovery from genuinely missing HDMI detection or EDID. Desktop mirroring does not remove that distinction.

## Reproduce without changing the checkpoint

1. Shut down completely before physically disconnecting the G1.
2. Boot the Ally detached into idle Gaming Mode.
3. Confirm the exact version and both automatic preferences; start the bounded capture.
4. Connect the G1. Do not press Retry or issue a manual recovery command.
5. For the standby case, keep the TV off until GPU recovery is observed, then turn it on.
6. Confirm picture, audio and controls, and correlate the automatic attempt count with the capture.

## Preservation and rollback

Keep the original archive; do not rebuild or overwrite version 0.3.82. Check the published SHA256 before reinstalling it through the normal Decky ZIP installer. Source restoration uses the checkpoint tag in a separate branch/worktree. Preserve future changes separately and compare against these same connection cases before replacing the working install.

Package installation and settings restoration are separate. Automatic recovery defaults off and has separate persisted consent. For these supervised trials it was enabled through the existing authorized settings interface; the dedicated player-facing preference control is unfinished. Reinstalling the archive alone does not guarantee those settings are enabled. This record intentionally includes no raw privileged recovery commands, credentials or device identifiers.

## Validation and remaining limits

The candidate passed 2,983 backend tests with 101 skips, 636 frontend tests with one skip, architecture, compile, type, bundle, package and integration checks; final-head CI passed. These checks are distinct from the three physical trials.

Remaining: dedicated recovery preference UI, native manual confirmation interaction verification, genuinely missing HDMI/EDID, second-attempt behavior on hardware, and broader repeatability. No running-game recovery, live physical unplug clearance or general hardware certification is established. Retain normal shutdown before physical disconnect.

## Related records

[Engineering checkpoint](https://github.com/ronnierosal/Re-Gear/blob/main/docs/EGPU_0382_CHECKPOINT.md) · [Device troubleshooting](Ally-X-and-GPD-G1-Troubleshooting) · [eGPU and Docking](eGPU-and-Docking)
