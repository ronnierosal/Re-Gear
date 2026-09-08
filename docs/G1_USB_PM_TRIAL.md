# G1 USB runtime-PM comparison (developer draft)

This is an unvalidated hardware experiment, not live-unplug support or a Re-Gear
release. The G1 must remain physically connected until full power-off. No device
remove, rescan, driver unbind, USB4 reset, global power setting, or display
transition is performed by this helper.

## Evidence and hypothesis

On September 5, the G1 USB bridge reported four nonfatal ACS violations after
TV switching and four after Portable return. The recorder observed active and
suspended USB states around those bursts. That correlation does not establish
the cause. A later attached shutdown hung even though the patched Decky loader
recorded complete Re-Gear cleanup and Gamescope stopped. The final kernel stall
was not captured; USB errors are not a proven shutdown diagnosis.

The comparison temporarily sets only the exact G1 xHCI controller's
`power/control` to `on`, then restores `auto`. Kernel documentation describes
this as disallowing runtime power management:
https://www.kernel.org/doc/html/v6.16/power/runtime_pm.html
It is not equivalent to safely ejecting or powering down the GPU.

## Review and execution gates

1. Review this focused PR before any mutation. Keep it separate from popup fixes,
   release integration, and production ZIPs. Local fixture results are not
   hardware validation.
2. Confirm a detached, normally functioning Ally and no game. Verify the exact
   tested Decky loader and installed Re-Gear identity. Use a local Konsole session
   for privileged execution; do not widen sudoers or use a Decky RPC workaround.
3. Stage both scripts (`g1_usb_pm_trial.py` and `capture_g1_pcie_health.py`) in a
   unique directory, verify SHA-256, and first run without `--apply`. Default
   mode is read-only. No hardware run has occurred yet.
4. For a supervised trial, start the helper with `--apply` while detached. It
   refuses already attached/partial transport and overlapping helper runs. Its
   `armed_detached` event precedes the single user cable connection.
5. Detection defaults to 600 seconds (ten minutes), independently of Re-Gear's 120-second
   first-attempt timeout. It requires an exact GPU, transport ancestry, and xHCI
   driver, clean readable fatal/nonfatal counters, no USB block devices, and the
   original automatic power setting. It does not alter readiness gates.
   The timeout runs from arming, including time before the user connects. The
   explicit 600-second bound accounts for a recorded 363-second GPU arrival;
   expiry still ends without a write. This is a developer-test window, not a
   change to the player's popup or backend transition policy.
6. The 180-second hold begins only after writing and reading back `on` and
   verifying the controller is active. Re-Gear remains responsible for display
   switching. AER failures, identity changes or unexpected setting changes abort
   observation. Normal expiry and catchable cancellation attempt restoration.
7. Check `restored`, the setting, kernel logs, and user-observed display/audio/
   input. A negative result is not authorization to try resets or removal.

## Deadlines and rollback limits

The original setting is logged to a private per-run directory under `/run`
before mutation. Both serialized writes use one original open sysfs handle.
The boot and device identities are rechecked before restoration. Device change
causes a visible unverified restoration result, not a write to a replacement.

A kernel sysfs write can block. The watchdog reports unknown state after the
hold deadline plus ten seconds; it does not terminate the kernel operation or
issue a competing reset/write. If the original call returns, normal cleanup
continues. Uninterruptible hangs, SIGKILL, power loss, or device disappearance
cannot promise restoration. Keep connected and use the supervised recovery
procedure. `/run` records are volatile and must be copied before reboot.

## Verification

Twenty fixture tests exercise target selection, unrelated/ambiguous USB
devices, wrong drivers, counter/storage rejection, restored state, mutation
failure, cancellation, replacement identity, active-state verification, and the
non-mutating deadline alarm. Architecture and Python compilation checks pass.
Fan/thermal control is outside this helper. The original revision has now been
used in supervised trials; the longer-wait revision was subsequently exercised
with Re-Gear fixed at 0.3.50, as recorded below.

## Supervised results and next comparison

The original 180-second hold kept the exact xHCI controller active with zero
observed nonfatal/fatal errors. It restored `auto`, and a subsequent Portable
return produced four USB-bridge ACS/recovery failures. Re-Gear was updated from
0.3.46 to 0.3.47 during that trial, so it is not a clean causal comparison.

With Re-Gear fixed at 0.3.48, the old helper's 300-second armed wait ended
without a write. GPU detection arrived 363 seconds after physical connection;
TV switching succeeded around 371 seconds. Four USB-bridge failures followed
TV transition and four followed Portable return. The subsequent shutdown hung,
despite complete Re-Gear cleanup; a hard-off and detached restart restored the
Ally controller. The final kernel stall is still unproven.

## Fixed 0.3.50 trial and failed shutdown — 2026-09-05

Re-Gear 0.3.50 revision `e07bfb6e657ff3c30fc2f0fa3d84a94e87f869e9`
remained unchanged during this trial. The patched Decky Loader remained installed.
Helper revision `bd790a7` used a 600-second armed wait and 300-second hold.
GPU enumeration took approximately 230 seconds after transport detection;
TV switching succeeded at approximately 237 seconds. These are journal-derived
intervals, not precisely measured cable-insertion timestamps.

Both TV and Portable transitions completed while the controller was held awake.
The player confirmed picture, audio and controls on both displays. The helper
reported restoration to `auto`; subsequent reads showed the USB controller and
bridge suspended. Monitored fatal/nonfatal counters stayed zero, including a
check almost three minutes after restoration. This does NOT mean zero PCIe
errors: retained kernel logs include correctable BadDLLP and BadTLP events.

The subsequent ordinary attached shutdown FAILED and required forced power-off.
Re-Gear logged `unload_complete elapsed_ms=2`, and Decky reported its plugin
stopped in 0.1 seconds. The system manager (PID 1) progressed to filesystem
unmounting and stopping persistent journal flushing. The user-manager shutdown
target is not proof of system power-off. No final blocked-task stack or kernel
power-off completion was captured. Absence of the earlier monitored recovery
failures therefore does not establish a shutdown fix or a causal explanation.

After full power-off and cable removal, the detached boot had working display
and audio but failed controller input. InputPlumber logged source-device reads
failing with "No such device". Those messages alone do not establish the cause.
A subsequent normal detached restart restored controls, confirmed by the player.

Local evidence (ignored `out/`, not public raw logs):
- `usb-pm-fixed-050-final-check.txt`
- `usb-pm-fixed-050-failed-shutdown-retained.log`
- `usb-pm-fixed-050-shutdown-system-kernel-tail.log`
- `usb-pm-fixed-050-controller-after-hardoff.log`
- `usb-pm-fixed-050-restoration.jsonl`

## Next diagnostic gate

Do not repeat the same attached shutdown until late-stage capture is prepared.
Read-only inspection found the active pstore backend is `ramoops`, the persistent
archive directory is empty, and the pstore archival service is inactive. The
pstore filesystem and ramoops parameters require root to inspect. This does not
prove console retention is configured or that logs survive forced power-off.
The available network interface is Wi-Fi; SSH already disappears before the
unknown final shutdown stage and is insufficient as the only recorder.

Next inspect existing pstore records and ramoops console capacity read-only with
the player entering sudo locally. Preserve any existing records before making
changes. Verify actual installed-kernel support before selecting a reversible
capture configuration; do not blindly apply options from newer kernel docs.
No boot parameters, pstore settings, services, drivers or device states were
changed by this inspection. Keep the G1 detached and software frozen meanwhile.

Reference: [Linux shutdown debugging with pstore](https://cdn.kernel.org/doc/html/latest/power/shutdown-debugging.html).
Persistent console capture is a diagnostic possibility, not a validated solution
on this Ally. No live-removal support or GPU unbind/reset was tested or added.

### Read-only pstore follow-up

Player sudo inspection found an empty `/sys/fs/pstore`, `console_size=4096`,
`mem_size=5242880`, `record_size=2097152`, and `max_reason=2`.
Live `/proc/config.gz` inspection established `CONFIG_PSTORE=y` and
`CONFIG_PSTORE_RAM=m`, but `CONFIG_PSTORE_CONSOLE`, `CONFIG_PSTORE_PMSG`, and
`CONFIG_PSTORE_FTRACE` are not enabled. Therefore the console_size parameter
must not be described as an operational persistent console recorder. Increasing
that parameter alone cannot add the missing compiled support. max_reason=2
selects Oops/Panic dumps, not continuous capture of a silent shutdown hang.
No records were deleted and no settings were changed.

Reference: [Linux 6.16 ramoops documentation](https://www.kernel.org/doc/html/v6.16/admin-guide/ramoops.html).
The proposed persistent-console route is blocked on this installed kernel.
Next assess visible console capture or an independently connected supported
network console before considering a kernel change. Neither capture method is
validated on this Ally; do not repeat the attached hang simply to collect the
same journal cutoff, or trigger a deliberate panic as a substitute.

### Temporary visible-console diagnostic candidate

Read-only inspection found the active console and foreground VT are tty1;
manager logging is info/journal-or-kmsg and printk console level is 1.
plymouth-poweroff.service is static, inactive, with no /run or /etc override;
it starts the shutdown splash. The installed systemctl help confirms runtime
masks expire at reboot.

Proposed detached-only preparation (not yet applied/validated): runtime-mask
only plymouth-poweroff.service, set manager log-target=console and log-level=debug,
and set console printk level to 7. This changes diagnostic output and suppresses
the shutdown splash for this boot; it does not initiate shutdown. Verify command
results before a separately supervised normal detached poweroff. Screen visibility
is not guaranteed because graphics teardown can disable console output.

Rollback before reboot: systemctl log-level info; systemctl log-target
journal-or-kmsg; dmesg -n 1; systemctl unmask --runtime plymouth-poweroff.service.
These original values were read from the current device. Do not apply this
rollback to an unrelated machine or a later configuration without rechecking.
No G1 attach test is authorized by successful logging setup alone.
