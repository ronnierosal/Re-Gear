"""Supervised, self-restoring check that the console-held eGPU CRTC releases.

Answers the one thing #168 cannot settle by reading: does turning the CRTC off
actually clear the committed mode on this kernel, and does the console's mode
come back when the descriptor closes.

What it does, in order:

1. Observe both cards' CRTCs read-only, and scan for processes holding the
   eGPU's card node.
2. Ask `decide_display_release`. Without `--release` it stops here and reports
   what would have happened; nothing is opened for writing and no master is
   taken.
3. With `--release`, hold the release for `--hold` seconds, reading the CRTC
   back while it is held, then restore.

The restore is not a step this has to remember. `HeldDisplayRelease` closes the
descriptor in a `finally`, and the kernel puts the console's mode back when the
last descriptor on the device goes -- including if this process is killed
partway through. The visible effect on an external display that is powered on
is a blank for the length of the hold, then the console again.

This removes nothing, detaches nothing, and touches no card but the eGPU's. It
is not a claim that any device is safe to unplug.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections.abc import Sequence
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from hdm.adapters.steamos.drm_crtc import DrmCrtcProbe  # noqa: E402
from hdm.adapters.steamos.drm_display_release import DrmDisplayRelease  # noqa: E402
from hdm.domain.display_release import (  # noqa: E402
    DisplayReleaseEvidence,
    DisplayReleaseState,
    decide_display_release,
)


def report(text: str = "") -> None:
    print(text, flush=True)


def section(title: str) -> None:
    report(f"\n=== {title} ===")


def holders(node: str, render_node: str) -> tuple[tuple[str, ...], bool]:
    """Return processes holding either eGPU node, and whether the scan finished.

    A process whose descriptors cannot be read makes the scan incomplete rather
    than absent from it: an empty list from a scan that could not look is the
    fail-open this project removed elsewhere.
    """
    found: set[str] = set()
    complete = True
    try:
        entries = list(Path("/proc").iterdir())
    except OSError:
        # No procfs at all. Nothing was looked at, so the scan did not finish.
        return (), False
    for entry in entries:
        if not entry.name.isdigit():
            continue
        directory = entry / "fd"
        try:
            descriptors = list(directory.iterdir())
        except FileNotFoundError:
            # The process exited between listing and reading it. Nothing is
            # missed: a process that is gone holds nothing.
            continue
        except PermissionError:
            complete = False
            continue
        for descriptor in descriptors:
            try:
                target = os.readlink(descriptor)
            except OSError:
                continue
            if target in (node, render_node):
                name = (entry / "comm").read_text(encoding="utf-8").strip()
                found.add(f"{name}[{entry.name}]")
    return tuple(sorted(found)), complete


def sysfs_view(card: str) -> tuple[str, ...]:
    """What the existing removal-safety gate would see, read from sysfs.

    The gate grades `external_display_active` from `DrmConnectorRecord`, whose
    `mode_committed` comes from `enabled` -- which reports whether an encoder
    is attached, not whether a mode is committed. Capturing it beside the CRTC
    reading is the only way to learn whether turning the CRTC off is enough for
    the gate as it stands, or whether the gate has to read the CRTC too.
    """
    lines = []
    root = Path("/sys/class/drm")
    try:
        connectors = sorted(root.glob(f"{card}-*"))
    except OSError:
        return ("  (sysfs unreadable)",)
    for connector in connectors:
        try:
            status = (connector / "status").read_text(encoding="utf-8").strip()
            enabled = (connector / "enabled").read_text(encoding="utf-8").strip()
            dpms = (connector / "dpms").read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if status != "connected":
            continue
        lines.append(f"  {connector.name}: status={status} enabled={enabled} dpms={dpms}")
    for address in ("0000:08:00.0",):
        device = Path("/sys/bus/pci/devices") / address
        try:
            power = (device / "power_state").read_text(encoding="utf-8").strip()
            runtime = (device / "power/runtime_status").read_text(encoding="utf-8").strip()
        except OSError:
            continue
        lines.append(f"  {address}: power_state={power} runtime_status={runtime}")
    return tuple(lines) or ("  (no connected connector found)",)


def main(argv: Sequence[str] = ()) -> int:
    parser = argparse.ArgumentParser(
        prog="probe_display_release.py", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument("--card", default="/dev/dri/card1", help="eGPU card node")
    parser.add_argument("--render", default="/dev/dri/renderD129", help="eGPU render node")
    parser.add_argument("--internal", default="/dev/dri/card0", help="internal panel card node")
    parser.add_argument(
        "--release",
        action="store_true",
        help="take master and turn the CRTC off; without this nothing is opened"
        " for writing and no master is taken",
    )
    parser.add_argument(
        "--hold", type=float, default=3.0, help="seconds to hold the release"
    )
    arguments = parser.parse_args(argv)

    probe = DrmCrtcProbe()

    section("1. observe both cards, read-only")
    external = probe.observe(arguments.card)
    internal = probe.observe(arguments.internal)
    for label, state in (("external", external), (" internal", internal)):
        report(f"  {label} {state.node}: {state.code} committed={state.mode_committed}")
        for record in state.crtcs:
            if record.committed:
                report(
                    f"      crtc={record.crtc_id} fb={record.fb_id}"
                    f" {record.width}x{record.height}"
                )

    section("2. what the existing gate sees, from sysfs")
    for line in sysfs_view(Path(arguments.card).name):
        report(line)

    section("3. who holds the eGPU nodes")
    units, complete = holders(arguments.card, arguments.render)
    report(f"  holders: {units or '(none)'}")
    report(f"  scan complete: {complete}")
    if not complete and getattr(os, "geteuid", lambda: 0)() != 0:
        report("  (unprivileged: some processes could not be read; run with sudo)")

    section("4. decide")
    evidence = DisplayReleaseEvidence(
        external_committed=tuple(record.crtc_id for record in external.committed),
        external_complete=external.complete,
        internal_committed=internal.mode_committed,
        client_holders=units,
        client_scan_complete=complete,
    )
    decision = decide_display_release(evidence, approved=arguments.release)
    report(f"  {decision.state.value} / {decision.code}")
    if decision.crtcs:
        report(f"  would release crtcs: {decision.crtcs}")

    if not arguments.release:
        section("plan only")
        report("  no master was taken and no mode was changed.")
        report("  re-run with --release to perform it.")
        return 0
    if decision.state is DisplayReleaseState.NOT_NEEDED:
        report("\n  nothing to release.")
        return 0
    if not decision.permitted:
        report("\n  refusing to release.")
        return 1

    section("5. release, hold, restore")
    result, held = DrmDisplayRelease().release(arguments.card, decision.crtcs)
    report(f"  {result.outcome.value} / {result.code}")
    if held is None:
        return 1
    try:
        report(f"  still_released={held.still_released()}")
        after = probe.observe(arguments.card)
        report(f"  external committed while held: {after.mode_committed}")
        section("6. what the existing gate sees WHILE the release is held")
        for line in sysfs_view(Path(arguments.card).name):
            report(line)
        report("")
        report(f"  holding {arguments.hold}s")
        time.sleep(max(0.0, arguments.hold))
    finally:
        held.restore()
        report("  restored: descriptor closed, console mode returns")

    section("7. after restore")
    final = probe.observe(arguments.card)
    report(f"  external committed: {final.mode_committed}")
    for record in final.committed:
        report(f"      crtc={record.crtc_id} fb={record.fb_id} {record.width}x{record.height}")
    for line in sysfs_view(Path(arguments.card).name):
        report(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
