"""Supervised operator tool for releasing an eGPU's holders.

Ships inside the plugin, so it survives reboots and updates rather than living
in a temporary directory. It is an operator tool, not the player feature: there
is no UI, nothing runs automatically, and every step reports what it did.

What it does, in the order the supervised hardware runs established:

1. Discover the exact character devices of both eGPU PCI functions.
2. Compose the device policy those functions require. A policy covering only
   the render path is refused, because one retained audio handle keeps the
   device held.
3. Compile the policy to a cgroup device program.
4. With ``--arm``: attach it at the user manager cgroup, verify the program is
   actually enforced, print the restart commands an approved plan calls for,
   and re-observe holders while you run them.

Without ``--arm`` nothing is loaded or attached. The default is a plan: it
reports what would happen and stops.

It never spawns a process. ``subprocess`` appears in exactly one adapter in
this codebase, enforced by an architecture check, and the approved
user-service operations do not currently include the audio units. Opening a
second spawning path outside that boundary to save the operator two commands
would be the wrong trade.

Two things this deliberately does not do. It never removes a device; clearing
holders is not removal authority. And the link it attaches is unpinned, so it
disappears when this process exits — convenient for a supervised run, and
explicitly NOT durable recovery, because a crash silently returns the system to
unfiltered with nothing recording that it happened. A production caller needs
journalled ownership instead.

Usage on the device, from the installed plugin directory:

    sudo PYTHONPATH=backend python3 -m hdm.egpu_release
    sudo PYTHONPATH=backend python3 -m hdm.egpu_release --arm --hold 120
"""

from __future__ import annotations

import argparse
import os
import time
from collections.abc import Sequence
from pathlib import Path

from .adapters.steamos.egpu_device_nodes import SteamOsEgpuDeviceNodeDiscovery
from .delivery.device_filter_kernel import CgroupDeviceLink
from .delivery.device_filter_program import compile_device_filter
from .domain.egpu_device_policy import DevicePolicyState, compose_egpu_device_policy
from .domain.filter_arm_sequence import (
    ArmSequenceState,
    classify_holder_units,
    compose_restart_plan,
)


DRI_NODES = ("card", "render")
USER_MANAGER = "/sys/fs/cgroup/user.slice/user-{uid}.slice/user@{uid}.service"


def report(text: str = "") -> None:
    print(text, flush=True)


def section(title: str) -> None:
    report(f"\n=== {title} ===")


def egpu_functions(gpu_bdf: str) -> tuple[str, str]:
    """Return the GPU and audio function addresses for `gpu_bdf`.

    A multi-function eGPU exposes audio as function 1 of the same device. This
    derives it rather than accepting it separately, so the two cannot disagree.
    """
    prefix, _, function = gpu_bdf.rpartition(".")
    return gpu_bdf, f"{prefix}.{int(function) + 1}"


def holder_units(nodes: tuple[str, ...], proc_root: Path = Path("/proc")) -> tuple[str, ...]:
    """Read the systemd unit of every process holding one of `nodes`."""
    wanted = set(nodes)
    units: set[str] = set()
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            descriptors = list((entry / "fd").iterdir())
        except OSError:
            continue
        held = False
        for descriptor in descriptors:
            try:
                if os.readlink(descriptor) in wanted:
                    held = True
                    break
            except OSError:
                continue
        if not held:
            continue
        try:
            cgroup = (entry / "cgroup").read_text(encoding="utf-8").strip()
        except OSError:
            continue
        leaf = cgroup.rsplit("/", 1)[-1]
        if leaf.endswith(".service"):
            units.add(leaf)
    return tuple(sorted(units))


def node_paths(gpu_bdf: str, audio_bdf: str) -> tuple[str, ...]:
    """Resolve the device node paths for both functions, for holder matching."""
    resolved: list[str] = []
    for suffix in DRI_NODES:
        link = Path(f"/dev/dri/by-path/pci-{gpu_bdf}-{suffix}")
        try:
            resolved.append(str(link.resolve(strict=True)))
        except OSError:
            continue
    control = Path(f"/dev/snd/by-path/pci-{audio_bdf}")
    try:
        target = control.resolve(strict=True)
    except OSError:
        return tuple(resolved)
    resolved.append(str(target))
    index = target.name.removeprefix("controlC")
    for entry in sorted(Path("/dev/snd").iterdir()):
        if entry.name.startswith((f"hwC{index}D", f"pcmC{index}D")):
            resolved.append(str(entry))
    return tuple(resolved)


def restart_commands(units: tuple[str, ...], uid: int) -> tuple[str, ...]:
    """Return the commands an operator runs to apply the plan.

    This tool does not spawn them. `subprocess` appears in exactly one adapter
    in this codebase, with an architecture check enforcing that, and the
    approved user-service operations do not currently include the audio units.
    Rather than open a second spawning path outside that boundary, the operator
    runs these while the filter is held.
    """
    prefix = f"XDG_RUNTIME_DIR=/run/user/{uid} systemctl --user"
    return tuple(f"{prefix} restart {unit}" for unit in units)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hdm-egpu-release", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument("--gpu", default="0000:08:00.0", help="eGPU PCI function")
    parser.add_argument("--uid", type=int, default=1000, help="session user id")
    parser.add_argument(
        "--arm",
        action="store_true",
        help="attach the filter and run the restart plan; without this nothing"
        " is loaded, attached or restarted",
    )
    parser.add_argument(
        "--hold",
        type=int,
        default=60,
        help="seconds to hold the filter after arming before detaching",
    )
    arguments = parser.parse_args(argv)

    if arguments.arm and os.geteuid() != 0:
        report("--arm needs root: loading a program and restarting units")
        return 2

    gpu_bdf, audio_bdf = egpu_functions(arguments.gpu)

    section("1. discover the exact device set")
    scan = SteamOsEgpuDeviceNodeDiscovery().scan(gpu_bdf=gpu_bdf, audio_bdf=audio_bdf)
    if not scan.complete:
        report(f"  discovery incomplete: {scan.error}")
        return 1
    for node in scan.nodes:
        report(f"  {node.kind.value:16s} {node.major}:{node.minor}")

    section("2. compose the policy")
    policy = compose_egpu_device_policy(scan.nodes)
    report(f"  {policy.state.value} / {policy.code}")
    if policy.state is not DevicePolicyState.COMPOSED:
        return 1
    report(f"  {len(policy.devices)} devices")

    section("3. compile")
    program = compile_device_filter(policy.devices)
    report(f"  {len(program)} bytes, {len(program) // 8} instructions")

    section("4. observe holders")
    nodes = node_paths(gpu_bdf, audio_bdf)
    observed = holder_units(nodes)
    report(f"  holder units: {observed or '(none)'}")
    coverage = classify_holder_units(observed)
    report(f"  reached by session target : {coverage.reached}")
    report(f"  need explicit restart     : {coverage.requires_explicit_restart}")
    report(f"  unapproved                : {coverage.unapproved}")

    plan = compose_restart_plan(observed)
    report(f"  plan: {plan.state.value} / {plan.code}")
    if plan.state is ArmSequenceState.COMPOSED:
        report(f"  units: {plan.units}")

    if not arguments.arm:
        section("plan only")
        report("  nothing was loaded, attached or restarted.")
        report("  re-run with --arm to apply this plan.")
        return 0
    if plan.state is not ArmSequenceState.COMPOSED:
        report("\n  refusing to arm: the restart plan is not approved.")
        return 1

    cgroup_path = USER_MANAGER.format(uid=arguments.uid)
    if not Path(cgroup_path).is_dir():
        report(f"\n  cgroup missing: {cgroup_path}")
        return 1

    section(f"5. arm at {cgroup_path}")
    cgroup_fd = os.open(cgroup_path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        with CgroupDeviceLink() as link:
            link.load(program)
            program_id = link.program_id()
            link.attach(cgroup_fd)
            report(f"  attached: program_id={program_id}")

            # Enforcement before disruption: a link the kernel accepted is not
            # proof that this program decides opens on that cgroup.
            attached = link.query_program_ids(cgroup_fd)
            if program_id not in attached:
                report("  enforcement unverified; detaching without restarting")
                return 1
            report("  enforcement verified")

            section("6. restart exactly the planned units")
            for unit in plan.units:
                ok = restart_unit(unit, arguments.uid)
                report(f"  {unit}: {'restarted' if ok else 'FAILED'}")
                if not ok:
                    report("  detaching after a failed restart")
                    return 1
            for _ in range(40):
                time.sleep(3)
                if not holder_units(nodes):
                    break

            section("7. verify")
            remaining = holder_units(nodes)
            if remaining:
                report(f"  holders remain: {remaining}")
                return 1
            report("  clients_clear: every holder released")
            report("\n  The eGPU is released. This is NOT removal clearance.")
            report(f"  Holding the filter for {arguments.hold}s, then detaching.")
            time.sleep(max(0, arguments.hold))
    finally:
        os.close(cgroup_fd)
        section("detached")
        report("  the link was unpinned and is gone; this is not durable recovery.")
        report("  restore normal access by running, as the session user:")
        for command in restart_commands(
            ("wireplumber.service", "gamescope-session.target"), arguments.uid
        ):
            report(f"    {command}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
