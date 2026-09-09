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

5. With ``--hold-open SECONDS``: once every holder has released, keep the
   filter attached for that long instead of detaching at once, so a supervised
   removal can run in a second terminal while ``clients_clear`` still holds.

Without ``--arm`` nothing is loaded or attached. The default is a plan: it
reports what would happen and stops.

Why ``--hold-open`` exists. ``clients_clear`` is a property of the filter being
attached, not a state the device settles into: the filter is what gates
``open()``, so the instant the link goes, WirePlumber and the session reopen
the nodes. Reporting "every holder released" and detaching in the same breath
therefore describes a condition that has already stopped being true. Anything
that must act on a clear device -- a supervised removal above all -- has to act
inside the filter's lifetime, and this is the window in which it can.

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
    sudo PYTHONPATH=backend python3 -m hdm.egpu_release --arm --hold 120 \
        --hold-open 180
"""

from __future__ import annotations

import argparse
import os
import time
from collections.abc import Sequence
from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class HolderScan:
    """What a holder scan found, and whether it managed to look everywhere.

    The previous version of this returned a bare tuple of unit names, so the
    four ways a scan can fail to see a holder were all indistinguishable from
    "nothing holds the device". An empty tuple then read as clear. This keeps
    the failures, because a scan that could not finish looking is not evidence
    of absence, and `clients_clear` is the fact the whole release sequence is
    judged on.
    """

    units: tuple[str, ...]
    unreadable_processes: int = 0
    unreadable_descriptors: int = 0
    unattributed_holders: int = 0
    nodes_incomplete: bool = False

    @property
    def complete(self) -> bool:
        """Whether the scan looked everywhere it needed to."""
        return not (
            self.unreadable_processes
            or self.unreadable_descriptors
            or self.unattributed_holders
            or self.nodes_incomplete
        )

    @property
    def clear(self) -> bool:
        """Whether the device is demonstrably held by nothing.

        Both halves are required. An incomplete scan that found no holders is
        not a clear device; it is an unanswered question, and answering it with
        "clear" is the failure this type exists to prevent.
        """
        return self.complete and not self.units

    def why_not_clear(self) -> tuple[str, ...]:
        """The specific reasons, so a refusal can be acted on rather than read."""
        reasons: list[str] = []
        if self.units:
            reasons.append(f"holders remain: {', '.join(self.units)}")
        if self.unreadable_processes:
            reasons.append(
                f"{self.unreadable_processes} process(es) could not be read;"
                " any of them may hold the device"
            )
        if self.unreadable_descriptors:
            reasons.append(
                f"{self.unreadable_descriptors} descriptor(s) could not be"
                " resolved; any of them may be an eGPU node"
            )
        if self.unattributed_holders:
            reasons.append(
                f"{self.unattributed_holders} holder(s) found but not"
                " attributable to a unit"
            )
        if self.nodes_incomplete:
            reasons.append(
                "the device node set was incomplete, so the scan looked for"
                " fewer nodes than the device exposes"
            )
        return tuple(reasons)


def scan_holders(
    nodes: tuple[str, ...],
    proc_root: Path = Path("/proc"),
    *,
    nodes_incomplete: bool = False,
) -> HolderScan:
    """Find every process holding one of `nodes`, and record what was missed.

    Holders are returned whatever their cgroup leaf. The earlier version kept
    only leaves ending in `.service`, which silently dropped a holder living in
    a `.scope` -- it was found, attributed, and then discarded. An unrestartable
    holder is a reason to refuse, not a reason to look away: the restart plan
    classifies it as unapproved downstream and declines, which is the outcome a
    `.scope` holder should produce.
    """
    wanted = set(nodes)
    units: set[str] = set()
    unreadable_processes = 0
    unreadable_descriptors = 0
    unattributed = 0
    for entry in sorted(proc_root.iterdir()):
        if not entry.name.isdigit():
            continue
        try:
            descriptors = list((entry / "fd").iterdir())
        except FileNotFoundError:
            # The process exited between listing and reading. Nothing was
            # missed: a process that no longer exists holds nothing.
            continue
        except OSError:
            unreadable_processes += 1
            continue
        held = False
        unresolved = 0
        for descriptor in descriptors:
            try:
                if os.readlink(descriptor) in wanted:
                    held = True
                    break
            except FileNotFoundError:
                continue
            except OSError:
                unresolved += 1
        if not held:
            # Only count unresolved descriptors for a process that did not
            # otherwise prove to be a holder; once it is known to hold the
            # device, its remaining descriptors change nothing.
            unreadable_descriptors += unresolved
            continue
        try:
            cgroup = (entry / "cgroup").read_text(encoding="utf-8").strip()
        except OSError:
            unattributed += 1
            continue
        leaf = cgroup.rsplit("/", 1)[-1]
        if leaf:
            units.add(leaf)
        else:
            unattributed += 1
    return HolderScan(
        tuple(sorted(units)),
        unreadable_processes,
        unreadable_descriptors,
        unattributed,
        nodes_incomplete,
    )


def node_paths(gpu_bdf: str, audio_bdf: str) -> tuple[tuple[str, ...], bool]:
    """Resolve the device node paths for both functions, for holder matching.

    Returns the resolved paths and whether the set is complete. A node that
    could not be resolved is not a node that does not exist: the scan then looks
    for fewer nodes than the device exposes, and a holder of the missing one is
    invisible to it. The completeness flag travels with the scan so that shows
    up as an incomplete answer rather than as a clear device.
    """
    resolved: list[str] = []
    complete = True
    for suffix in DRI_NODES:
        link = Path(f"/dev/dri/by-path/pci-{gpu_bdf}-{suffix}")
        try:
            resolved.append(str(link.resolve(strict=True)))
        except OSError:
            complete = False
    control = Path(f"/dev/snd/by-path/pci-{audio_bdf}")
    try:
        target = control.resolve(strict=True)
    except OSError:
        # Without the control node the audio function's other nodes cannot be
        # enumerated either, so the shortfall is the whole audio side.
        return tuple(resolved), False
    resolved.append(str(target))
    index = target.name.removeprefix("controlC")
    try:
        entries = sorted(Path("/dev/snd").iterdir())
    except OSError:
        return tuple(resolved), False
    for entry in entries:
        if entry.name.startswith((f"hwC{index}D", f"pcmC{index}D")):
            resolved.append(str(entry))
    return tuple(resolved), complete


def hold_open(
    nodes: tuple[str, ...],
    seconds: int,
    interval: float = 3.0,
    *,
    nodes_incomplete: bool = False,
) -> HolderScan | None:
    """Keep the caller inside the filter's lifetime for `seconds`.

    `clients_clear` is true only while the filter is attached: the filter is
    what gates `open()`. The moment the link goes, WirePlumber and the session
    reopen the nodes. A supervised removal therefore has to run inside this
    window, so this holds it open and watches it, rather than returning as soon
    as the device is first observed clear.

    Returns the scan that ended the window, or None if the device stayed clear
    for its whole length. Anything short of clear ends it immediately, including
    a scan that could no longer see everywhere: an operator inside this window is
    about to remove a device, so a lost ability to check must end it exactly as a
    returning holder does. Waiting either out would end by reporting a device
    that is no longer known to be clear.
    """
    deadline = time.monotonic() + max(0, seconds)
    while time.monotonic() < deadline:
        time.sleep(max(0.0, min(interval, deadline - time.monotonic())))
        scan = scan_holders(nodes, nodes_incomplete=nodes_incomplete)
        if not scan.clear:
            return scan
    return None


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
    parser.add_argument(
        "--hold-open",
        type=int,
        default=0,
        help="after every holder releases, keep the filter attached this many"
        " seconds so a supervised removal can run while clients_clear still"
        " holds; the default of 0 detaches immediately, as before",
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
    nodes, nodes_complete = node_paths(gpu_bdf, audio_bdf)
    scan = scan_holders(nodes, nodes_incomplete=not nodes_complete)
    observed = scan.units
    report(f"  holder units: {observed or '(none)'}")
    report(f"  scan complete: {scan.complete}")
    for reason in scan.why_not_clear():
        report(f"    - {reason}")
    coverage = classify_holder_units(observed)
    report(f"  reached by session target : {coverage.reached}")
    report(f"  need explicit restart     : {coverage.requires_explicit_restart}")
    report(f"  unapproved                : {coverage.unapproved}")

    plan = compose_restart_plan(observed, scan_complete=scan.complete)
    report(f"  plan: {plan.state.value} / {plan.code}")
    if plan.usable:
        report(f"  units: {plan.units or '(none)'}")

    if not arguments.arm:
        section("plan only")
        report("  nothing was loaded, attached or restarted.")
        report("  re-run with --arm to apply this plan.")
        return 0
    if not plan.usable:
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

            section("6. run these, as the session user, in another terminal")
            for command in restart_commands(plan.units, arguments.uid):
                report(f"  {command}")
            report("")
            report(f"  The filter is held for up to {arguments.hold}s while you do.")
            report("  Holders are re-checked every few seconds.")

            section("7. verify")
            deadline = time.monotonic() + max(0, arguments.hold)
            verified = scan_holders(nodes, nodes_incomplete=not nodes_complete)
            while not verified.clear and time.monotonic() < deadline:
                time.sleep(3)
                verified = scan_holders(
                    nodes, nodes_incomplete=not nodes_complete
                )
            if not verified.clear:
                # An incomplete scan lands here too. It is not a clear device,
                # and the reasons say which of the two happened.
                report("  clients_clear NOT established:")
                for reason in verified.why_not_clear():
                    report(f"    - {reason}")
                return 1
            report("  clients_clear: every holder released, scan complete")

            if arguments.hold_open > 0:
                section("8. hold the filter open")
                # Reporting the window explicitly, because the property an
                # operator is about to rely on is not "the device was clear"
                # but "the device is clear right now, and stays clear while
                # this link exists".
                report("  clients_clear holds only while this filter is attached.")
                report("  Run the supervised removal now, in another terminal:")
                report(
                    "    sudo PYTHONPATH=backend python3 -m hdm.egpu_remove"
                    f" --gpu {gpu_bdf} --remove"
                )
                report("")
                report(f"  The window is {arguments.hold_open}s. Holders are re-checked.")
                ended = hold_open(
                    nodes,
                    arguments.hold_open,
                    nodes_incomplete=not nodes_complete,
                )
                if ended is not None:
                    report("\n  the window ended early:")
                    for reason in ended.why_not_clear():
                        report(f"    - {reason}")
                    report("  clients_clear no longer holds; do not remove.")
                    return 1
                report("  the window closed with the device still clear.")

            report("\n  The eGPU is released. This is NOT removal clearance.")
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
