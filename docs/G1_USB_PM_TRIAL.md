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
used in supervised trials; the longer-wait revision has not yet been run.

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

Next trial: retain the exact installed Re-Gear and patched Loader, use the
600-second armed wait and explicitly select the existing 300-second hold. Test
TV and Portable before hold expiry. Do not shut down while the helper is active;
first verify restoration. Do not install another update during the trial.
