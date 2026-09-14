# 0.3.98 eGPU cycle checkpoint

Ronnie designated this exact installed version as the golden baseline on
2026-09-13 UTC after the supervised cycle below. This supplements the older
0.3.82 automatic-TV checkpoint; it does not erase the earlier evidence.

- Source: `f6059fad8c213a059aa77cbba15524ef2d9149ae`.
- Published Git tag: `checkpoint/0.3.98-egpu-cycle`.
- Installable archive: `Re-Gear-0.3.98.zip`, 976983 bytes.
- SHA256: `aa14dcab885492368ee86e26523a8da7cd156d7483d097ba86f6814ebbf413da`.
- Installed version and full revision were read back over SSH before the trial.
- Hardware: Ally and G1; kernel
  `6.16.12-valve24.5-1-neptune-616-gb2f7cfe85e45`.
- Automatic docking and recovery enabled; existing session restart strategy,
  10-second initial delay, two-attempt maximum. No preferences changed in the trial.
- Local rollback copies, source bundle and evidence:
  `egpu-connection-admission-fix/out/golden-0.3.98/` in the shared workspace.
  The original archive and the staged `/home/deck/Re-Gear-0.3.98.zip` remain intact.

## Verified journey

1. User pressed the expanded Command Center Safely disconnect action once.
2. At 03:29:13.090 UTC: `dock_teardown.software_down`, release stage `removed`,
   `live_disconnect.removed`, `display_release.released`, filter disarmed;
   external GPU absent. User confirmed handheld picture, audio and controls.
3. User physically unplugged. At 03:32:34.702: transport absent, claim `none`;
   completed history cleared automatically. Handheld continued normally.
4. User physically reconnected. First sampled settling at 03:33:49.436;
   GPU and HDMI were initially absent.
5. At 03:34:20.994: one automatic recovery, TV active, all readiness checks true,
   claim `none`. User confirmed TV picture, audio and controls worked.

Captures: `0398-disconnect-1789270101399.jsonl` and
`0398-disconnect-1789270372901.jsonl`; installable candidate manifest contains
readback and confirmations. CI34735201550 and privileged delivery34735201545
passed on the exact source; independent diagnostic review and golden tests passed.

## Scope and preservation

This is one successful supervised cycle, not universal hardware qualification,
proof of repeated reliability, sleep/shutdown qualification, or a software
reconnect endorsement. The previous 0.3.97 GPU-release refusal remains documented;
0.3.98 added diagnostics and did not establish its cause. Preserve both outcomes.

Future power actions must call the same disconnect sequence, then continue the
original power intent once. They must not introduce new prerequisites, retries,
or teardown state into ordinary auto-TV attachment. New work uses a descendant
branch; the tag, ZIP and source bundle are immutable. Preserve the previous ZIP
and settings before a trial install; rollback uses this exact ZIP and an installed
revision readback, with automatic docking/recovery settings checked separately.

Software USB4 reconnect, reauthorization on wake and PCI rescan recovery are
explicitly excluded by Ronnie after the earlier heating incident. First-time
permission for a genuinely new device is a separate feature and must not turn an
intentionally disconnected still-cabled dock back on.
