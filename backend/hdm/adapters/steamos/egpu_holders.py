"""Find what holds an eGPU, and say honestly what the scan could not see.

Extracted from `hdm.egpu_release`, which is an operator CLI. The plugin
backend needs the same reading to drive a disconnect behind an RPC, and a
delivery module importing a command-line tool is the wrong direction; both now
import this.

The completeness this carries is the point of the type. A bare tuple of unit
names cannot tell a device nothing holds from a scan that could not finish
looking, and an empty one then read as clear -- the fail-open removed in #137.
Every way the scan can fall short is counted separately so a refusal can name
which one happened.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


#: The DRI node kinds an eGPU exposes under /dev/dri/by-path.
DRI_NODES = ("card", "render")


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
