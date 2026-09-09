"""Supervised operator tool for detaching an eGPU in software.

The companion to ``hdm.egpu_release``. That tool clears the holders of an eGPU
and stops there, because clearing holders is not removal authority. This one
takes the next step: it composes a removal plan over a classified observation
and, only when explicitly asked, executes it through the single adapter that is
permitted to write to a device node.

It exists because the removal proven on an Ally X with a GPD G1 was driven by
hand. Every part it needs is already merged -- the port, the planner and the
writer -- but nothing composed them, so the run was neither repeatable nor
reviewable. This composes them and reports each step.

What it does, in order:

1. Observe one snapshot and classify it with ``assess_removal_safety``, over
   the same read-only path ``scripts/probe_safe_undock_readiness.py`` uses.
2. Compose the ordered removal plan for both PCI functions of the device.
3. With ``--remove``: take a *fresh* observation, recompose from it, confirm
   the attachment did not change between planning and acting, and only then
   detach each function in plan order, verifying each one.
4. With ``--rescan``: the defined recovery, restoring both functions by bus
   rescan.

Without ``--remove`` or ``--rescan`` nothing is written. The default is a plan:
it reports what would happen and stops.

On revalidation, which is easy to get subtly wrong. What must not change is
the *device*, and identity alone does not establish that removing it is still
safe, so ``--remove`` checks four separate things and refuses on any of them:
the fresh observation is ready in its own right, its attachment binding is the
one planning saw, its generation is unchanged, and the plan recomposed from it
has the same addresses as the plan that was reviewed.

This originally worked around a defect in ``plan_is_current``, which compared
a per-observation ``sample_id`` and so could never be satisfied by a fresh
reading. That is fixed upstream (issue #127): the predicate now compares
identity only, and states that identity is necessary and not sufficient. The
checks around it are still required and are kept.

Three things this deliberately does not do. It never spawns a process, keeping
``subprocess`` confined to the one adapter an architecture check permits it in.
It never clears holders; run ``hdm.egpu_release`` first if something still holds
the device, because ``clients_clear`` is one of the facts gating this tool. And
a successful removal is NOT clearance to unplug anything: safety invariant 10
stands, physical live unplug is unsupported, and the only supported shape is an
orderly removal followed by an unplug the operator decides on separately.

Usage on the device, from the installed plugin directory:

    PYTHONPATH=backend python3 -m hdm.egpu_remove
    sudo PYTHONPATH=backend python3 -m hdm.egpu_remove --remove
    sudo PYTHONPATH=backend python3 -m hdm.egpu_remove --rescan
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Sequence

from .adapters.steamos.device_removal import SysfsDeviceRemoval
from .adapters.steamos.discovery import SteamOsDiscovery
from .adapters.steamos.peripherals import SteamOsPeripheralObservationAdapter
from .application.safe_undock_evidence import build_safe_undock_evidence
from .application.snapshot import SnapshotService
from .domain.device_removal import (
    RemovalFunction,
    RemovalFunctionKind,
    RemovalPlan,
    RemovalPlanState,
    compose_removal_plan,
    plan_is_current,
)
from .domain.removal_safety import (
    RemovalSafety,
    RemovalSafetyState,
    assess_removal_safety,
)
from .ports.device_removal import DeviceRemovalPort


def report(text: str = "") -> None:
    print(text, flush=True)


def section(title: str) -> None:
    report(f"\n=== {title} ===")


def egpu_functions(gpu_bdf: str) -> tuple[str, str]:
    """Return the GPU and audio function addresses for `gpu_bdf`.

    A multi-function eGPU exposes audio as function 1 of the same device. This
    derives it rather than accepting it separately, so the two cannot disagree.
    Matches `hdm.egpu_release.egpu_functions`; both describe the same device.
    """
    prefix, _, function = gpu_bdf.rpartition(".")
    return gpu_bdf, f"{prefix}.{int(function) + 1}"


def removal_functions(gpu_bdf: str, audio_bdf: str) -> tuple[RemovalFunction, ...]:
    """Name both functions the planner requires.

    The planner orders them; this only states which exist. A plan covering one
    function of a multi-function device is refused there rather than here, so
    the refusal keeps a single home.
    """
    return (
        RemovalFunction(RemovalFunctionKind.GPU, gpu_bdf),
        RemovalFunction(RemovalFunctionKind.AUDIO, audio_bdf),
    )


def observe(service: SnapshotService) -> tuple[RemovalSafety, str]:
    """Classify one fresh observation for removal safety.

    Returns the verdict and the attachment binding it was taken against. The
    binding is returned even when the verdict is not ready, so a caller can
    report which device it looked at when explaining a refusal.
    """
    composed = build_safe_undock_evidence(service.observe())
    evidence = composed.evidence
    if evidence is None:
        return (
            RemovalSafety(RemovalSafetyState.EVIDENCE_INSUFFICIENT, composed.code),
            "",
        )
    return (
        assess_removal_safety(
            evidence,
            expected_attachment_binding=evidence.attachment_binding,
            expected_generation=evidence.generation,
            expected_sample_id=evidence.sample_id,
        ),
        evidence.attachment_binding,
    )


def describe_plan(plan: RemovalPlan) -> None:
    report(f"  {plan.state.value} / {plan.code}")
    if plan.usable:
        for index, function in enumerate(plan.functions, start=1):
            report(f"  {index}. detach {function.kind.value:5s} {function.address}")


def execute(plan: RemovalPlan, removal: DeviceRemovalPort) -> int:
    """Detach every function in plan order, stopping at the first that does not.

    Stopping leaves the device half-detached, which is why the rescan recovery
    is named in the failure report: the operator needs the next action, not
    only the code that ended the run.
    """
    for function in plan.functions:
        result = removal.remove(function.address)
        report(f"  {function.address}: {result.outcome.value} {result.code}".rstrip())
        if not result.ok:
            report("")
            report("  stopped. The device may be partially detached.")
            report("  restore it with: --rescan")
            return 1
    return 0


#: What to do about each refusal, keyed by the readiness code that caused it.
#: A refusal a reader cannot act on sends them somewhere useless, and the
#: generic advice this replaced did exactly that: run as an unprivileged user
#: with the holders already clear, it told the operator to go and clear the
#: holders.
NEXT_ACTION: dict[str, tuple[str, ...]] = {
    "removal_safety.clients_active_or_protected": (
        "holders are the blocker: clear them with hdm.egpu_release --arm.",
    ),
    "removal_safety.external_display_still_active": (
        "the external display is still active, which no holder release fixes.",
        "on the tested hardware this is the kernel console holding the eGPU",
        "CRTC after the compositor left it; see issue 168.",
    ),
    "removal_safety.game_running": (
        "a game is running; close it and re-observe.",
    ),
}


def next_action(code: str, euid: int) -> tuple[str, ...]:
    """Say what to do about this refusal, not merely that it happened.

    An incomplete client scan is reported specially when unprivileged,
    because the cause is almost always that this process cannot read other
    processes rather than anything about the device. Telling an operator to
    clear holders in that case is worse than saying nothing: the holders may
    already be clear, and re-running the release would achieve nothing.
    """
    if code == "removal_safety.client_scan_incomplete" and euid != 0:
        return (
            "the client scan could not finish, which unprivileged it usually",
            "cannot: it cannot read other processes. Re-run with sudo before",
            "concluding anything about holders.",
        )
    return NEXT_ACTION.get(code, ("re-observe once the reported fact changes.",))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hdm-egpu-remove", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument("--gpu", default="0000:08:00.0", help="eGPU PCI function")
    parser.add_argument(
        "--remove",
        action="store_true",
        help="execute the plan; without this nothing is written",
    )
    parser.add_argument(
        "--rescan",
        action="store_true",
        help="re-enumerate the bus to restore both functions, and nothing else",
    )
    arguments = parser.parse_args(argv)

    if arguments.remove and arguments.rescan:
        report("--remove and --rescan are separate operations; run one at a time.")
        return 2

    gpu_bdf, audio_bdf = egpu_functions(arguments.gpu)
    # `os.geteuid` is POSIX-only. Reaching this branch on a platform without it
    # means the sysfs writes could not work anyway, so refuse rather than crash.
    euid = getattr(os, "geteuid", None)
    if (arguments.remove or arguments.rescan) and (euid is None or euid() != 0):
        report("writing to sysfs needs root on a Linux device.")
        return 2

    removal = SysfsDeviceRemoval()

    if arguments.rescan:
        section("rescan")
        result = removal.rescan((audio_bdf, gpu_bdf))
        report(f"  {result.outcome.value} {result.code}".rstrip())
        report(f"  restored: {result.restored or '(none)'}")
        return 0 if result.ok else 1

    service = SnapshotService(
        # `DiagnosticsApi` wires discovery only, so Safe Undock evidence cannot
        # be composed from it. Compose the same read-only service here with the
        # peripheral observer attached, as the readiness probe does, rather
        # than widening the shared API surface for one operator tool.
        SteamOsDiscovery(),
        peripheral_observation=SteamOsPeripheralObservationAdapter(),
    )
    functions = removal_functions(gpu_bdf, audio_bdf)

    section("1. classify the observation")
    readiness, planned_binding = observe(service)
    report(f"  {readiness.state.value} / {readiness.code}")

    section("2. compose the removal plan")
    plan = compose_removal_plan(readiness, functions)
    describe_plan(plan)

    if not arguments.remove:
        section("plan only")
        report("  nothing was written.")
        if plan.usable:
            report("  re-run with --remove to execute this plan.")
        else:
            report("  the plan is not executable; the code above says why.")
            for line in next_action(readiness.code, os.geteuid() if hasattr(os, "geteuid") else 0):
                report(f"  {line}")
        return 0 if plan.usable else 1

    if not plan.usable:
        report("\n  refusing to remove: there is no executable plan.")
        return 1

    section("3. revalidate against a fresh observation")
    fresh, fresh_binding = observe(service)
    report(f"  {fresh.state.value} / {fresh.code}")
    if fresh.state is not RemovalSafetyState.READY_FOR_SUPERVISED_REMOVAL:
        report("  refusing to remove: readiness did not hold on re-observation.")
        return 1
    if fresh_binding != planned_binding:
        # A different attachment is a different device, whatever else matches.
        report("  refusing to remove: the attachment changed since planning.")
        return 1

    current = compose_removal_plan(fresh, functions)
    if current.state is not RemovalPlanState.COMPOSED:
        report(f"  refusing to remove: recompose failed / {current.code}")
        return 1
    if current.generation != plan.generation:
        # The observed device set changed while the plan was being reviewed.
        # The binding can stay identical across that, so this is a separate
        # question from whether the same eGPU is attached.
        report("  refusing to remove: the observation changed since planning.")
        return 1
    if not plan_is_current(
        current,
        attachment_binding=planned_binding,
        generation=plan.generation,
    ):
        report("  refusing to remove: the plan does not bind the fresh observation.")
        return 1
    if current.addresses != plan.addresses:
        report("  refusing to remove: the recomposed plan differs from the reviewed one.")
        return 1
    report("  the plan still describes the device that was observed.")

    section("4. detach")
    status = execute(current, removal)
    if status:
        return status
    report("")
    report("  both functions are detached. This is NOT clearance to unplug.")
    report("  restore them with: --rescan")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
