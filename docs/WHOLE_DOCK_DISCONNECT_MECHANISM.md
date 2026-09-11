# Whole-dock disconnect investigation — September 11, 2026

## Goal and preserved baseline

One player action: return to the internal display, release dock resource users, verify release, execute supported dock-level teardown, then verify the entire relevant connection before offering cable clearance. Keep installed 0.3.82 and tag `checkpoint/0.3.82-auto-tv` unchanged. This investigation contains no device writes or unplug trial.

## Current evidence

Reviewed origin/main 280d760 and existing issue #105. The historical issue records USB-branch ACS violations and xHCI AER recovery failure, separately from successful GPU/audio software removal. It does not establish that a generic USB eject resolves that failure.

A fresh read-only run of the existing removal-capability collector on the attached Ally reports domain deauthorization supported, user security, and an authorized external router. Router identifiers were not published. The collector explicitly leaves GPU-to-router binding unverified. This establishes a available kernel capability, not a writable privileged path or whole-dock removal success.

## Existing code to retain

- `backend/regear/application/live_disconnect.py` and `delivery/live_disconnect_runtime.py`: guarded resource release and GPU/audio removal flow.
- `backend/regear/domain/dock_teardown.py`: existing pure decision contract for the remaining dock; requires removed GPU, complete unused-storage evidence, supported identified tunnel, scoped approval and complete observations.
- `backend/regear/adapters/steamos/dock_branch.py`: read-only USB/storage/tunnel observations. It is not an executor.
- Canonical follow-up task: `egpu-whole-dock-teardown-executor`. Do not replace these contracts with an independent eject path.

## Linux mechanism boundary

The kernel documents Thunderbolt deauthorization as PCIe-tunnel teardown, equivalent to PCIe hot removal. It is a candidate final operation after driver/resource release, not a storage eject and not proof that all USB/DisplayPort paths vanish. USB4 port offline is documented for retimer maintenance, so it is not adopted as a generic eject command.

UDisks drive power-off deconfigures a USB storage device and disables its upstream hub port. Its drive-oriented API is not a verified eject contract for an entire USB4 eGPU dock.

Sources: https://www.kernel.org/doc/html/latest/admin-guide/thunderbolt.html and https://storaged.org/udisks/docs/gdbus-org.freedesktop.UDisks2.Drive.html . Existing repository research: PREPARED_EGPU_REMOVAL_RESEARCH.md.

## Next implementation boundary

1. Bind GPU, audio, sibling USB controller and router using actual topology; never device-name matching alone. Review the existing tunnel observer's domain selection before mutation use.
2. Preflight the final operation before releasing anything: capability, exact target, privileged access, complete storage and topology evidence.
3. Extend the existing serialized removal transaction with remaining-USB and tunnel steps; inhibit automatic recovery/docking for the transaction and preserve that inhibition after partial failure. The new 0.3.82 attachment-recovery policy must not mistake intentional teardown for a new recoverable attachment.
4. Revalidate after each step and record durable progress. A timed-out kernel write is unresolved, not cancelled; never issue competing retries.
5. First verify software teardown with the cable connected, then separately validate physical unplug/reconnect on the supported profile. Unknown, partial, or unverified branches never grant clearance.

No supported universal whole-USB-C eject operation has been established. The current concrete candidate is ordered release followed by exact supported PCIe-tunnel teardown, with explicit verification of any remaining dock functions. Next work belongs to the canonical executor task after topology and current ownership review.

## Initial implementation

`application/whole_dock_teardown.py` now executes the post-GPU sequence through an explicit port: preflight, exclusive durable claim, fresh recheck, USB removal intent/action/readback, fresh tunnel recheck, deauthorization, final readback. It reuses the existing domain decision. Exceptions and partial results retain ownership; no automatic retry or restore is issued. Its result always leaves physical unplug clearance false.

Eight targeted regression tests cover ordering, storage/GPU/idle refusal, attachment changes, late GPU return, unreadable final state, write timeout, journal failure and concurrent/reentrant calls. Architecture and diff checks pass.

This is an executor core with a test port, not a production Linux writer or installed feature. A real port must implement atomic persistent claim/inhibition, full fresh topology and privileged storage observation, immediately revalidated exact sysfs operations and interrupted-operation recovery. Those requirements cannot be replaced by the in-memory test port. Production wiring and supervised hardware validation remain open under the existing whole-dock executor workstream.
