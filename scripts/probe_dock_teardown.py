"""Report what a full dock teardown would find. Changes nothing.

Read-only, and deliberately so: this is the evidence issue #147 asks for
before any decision about the cable, and gathering it must not be the thing
that alters the state being gathered. It removes nothing, writes to no sysfs
file, and deauthorizes nothing.

What it answers:

- which of the eGPU's PCI functions are still attached;
- whether the dock's USB controller is still enumerated, and what is plugged
  into it;
- whether anything on that branch is in use -- a mounted filesystem in any
  namespace, swap, or a stacked device -- which refuses absolutely, because a
  device removed with writes outstanding is somebody's files;
- whether the Thunderbolt router is authorized and whether this process could
  deauthorize it.

Run it twice: once with the eGPU attached and idle, and once immediately after
a live disconnect. The second reading is the one that matters, because it is
the state a player would be in when they reach for the cable.

    python scripts/probe_dock_teardown.py

The defaults describe the tested Ally X / GPD G1 pairing. Another dock needs
its own addresses, and the report records whichever were used so a captured
result says which hardware it describes:

    python scripts/probe_dock_teardown.py \
        --usb-controller 0000:aa:00.0 --tunnel-name "Some Other Dock" \
        --gpu-function 0000:bb:00.0 --gpu-function 0000:bb:00.1

Nothing here is clearance to unplug anything. Safety invariant 10 stands and
#147 is undecided; this produces the evidence that decision needs, and makes
no claim of its own.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from regear.adapters.steamos.dock_branch import DockBranchDiscovery  # noqa: E402
from regear.domain.dock_teardown import (  # noqa: E402
    TunnelEvidence,
    UsbBranchEvidence,
    decide_dock_teardown,
)


#: The tested Ally X / GPD G1 pairing. These are observations recorded from that
#: hardware rather than constants the code may assume elsewhere, which is why
#: they are defaults a caller can replace rather than fixed values. A probe that
#: only runs on one dock can only produce evidence about one dock, and the
#: decision in #147 is not about one dock.
DEFAULT_GPU_FUNCTIONS = ("0000:08:00.0", "0000:08:00.1")
DEFAULT_USB_CONTROLLER = "0000:09:00.0"
DEFAULT_TUNNEL_NAME = "Tapex Creek"
PCI_DEVICES = Path("/sys/bus/pci/devices")


def attached_gpu_functions(
    gpu_functions: tuple[str, ...],
) -> tuple[tuple[str, ...], bool]:
    """Which eGPU functions are still enumerated, and whether the look worked."""
    try:
        present = {entry.name for entry in PCI_DEVICES.iterdir()}
    except OSError:
        return (), False
    return tuple(bdf for bdf in gpu_functions if bdf in present), True


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        prog="probe_dock_teardown",
        description=(
            "Report what a full dock teardown would find. Changes nothing. "
            "Defaults describe the tested Ally X / GPD G1 pairing."
        ),
    )
    value.add_argument(
        "--gpu-function",
        action="append",
        metavar="BDF",
        help=(
            "PCI address of an eGPU function, repeatable. "
            f"Defaults to {' and '.join(DEFAULT_GPU_FUNCTIONS)}."
        ),
    )
    value.add_argument(
        "--usb-controller",
        default=DEFAULT_USB_CONTROLLER,
        metavar="BDF",
        help="PCI address of the dock's USB controller.",
    )
    value.add_argument(
        "--tunnel-name",
        default=DEFAULT_TUNNEL_NAME,
        metavar="NAME",
        help="device_name the dock's Thunderbolt router publishes.",
    )
    return value


def main(argv: Sequence[str] | None = None) -> int:
    options = parser().parse_args(argv)
    gpu_functions = tuple(options.gpu_function or DEFAULT_GPU_FUNCTIONS)
    discovery = DockBranchDiscovery()

    gpu_present, gpu_complete = attached_gpu_functions(gpu_functions)
    usb = discovery.observe_usb(options.usb_controller)
    storage = discovery.observe_storage(options.usb_controller)
    tunnel = discovery.observe_tunnel(options.tunnel_name)

    decision = decide_dock_teardown(
        usb=UsbBranchEvidence(
            controller_bdf=usb.controller_bdf,
            present=usb.present,
            scan_complete=usb.complete,
            mounted_storage=storage.mounts,
            storage_in_use=tuple(
                f"{use.device}: {use.detail}" for use in storage.other_uses
            ),
            storage_scan_complete=storage.complete,
            input_devices=tuple(
                device.label for device in usb.devices if "input" in device.kinds
            ),
            other_devices=tuple(
                device.label for device in usb.devices if "input" not in device.kinds
            ),
        ),
        tunnel=TunnelEvidence(
            sysfs_id=tunnel.sysfs_id,
            authorized=tunnel.authorized,
            capability=tunnel.capability,
            write_permission=tunnel.write_permission,
            scan_complete=tunnel.complete,
        ),
        gpu_functions_present=gpu_present,
        gpu_scan_complete=gpu_complete,
        # Never approved from a probe. Reporting the substantive blocker is the
        # whole job; producing a permitted decision is not. Passing no approval
        # is what expresses that: an otherwise-clear dock stops at
        # `approval_required` rather than reaching `permitted`.
        approval=None,
    )

    report = {
        # A captured report has to say which dock it describes. Evidence for
        # #147 that does not name its own hardware cannot be compared against
        # evidence from another dock, and these values are now a caller's
        # choice rather than a constant a reader could look up.
        "identity": {
            "gpu_functions": list(gpu_functions),
            "usb_controller": options.usb_controller,
            "tunnel_name": options.tunnel_name,
            "defaults_used": (
                gpu_functions == DEFAULT_GPU_FUNCTIONS
                and options.usb_controller == DEFAULT_USB_CONTROLLER
                and options.tunnel_name == DEFAULT_TUNNEL_NAME
            ),
        },
        "gpu": {
            "still_attached": list(gpu_present),
            "scan_complete": gpu_complete,
        },
        "usb_branch": {
            "controller": usb.controller_bdf,
            "present": usb.present,
            "scan_complete": usb.complete,
            "devices": [
                {
                    "id": device.sysfs_id,
                    "label": device.label,
                    "kinds": list(device.kinds),
                }
                for device in usb.devices
            ],
        },
        "storage": {
            "mounted": list(storage.mounts),
            "other_uses": [
                {"device": use.device, "kind": use.kind, "detail": use.detail}
                for use in storage.other_uses
            ],
            "scan_complete": storage.complete,
            # Which evidence was not read, in a stable order. One code told an
            # operator the scan did not finish; these say what did not finish,
            # and the remedies differ. Bare identifiers by construction: no
            # device name, mount point or pid can appear here.
            "gaps": [gap.value for gap in storage.gaps],
        },
        "tunnel": {
            "sysfs_id": tunnel.sysfs_id,
            "authorized": tunnel.authorized,
            "capability": tunnel.capability.value,
            "write_permission": tunnel.write_permission.value,
            # Derived, and reported alongside rather than instead of the two
            # axes: it is true only when support is established AND the file
            # is writable, so a reader who sees false can see which half.
            "deauthorizable": tunnel.deauthorizable,
            "scan_complete": tunnel.complete,
            # An ambiguous reading is incomplete, so the decision refuses
            # either way. Reporting only the incompleteness would tell an
            # operator the scan failed, when what actually happened is that
            # two routers answer to this name and no single one is the dock.
            # That is something they can act on; "scan incomplete" is not.
            "ambiguous_name": tunnel.ambiguous,
        },
        "decision": {
            "state": decision.state.value,
            "code": decision.code,
            "blocking_mounts": list(decision.blocking_mounts),
            "blocking_uses": list(decision.blocking_uses),
            "would_disconnect": list(decision.disconnecting),
        },
    }
    print(json.dumps(report, indent=2))

    print()
    print("=" * 68)
    if decision.blocking_mounts:
        print("BLOCKED: a filesystem on the dock is mounted.")
        for mount in decision.blocking_mounts:
            print(f"  {mount}")
        print("Unmount it yourself before any teardown. Re-Gear will not.")
    elif decision.blocking_uses:
        print("BLOCKED: a drive on the dock is in use without being mounted.")
        for use in decision.blocking_uses:
            print(f"  {use}")
    elif decision.code == "dock_teardown.approval_required":
        print("Every substantive fact holds. A teardown would be permitted.")
    else:
        print(f"Would refuse: {decision.code}")
    if decision.disconnecting:
        print()
        print("These would disconnect with the branch:")
        for device in decision.disconnecting:
            print(f"  {device}")
    print()
    print("This is not clearance to unplug anything. Invariant 10 stands.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
