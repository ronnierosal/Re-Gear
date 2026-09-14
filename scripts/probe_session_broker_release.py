"""Read-only preparation for a session broker experiment; execution is disabled.

No result authorizes a session stop, device removal, or physical unplug.
Raw session, process, attachment and bus identities stay inside this process.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))


def bounded_text(path: Path, limit: int = 16384) -> str:
    with path.open(encoding="utf-8") as stream:
        value = stream.read(limit + 1)
    if len(value) > limit:
        raise ValueError("oversized evidence")
    return value


def controller_identity(session_root=Path("/run/systemd/sessions"),
                        proc_root=Path("/proc"), run=subprocess.run):
    """Resolve login1's controller bus owner to the exact Gamescope service PID."""
    candidates = []
    entries = list(session_root.iterdir())
    if len(entries) > 128:
        raise ValueError("session inventory oversized")
    for entry in entries:
        if not entry.name.isalnum():
            continue
        fields = dict(line.split("=", 1) for line in bounded_text(entry).splitlines()
                      if "=" in line and not line.startswith("#"))
        controller = fields.get("CONTROLLER", "")
        if not re.fullmatch(r":[0-9]+\.[0-9]+", controller):
            continue
        reply = run(["busctl", "--system", "call", "org.freedesktop.DBus",
                     "/org/freedesktop/DBus", "org.freedesktop.DBus",
                     "GetConnectionUnixProcessID", "s", controller],
                    capture_output=True, text=True, timeout=5, check=True).stdout.strip()
        match = re.fullmatch(r"u ([1-9][0-9]{0,9})", reply)
        if not match:
            raise ValueError("controller unresolved")
        pid = match[1]
        group = bounded_text(proc_root / pid / "cgroup")
        unified = [line[3:] for line in group.splitlines() if line.startswith("0::")]
        if len(unified) == 1 and unified[0].endswith("/gamescope-session.service"):
            candidates.append((entry.name, controller, pid, unified[0]))
    if len(candidates) != 1:
        raise ValueError("controller ambiguous")
    return candidates[0]


def observe():
    from regear.adapters.steamos.drm import DrmDiscovery
    from regear.adapters.steamos.egpu_holders import node_paths, scan_holders
    from regear.adapters.steamos.whole_dock_topology import resolve_whole_dock
    from regear.domain.filter_arm_sequence import APPROVED_HOLDER_UNITS

    cards = [card for card in DrmDiscovery().scan() if card.boot_vga is False]
    if len(cards) != 1:
        raise ValueError("attachment ambiguous")
    binding = resolve_whole_dock(cards[0].pci_bdf)
    controller = controller_identity()
    nodes, complete = node_paths(binding.gpu_bdf, binding.audio_bdf)
    scan = scan_holders(nodes, nodes_incomplete=not complete)
    categories = set()
    for unit in scan.units:
        categories.add("session_controller" if unit == "gamescope-session.service"
                       else "system_broker" if unit == "systemd-logind.service"
                       else "system_manager" if unit == "init.scope"
                       else "approved_session_or_audio" if unit in APPROVED_HOLDER_UNITS
                       else "other_holder")
    # Re-resolve identities after collection; no stable binding is inferred
    # merely from the same visible GPU address.
    stable = (controller == controller_identity()
              and binding == resolve_whole_dock(cards[0].pci_bdf))
    return {"stable": stable, "complete": scan.complete,
            "holder_categories": sorted(categories)}


def probe(*, execute=False, euid=None, observer=observe):
    result = {"schema_version": 1, "code": "broker_probe.evidence_unavailable",
              "execution_enabled": False, "safe_to_unplug": False,
              "holder_categories": [], "scan_complete": False,
              "missing_execution_guards": ["independent_restore_watchdog",
                  "exclusive_mutation_ownership", "retained_claim_validation"]}
    if execute:
        return {**result, "code": "broker_probe.execution_not_implemented"}
    if (os.geteuid() if euid is None and hasattr(os, "geteuid") else euid) != 0:
        return {**result, "code": "broker_probe.root_required"}
    try:
        evidence = observer()
        allowed = {"session_controller", "system_broker", "system_manager",
                   "approved_session_or_audio", "other_holder"}
        categories = evidence["holder_categories"]
        if (type(categories) is not list or len(categories) > len(allowed)
                or any(type(item) is not str or item not in allowed for item in categories)):
            return result
        if evidence["stable"] is not True:
            return {**result, "code": "broker_probe.identity_changed"}
        return {**result, "code": "broker_probe.observed" if evidence["complete"] is True
                else "broker_probe.scan_incomplete", "scan_complete": evidence["complete"] is True,
                "holder_categories": sorted(set(categories))}
    except Exception:
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Refused: executor is not implemented")
    result = probe(execute=parser.parse_args().execute)
    print(json.dumps(result, separators=(",", ":")))
    return 0 if result["code"] == "broker_probe.observed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
