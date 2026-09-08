"""Bounded passive G1 PCIe counters and runtime-PM timeline, JSONL to stdout.

No config-space reads, subprocesses, driver operations or sysfs writes.
Run before a supervised attach to distinguish earlier errors from new ones.
This developer tool is not a safe-removal readiness decision.
"""
import argparse
import json
from pathlib import Path
import time


def read(path):
    try:
        with path.open(encoding="ascii") as stream:
            return stream.read(4097).strip()
    except (OSError, UnicodeError):
        return None


def identity(node):
    return read(node / "vendor"), read(node / "device")


def counters(path):
    value = read(path)
    if value is None or len(value) > 4096:
        return None
    result = {}
    for line in value.splitlines():
        fields = line.split()
        if len(fields) != 2 or not fields[1].isascii() or not fields[1].isdigit():
            return None
        count = int(fields[1])
        if count > 2**64 - 1 or fields[0] in result:
            return None
        result[fields[0]] = count
    return result or None


def collect(registry=Path("/sys/bus/pci/devices")):
    try:
        nodes = list(registry.iterdir())
    except OSError:
        return {"status": "pci_unavailable"}
    if len(nodes) > 512:
        return {"status": "inventory_limit"}
    gpus = [node for node in nodes if identity(node) == ("0x1002", "0x7480")]
    if len(gpus) != 1:
        return {"status": "g1_absent" if not gpus else "g1_ambiguous"}
    gpu = gpus[0]
    ancestors = [p for p in gpu.resolve().parents if identity(p) == ("0x8086", "0x15ef")]
    if not ancestors:
        return {"status": "transport_unverified"}
    transport = ancestors[-1]
    branch = [p for p in nodes if p.resolve().is_relative_to(transport)]
    controllers = [p for p in branch if identity(p) == ("0x8086", "0x15f0")]
    if len(controllers) != 1:
        return {"status": "usb_controller_unverified"}
    usb = controllers[0]
    targets = {"gpu": gpu, "usb_controller": usb, "usb_bridge": usb.resolve().parent}
    rows = {}
    for role, node in targets.items():
        rows[role] = {
            "node": node.name,
            "present": node.exists(),
            "power_control": read(node / "power/control"),
            "runtime_status": read(node / "power/runtime_status"),
            "correctable": counters(node / "aer_dev_correctable"),
            "nonfatal": counters(node / "aer_dev_nonfatal"),
            "fatal": counters(node / "aer_dev_fatal"),
        }
    # Hotplug may race a read. Missing evidence remains null, never healthy zero.
    return {"status": "observed", "devices": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=60)
    parser.add_argument("--interval", type=float, default=0.5)
    args = parser.parse_args()
    if not 1 <= args.samples <= 600 or not 0.5 <= args.interval <= 5:
        parser.error("samples must be 1..600 and interval 0.5..5 seconds")
    start = time.monotonic()
    previous = None
    for index in range(args.samples):
        state = collect()
        if state != previous or index == args.samples - 1:
            print(json.dumps({"sample": index, "elapsed_ms": int((time.monotonic()-start)*1000),
                              "unix_time": time.time(), "read_only": True, **state}), flush=True)
        previous = state
        if index < args.samples - 1:
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
