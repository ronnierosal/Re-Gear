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

## Parallel implementation follow-up

The post-intent USB preflight now repeats after durable I/O. Consent includes attachment binding and generation so a replacement at reused addresses cannot inherit the old approval. Ten transaction tests pass locally.

The Linux writer is confined to fixed controller `remove=1` and router `authorized=0` operations, using pinned directory identities and no-follow descriptor traversal. It is a primitive; the caller must still establish truthful topology and exclusive admission. The durable claim store uses exclusive creation, private root-owned descriptor traversal and fsync, retains claims on failure, and exposes no automatic clearing operation.

A fresh read-only topology inventory shows the PCI dock branch and Thunderbolt router beneath different host PCI paths on the Ally. A common-path guess cannot bind them. The current product-name tunnel lookup must remain diagnostic-only until a verified association is supplied. Existing storage observations do not include all raw block-device users; initial activation must either reject all attached storage or add complete raw-use checks.

Production runtime admission must be shared with automatic docking, recovery and presentation. A separate claim file alone does not stop those existing paths. These integration gates remain unresolved; no new installable version or physical disconnect claim is made.

### Kernel association found

Read-only inspection found a supplier/consumer device link connecting the dock's upstream PCI root port to the USB4 NHI. Linux v6.16 `drivers/thunderbolt/acpi.c`, `tb_acpi_add_links`, creates such links from the firmware `usb4-host-interface` reference. This provides a host association to investigate in the resolver, rather than treating unrelated sysfs path trees as an obstacle or guessing by product name. It still requires unambiguous external-router/branch association and stable attachment evidence before any write.

Source inspection only, no copied kernel code: https://github.com/torvalds/linux/blob/v6.16/drivers/thunderbolt/acpi.c . This source is a mechanism reference; the exact Valve kernel implementation remains a separate verification item.

### Live resolver verification and transaction integration

The new read-only resolver successfully bound the attached Ally/G1 topology and
revalidated its retained anchors on September 11. An initial failure came from
enumerating unrelated global device links; scoping observation to the NHI's
consumer links fixed it. Relevant missing endpoints and ambiguous consumers
still refuse binding. No device write was performed.

The production post-GPU port now joins fresh topology, storage observations,
durable ownership and guarded writes. Initial trials require an empty USB
peripheral branch. Local transaction/runtime tests pass; Linux-only filesystem
and topology fixtures still require verification for this combined revision.

Resource release must acquire the durable claim before starting and retain one
mutation admission scope through final verification. A transaction-local,
single-use continuation will join that release to the post-GPU executor.
Software reconnect remains unfinished; it must verify the same retained router
and freshly enumerated devices before releasing inhibition. There is no new
installable candidate or completed disconnect trial yet.

## 0.3.83 cable-connected trial controls

This candidate adds an explicitly confirmed operator path to the existing
`execute_egpu_disconnect` RPC. Ordinary UI calls retain their existing behavior.
Use `trial_action="whole_dock_disconnect"`, `trial_confirmed=true`, and
`release_display=true` with no relaunch app. Keep the physical cable connected.
Poll `get_egpu_disconnect_status` with `_request="whole_dock_trial"` across the
Steam session restart. Only a verified `software_down` permits the separate
`trial_action="whole_dock_reconnect"` call with the same confirmation flags.

The original plugin process retains the attachment binding; a plugin restart
refuses continuation. Both actions are tracked workers, so losing a browser/RPC
observer does not cancel a kernel operation. A dedicated sleep inhibitor covers
the transaction. Automatic presentation, recovery and native audio recovery
share mutation admission.

Reconnect performs one authorization write and bounded read-only enumeration.
It verifies retained host/router identity, hardware IDs and driver bindings,
then archives the completed claim after a further fresh verification. Only then
are ordinary gated actions available again. This does not verify picture/audio/
controls or authorize physical unplug. Partial outcomes retain the claim and
sleep inhibitor; do not retry writes or reinstall to bypass that state. Capture
the result and use supervised recovery. The preserved0.3.82 remains the rollback.

Current live evidence is read-only topology and driver binding validation on the
Ally/G1. New disconnect/reconnect hardware behavior remains untested.
