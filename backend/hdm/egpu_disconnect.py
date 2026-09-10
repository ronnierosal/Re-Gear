"""Supervised operator tool that runs a live eGPU disconnect end to end.

`hdm.egpu_release` clears the holders and stops. `hdm.egpu_remove` classifies
removal safety and detaches. `LiveDisconnectService` orders the whole thing --
recover, release, observe afresh, decide, revalidate, record, remove, verify,
disarm -- and had no caller on a device. This is that caller.

It composes the real adapters and nothing else: the cgroup device filter, the
sysfs device writer, the DRM display release, the durable transaction store,
and the same read-only observation path the readiness probe uses.

## The restarts, which are the interesting part

The sequence needs approved unit restarts, and this tool does not spawn them.
`subprocess` appears in exactly one adapter in this codebase, with an
architecture check enforcing that, and the approved user-service operations do
not include these units. Widening that boundary is a separate decision with its
own review, and it is not taken here.

So `restart(unit)` is satisfied by **observation instead of action**. The tool
prints the exact command, the operator runs it in another terminal, and the
step succeeds only when a fresh holder scan shows that unit no longer holding
the device. The coordinator's contract is met, and the change in meaning is
worth stating plainly: it reports that the unit *got* restarted, not that this
tool restarted it. A unit that never held the device passes immediately,
because there is nothing to wait for.

That is weaker than an unattended flow needs and exactly right for a supervised
one. A player-facing path will need the approved operations widened, and that
is tracked separately.

## What it will and will not do

Without `--execute` nothing is loaded, attached, restarted, released or
removed: it observes, composes the plan, and reports what would happen.

`--release-display` is a separate approval from the disconnect. On the tested
hardware the eGPU keeps a mode committed after the return, held by the kernel's
own fbdev client, and taking DRM master to turn that CRTC off is what clears
it. It is scoped to the eGPU's card, and the console's mode returns when the
descriptor closes -- including if this process is killed.

A successful removal is **not** clearance to unplug anything. Safety invariant
10 stands, physical live unplug is unsupported on the tested configuration, and
whether an unplug may follow a verified software removal is a separate question.

Usage on the device, from a source checkout:

    PYTHONPATH=backend python3 -m hdm.egpu_disconnect
    sudo PYTHONPATH=backend python3 -m hdm.egpu_disconnect --execute --release-display
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from .adapters.steamos.cgroup_identity import observe_user_manager_cgroup
from .adapters.steamos.device_filter import CgroupDeviceFilter
from .adapters.steamos.device_removal import SysfsDeviceRemoval
from .adapters.steamos.drm_display_release import DrmDisplayRelease
from .adapters.steamos.egpu_device_nodes import SteamOsEgpuDeviceNodeDiscovery
from .adapters.steamos.owner_identity import observe_owner_identity, read_boot_hash
from .adapters.steamos.session_restart import await_units_released
from .delivery.live_disconnect_runtime import (
    EXTERNAL_CARD,
    STORE_ROOT,
    disconnect_snapshot_service,
    observe_display,
    observe_removal,
    present_addresses,
)
from .application.filter_arm import FilterArmCoordinator, HolderObservation
from .application.live_disconnect import (
    LiveDisconnectService,
    LiveDisconnectStage,
)
from .delivery.device_filter_program import compile_device_filter
from .delivery.removal_transaction_store import FileRemovalTransactionStore
from .domain.egpu_device_policy import DevicePolicyState, compose_egpu_device_policy
from .domain.filter_arm_sequence import units_cleared_by
from .domain.filter_authorization import authorize_parent_scope
from .egpu_release import (
    egpu_functions,
    node_paths,
    report,
    restart_commands,
    scan_holders,
    section,
)
from .egpu_remove import removal_functions




#: What to do about each outcome. A refusal a reader cannot act on sends them
#: nowhere, which is the failure `hdm.egpu_remove` fixed for its own codes.
NEXT_ACTION: dict[LiveDisconnectStage, tuple[str, ...]] = {
    LiveDisconnectStage.RELEASE_REFUSED: (
        "the release did not reach a clear device; run hdm.egpu_release --arm",
        "to see which step refused and why.",
    ),
    LiveDisconnectStage.HOLDERS_REMAIN: (
        "holders remain after the restarts. Check the reported units; a holder",
        "in a .scope is not restartable by this plan and refuses by design.",
    ),
    LiveDisconnectStage.NOT_SAFE_AFTER_RELEASE: (
        "the release worked and something else blocks. The code above names",
        "which fact; a standing external display is the usual one, and",
        "--release-display addresses that case.",
    ),
    LiveDisconnectStage.ENFORCEMENT_LOST: (
        "the filter stopped being enforced before the write. Nothing was",
        "removed. Re-run; if it repeats, the cgroup is being recreated.",
    ),
    LiveDisconnectStage.IDENTITY_CHANGED: (
        "the device changed between planning and writing. Re-run from a fresh",
        "observation.",
    ),
    LiveDisconnectStage.RECOVERED_PRIOR_REMOVAL: (
        "a previous removal was interrupted and has been restored. Re-run from",
        "a fresh observation.",
    ),
    LiveDisconnectStage.RECOVERY_FAILED: (
        "a previous removal was interrupted and could NOT be restored. The",
        "device is half attached. Restore it with hdm.egpu_remove --rescan.",
    ),
    LiveDisconnectStage.REMOVAL_UNRECOVERABLE: (
        "a function did not detach and the restore failed. The device is half",
        "attached. Restore it with hdm.egpu_remove --rescan.",
    ),
    LiveDisconnectStage.RECORD_UNREADABLE: (
        "the durable record could not be read, and it may describe a",
        f"half-detached device. Inspect {STORE_ROOT} before re-running.",
    ),
}


def describe(result, *, gpu_bdf: str) -> None:
    report(f"  {result.stage.value} / {result.code}")
    report(f"  released={result.released}  session_disturbed={result.session_disturbed}")
    if result.display_release_code:
        report(
            f"  display: {result.display_release_code}"
            f"  released={result.display_released or '(none)'}"
        )
    if result.removed:
        report(f"  removed: {result.removed}")
    if result.restored:
        report(f"  restored by rescan: {result.restored}")
    report(f"  filter disarmed: {result.filter_disarmed}")
    if result.ok:
        report("")
        report("  Both functions are detached. This is NOT clearance to unplug.")
        report(f"  Restore them with: hdm.egpu_remove --rescan --gpu {gpu_bdf}")
        return
    for line in NEXT_ACTION.get(result.stage, ("re-observe once the reported fact changes.",)):
        report(f"  {line}")


def main(argv: Sequence[str] = ()) -> int:
    parser = argparse.ArgumentParser(
        prog="hdm-egpu-disconnect", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument("--gpu", default="0000:08:00.0", help="eGPU PCI function")
    parser.add_argument("--uid", type=int, default=1000, help="session user id")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="arm the filter and run the transaction; without this nothing is"
        " loaded, attached, restarted, released or removed",
    )
    parser.add_argument(
        "--release-display",
        action="store_true",
        help="approve taking DRM master on the eGPU card to turn a committed"
        " external mode off for the duration of the removal",
    )
    parser.add_argument(
        "--restart-timeout",
        type=float,
        default=90.0,
        help="seconds to wait for each unit to release the device after you"
        " run its restart command",
    )
    parser.add_argument("--store-root", default=str(STORE_ROOT), help="record directory")
    arguments = parser.parse_args(argv)

    gpu_bdf, audio_bdf = egpu_functions(arguments.gpu)
    euid = getattr(os, "geteuid", None)
    if arguments.execute and (euid is None or euid() != 0):
        report("--execute needs root: loading a program and writing to sysfs.")
        return 2

    section("1. discover the exact device set")
    scan = SteamOsEgpuDeviceNodeDiscovery().scan(gpu_bdf=gpu_bdf, audio_bdf=audio_bdf)
    if not scan.complete:
        report(f"  discovery incomplete: {scan.error}")
        return 1
    policy = compose_egpu_device_policy(scan.nodes)
    report(f"  {policy.state.value} / {policy.code}  ({len(policy.devices)} devices)")
    if policy.state is not DevicePolicyState.COMPOSED:
        return 1
    program = compile_device_filter(policy.devices)
    report(f"  program: {len(program)} bytes")

    section("2. authorize the parent scope")
    cgroup = observe_user_manager_cgroup(arguments.uid)
    owner = observe_owner_identity()
    boot_hash = read_boot_hash()
    observation = observe_removal(disconnect_snapshot_service())
    report(f"  cgroup: {cgroup.path if cgroup else '(unreadable)'}")
    report(f"  owner: {owner}")
    report(f"  boot hash: {'read' if boot_hash else '(unreadable)'}")
    report(f"  readiness now: {observation.readiness.state.value} / {observation.readiness.code}")
    if cgroup is None or owner is None or not boot_hash:
        report("\n  refusing: the grant cannot be bound to this scope, owner and boot.")
        return 1

    authorization = authorize_parent_scope(
        cgroup=cgroup,
        uid=arguments.uid,
        session_uid=arguments.uid,
        owner=owner,
        boot_hash=boot_hash,
        attachment_binding=observation.attachment_binding,
        generation=observation.generation,
        sample_id=observation.sample_id,
        deadline=time.monotonic() + max(60.0, arguments.restart_timeout * 4),
    )
    report(f"  {authorization.state.value} / {authorization.code}")
    if not authorization.granted:
        return 1

    section("3. observe holders")
    nodes, nodes_complete = node_paths(gpu_bdf, audio_bdf)
    holders = scan_holders(nodes, nodes_incomplete=not nodes_complete)
    report(f"  holder units: {holders.units or '(none)'}")
    report(f"  scan complete: {holders.complete}")
    for reason in holders.why_not_clear():
        report(f"    - {reason}")

    section("4. observe the displays")
    display = observe_display(nodes, nodes_incomplete=not nodes_complete)
    report(f"  external committed crtcs: {display.external_committed or '(none)'}")
    report(f"  internal committed: {display.internal_committed}")

    if not arguments.execute:
        section("plan only")
        report("  nothing was loaded, attached, restarted, released or removed.")
        report("  re-run with --execute to perform the disconnect.")
        if display.external_committed and not arguments.release_display:
            report("  note: an external mode is committed; add --release-display")
            report("  to approve turning it off for the duration of the removal.")
        return 0

    store_root = Path(arguments.store_root)
    store_root.mkdir(parents=True, exist_ok=True)

    device_filter = CgroupDeviceFilter()
    restart_deadline = arguments.restart_timeout

    def restart(unit: str) -> bool:
        """Print the command, then wait for what it should release to let go."""
        report("")
        for command in restart_commands((unit,), arguments.uid):
            report(f"  run this now, as the session user: {command}")
        observe = lambda: scan_holders(
            nodes, nodes_incomplete=not nodes_complete
        ).units
        expected = units_cleared_by(unit, observe())
        if not expected:
            report(f"  nothing observed is held by {unit}; continuing")
            return True
        report(f"  waiting up to {restart_deadline:.0f}s for {', '.join(expected)}")
        released = await_units_released(
            expected,
            observe,
            deadline=time.monotonic() + restart_deadline,
            now=time.monotonic,
            sleep=time.sleep,
        )
        report(f"  {unit}: {'released' if released else 'still holding'}")
        return released

    service = LiveDisconnectService(
        coordinator=FilterArmCoordinator(
            device_filter=device_filter,
            restart=restart,
            observe_holders=lambda: _holder_observation(nodes, nodes_complete),
            observe_cgroup=lambda: observe_user_manager_cgroup(arguments.uid),
            monotonic=time.monotonic,
        ),
        device_filter=device_filter,
        removal=SysfsDeviceRemoval(),
        display_release=DrmDisplayRelease(),
        store=FileRemovalTransactionStore(store_root),
        observe=lambda: observe_removal(disconnect_snapshot_service()),
        observe_display=lambda: observe_display(
            nodes, nodes_incomplete=not nodes_complete
        ),
        display_node=EXTERNAL_CARD,
        present_addresses=lambda: present_addresses(gpu_bdf, audio_bdf),
        removal_functions=lambda: removal_functions(gpu_bdf, audio_bdf),
        now_ns=time.time_ns,
        owner_id="regear",
        device_set=observation.attachment_binding or "egpu",
    )

    section("5. run the disconnect")
    result = service.disconnect(
        authorization,
        program,
        boot_hash=boot_hash,
        release_display=arguments.release_display,
    )

    section("6. outcome")
    describe(result, gpu_bdf=gpu_bdf)
    return 0 if result.ok else 1


def _holder_observation(nodes: tuple[str, ...], nodes_complete: bool) -> HolderObservation:
    """Project the operator scan onto what the coordinator consumes.

    `complete` is carried across rather than dropped: the coordinator refuses a
    clear-looking result from a scan that could not finish, which is the whole
    reason the observation is a type and not a tuple of names.
    """
    scan = scan_holders(nodes, nodes_incomplete=not nodes_complete)
    return HolderObservation(scan.units, scan.complete)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
