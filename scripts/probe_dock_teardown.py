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

Nothing here is clearance to unplug anything. Safety invariant 10 stands and
#147 is undecided; this produces the evidence that decision needs, and makes
no claim of its own.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from hdm.adapters.steamos.dock_branch import DockBranchDiscovery  # noqa: E402
from hdm.domain.dock_teardown import (  # noqa: E402
    TunnelEvidence,
    UsbBranchEvidence,
    decide_dock_teardown,
)


#: The tested Ally X / GPD G1 pairing. Both are observations recorded from that
#: hardware rather than constants the code may assume elsewhere.
GPU_FUNCTIONS = ("0000:08:00.0", "0000:08:00.1")
USB_CONTROLLER = "0000:09:00.0"
TUNNEL_NAME = "Tapex Creek"
PCI_DEVICES = Path("/sys/bus/pci/devices")


def attached_gpu_functions() -> tuple[tuple[str, ...], bool]:
    """Which eGPU functions are still enumerated, and whether the look worked."""
    try:
        present = {entry.name for entry in PCI_DEVICES.iterdir()}
    except OSError:
        return (), False
    return tuple(bdf for bdf in GPU_FUNCTIONS if bdf in present), True


def main() -> int:
    discovery = DockBranchDiscovery()

    gpu_present, gpu_complete = attached_gpu_functions()
    usb = discovery.observe_usb(USB_CONTROLLER)
    storage = discovery.observe_storage(USB_CONTROLLER)
    tunnel = discovery.observe_tunnel(TUNNEL_NAME)

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
            deauthorizable=tunnel.deauthorizable,
            scan_complete=tunnel.complete,
        ),
        gpu_functions_present=gpu_present,
        gpu_scan_complete=gpu_complete,
        # Never approved from a probe. Reporting the substantive blocker is the
        # whole job; producing a permitted decision is not.
        approved=False,
    )

    report = {
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
        },
        "tunnel": {
            "sysfs_id": tunnel.sysfs_id,
            "authorized": tunnel.authorized,
            "deauthorizable": tunnel.deauthorizable,
            "scan_complete": tunnel.complete,
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
