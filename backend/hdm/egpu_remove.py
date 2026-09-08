"""Supervised operator tool for detaching an eGPU in software.

The companion to `hdm.egpu_release`. That tool clears the holders of an eGPU
and says so explicitly: clearing holders is not removal authority. This tool is
the step after it, and it is the only place in the plugin that asks the kernel
to detach the device.

What it does, in the order a supervised run establishes:

1. Observe once, read-only, and classify that observation for removal safety.
2. Compose the removal plan from that verdict: both PCI functions, audio first.
3. With ``--remove``: take a second, independent observation, require the
   device to still be the same device, then detach each function in order and
   verify each one is gone.
4. With ``--restore``: rescan the bus and report which functions came back.

Without ``--remove`` or ``--restore`` nothing is written. The default is a
plan: it reports what would happen and stops.

Two limits are worth stating before anyone runs this.

This is software removal, not physical disconnect. Safety invariant 10 stands:
a live unplug is unsupported, and nothing here changes that. Orderly removal
then unplug is the design; surprise unplug is not.

The freshness check is weaker than the domain contract reads. `plan_is_current`
compares attachment binding, generation and sample id, but the only producer of
a sample id mints a new one on every observation, so a genuinely fresh
observation can never match a composed plan. The confirming read here therefore
requires the attachment binding and the generation to be unchanged -- both
content-derived, so both real guards -- and reports the sample id as changed by
construction rather than pretending it revalidated. Issue #127 tracks deciding
the contract; the workaround here goes away when it is decided.

Usage on the device, from the installed plugin directory:

    PYTHONPATH=backend python3 -m hdm.egpu_remove
    sudo PYTHONPATH=backend python3 -m hdm.egpu_remove --remove
    sudo PYTHONPATH=backend python3 -m hdm.egpu_remove --restore
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Sequence

from .adapters.steamos.device_removal import SysfsDeviceRemoval
from .adapters.steamos.discovery import SteamOsDiscovery
from .adapters.steamos.peripherals import SteamOsPeripheralObservationAdapter
from .application.safe_undock_evidence import assess_removal_safety_report
from .application.snapshot import SnapshotService
from .domain.device_removal import (
    RemovalFunction,
    RemovalFunctionKind,
    RemovalPlan,
    RemovalPlanState,
    compose_removal_plan,
    plan_is_current,
)
from .domain.removal_safety import RemovalSafety, RemovalSafetyState
from .ports.device_removal import DeviceRemovalPort


def report(text: str = "") -> None:
    print(text, flush=True)


def section(title: str) -> None:
    report(f"\n=== {title} ===")


def egpu_functions(gpu_bdf: str) -> tuple[RemovalFunction, ...]:
    """Return both PCI functions of the eGPU, derived from the GPU address.

    Audio is function 1 of the same multi-function device. Deriving it rather
    than accepting it separately is the same choice `hdm.egpu_release` makes,
    for the same reason: the two cannot then disagree.
    """
    prefix, _, function = gpu_bdf.rpartition(".")
    return (
        RemovalFunction(RemovalFunctionKind.GPU, gpu_bdf),
        RemovalFunction(RemovalFunctionKind.AUDIO, f"{prefix}.{int(function) + 1}"),
    )


def snapshot_service() -> SnapshotService:
    return SnapshotService(
        SteamOsDiscovery(),
        peripheral_observation=SteamOsPeripheralObservationAdapter(),
    )


def observe(service: SnapshotService) -> RemovalSafety:
    """Take one read-only observation and classify it for removal safety."""
    return assess_removal_safety_report(service.observe())


def confirm_unchanged(plan: RemovalPlan, confirming: RemovalSafety) -> bool:
    """Report whether a second observation still describes the same device.

    A composed plan carries the identity of the observation that authorised it.
    This requires the confirming observation to be ready in its own right and
    to agree on attachment binding and generation. It does not require the
    sample id to match: sample ids are minted per observation, so requiring one
    would reject every confirming read rather than only the changed ones.
    """
    if not plan.usable:
        return False
    if confirming.state is not RemovalSafetyState.READY_FOR_SUPERVISED_REMOVAL:
        return False
    revalidation = confirming.revalidation
    if revalidation is None:
        return False
    return plan_is_current(
        plan,
        attachment_binding=revalidation.attachment_binding,
        generation=revalidation.observed_generation,
        sample_id=plan.sample_id,
    )


def execute(plan: RemovalPlan, removal: DeviceRemovalPort) -> int:
    """Detach every function in plan order, stopping at the first not gone."""
    for function in plan.functions:
        result = removal.remove(function.address)
        report(f"  {function.kind.value:5s} {result.address} -> {result.outcome.value}")
        if not result.ok:
            report(f"  stopping: {result.code}")
            report("  the device is part-detached; --restore rescans the bus.")
            return 1
    return 0


def restore(addresses: tuple[str, ...], removal: DeviceRemovalPort) -> int:
    result = removal.rescan(addresses)
    report(f"  {result.outcome.value}: {result.restored or '(nothing)'}")
    if not result.ok:
        report(f"  {result.code}")
        # Enumeration can lag the write, so this is a report, not a verdict.
        report("  re-run --restore if the bus had not finished enumerating.")
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hdm-egpu-remove", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument("--gpu", default="0000:08:00.0", help="eGPU PCI function")
    parser.add_argument(
        "--remove",
        action="store_true",
        help="detach both functions; without this nothing is written",
    )
    parser.add_argument(
        "--restore",
        action="store_true",
        help="rescan the bus and report which functions came back",
    )
    arguments = parser.parse_args(argv)

    if arguments.remove and arguments.restore:
        report("--remove and --restore are opposite actions; pick one")
        return 2
    if (arguments.remove or arguments.restore) and os.geteuid() != 0:
        report("writing to sysfs needs root")
        return 2

    functions = egpu_functions(arguments.gpu)
    addresses = tuple(function.address for function in functions)
    removal = SysfsDeviceRemoval()

    if arguments.restore:
        section("rescan the bus")
        return restore(addresses, removal)

    section("1. observe and classify")
    service = snapshot_service()
    readiness = observe(service)
    report(f"  {readiness.state.value} / {readiness.code}")

    section("2. compose the removal plan")
    plan = compose_removal_plan(readiness, functions)
    report(f"  {plan.state.value} / {plan.code}")
    if plan.state is not RemovalPlanState.COMPOSED:
        return 1
    for index, function in enumerate(plan.functions, start=1):
        report(f"  {index}. {function.kind.value:5s} {function.address}")

    if not arguments.remove:
        section("plan only")
        report("  nothing was written.")
        report("  re-run with --remove to detach these functions.")
        return 0

    section("3. confirm the device has not changed")
    confirming = observe(service)
    report(f"  {confirming.state.value} / {confirming.code}")
    if not confirm_unchanged(plan, confirming):
        report("  refusing to remove: the confirming observation does not match.")
        return 1
    report("  attachment and generation unchanged; sample id differs by construction.")

    section("4. detach, audio first")
    outcome = execute(plan, removal)
    if outcome:
        return outcome
    report("\n  both functions detached. This is NOT clearance to unplug:")
    report("  safety invariant 10 stands, a live physical unplug is unsupported.")
    report("  --restore rescans the bus and rebinds both functions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
