"""Experimental Linux Raikiri II diagnostic. Never imported by the plugin.

No dependencies beyond Python's standard library. Default is offline help;
capture is passive unless --enable-events is explicitly supplied. See
docs/RAIKIRI_CONTROLLER_SUPPORT.md for source provenance and supervised gates.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import select
import struct
import sys
import time


VID, PID = 0x0B05, 0x1C92
ENABLE = bytes.fromhex("b0 51 36 01 00 01") + bytes(58)
MAX_REPORTS = 4096


def descriptor_supported(data: bytes) -> bool:
    """Require exact vendor report sizes/usages; reject malformed HID items.

    Counts exclude the report ID. Handles short HID items and global stacks.
    Unknown layouts never authorize opening with write access.
    """
    fields = {}
    globals_ = dict(page=0, size=0, count=0, report=0)
    stack, collections, usage = [], [], None
    offset = 0
    try:
        while offset < len(data):
            prefix = data[offset]
            offset += 1
            if prefix == 0xFE:
                return False  # Long items are outside this reviewed parser.
            size = (0, 1, 2, 4)[prefix & 3]
            if offset + size > len(data):
                return False
            value = int.from_bytes(data[offset:offset + size], "little")
            offset += size
            kind, tag = (prefix >> 2) & 3, prefix >> 4
            if kind == 1:
                name = {0: "page", 7: "size", 8: "report", 9: "count"}.get(tag)
                if name:
                    globals_[name] = value
                elif tag == 10:
                    stack.append(globals_.copy())
                elif tag == 11:
                    globals_ = stack.pop()
            elif kind == 2 and tag == 0:
                usage = (value >> 16, value & 0xFFFF) if size == 4 else (globals_["page"], value)
            elif kind == 0:
                if tag == 10:
                    collections.append(usage if value == 1 else (collections[-1] if collections else None))
                elif tag == 12:
                    collections.pop()
                elif tag in (8, 9, 11):
                    if not collections or globals_["size"] > 64 or globals_["count"] > 4096:
                        return False
                    key = (collections[-1], globals_["report"], tag)
                    fields[key] = fields.get(key, 0) + globals_["size"] * globals_["count"]
                usage = None
    except IndexError:
        return False
    required = {((0xFF03, 1), 0xB0, 8): 504,
                ((0xFF03, 1), 0xB0, 9): 504,
                ((0xFFC3, 1), 0xB3, 8): 504}
    # Duplicate report IDs in other collections make routing ambiguous.
    relevant = {k: v for k, v in fields.items() if k[1] in (0xB0, 0xB3)}
    return not stack and not collections and relevant == required


def decode_report(data: bytes) -> dict:
    """Source-derived hypotheses only; never a verified menu input."""
    if len(data) != 64:
        return {"kind": "unknown", "reason": "report_length"}
    if data[:4] == bytes.fromhex("b0 51 36 01"):
        return {"kind": "ack"}
    if data[:3] == bytes.fromhex("b0 ff aa"):
        return {"kind": "rejected"}
    if data[0] != 0xB3:
        return {"kind": "unknown", "reason": "report_id_or_response"}
    bank = data[3]
    positions = {0: ((5, "rear_1"), (6, "rear_2"), (7, "rear_3"), (8, "rear_4")),
                 2: ((5, "command_candidate"), (6, "library_candidate"))}.get(bank)
    if positions is None or any(data[index] not in (0, 1) for index, _ in positions):
        return {"kind": "unknown", "reason": "bank_or_button_value"}
    return {"kind": "candidate", "bank": bank, "verified": False,
            "pressed": [name for index, name in positions if data[index]]}


class LinuxHidraw:
    def __init__(self, path: str, writable: bool):
        if sys.platform != "linux":
            raise ValueError("Live capture requires Linux; replay works on Windows.")
        import fcntl
        self.fd = os.open(path, (os.O_RDWR if writable else os.O_RDONLY) | os.O_NONBLOCK)
        try:
            # Validate the opened handle, not a potentially stale sysfs path.
            info = bytearray(8)
            fcntl.ioctl(self.fd, 0x80084803, info, True)  # HIDIOCGRAWINFO
            bus, vendor, product = struct.unpack("IHH", info)
            length = bytearray(4)
            fcntl.ioctl(self.fd, 0x80044801, length, True)  # HIDIOCGRDESCSIZE
            count = struct.unpack("I", length)[0]
            if not 0 < count <= 4096:
                raise ValueError("Unsupported descriptor length")
            descriptor = bytearray(struct.pack("I", count) + bytes(4096))
            fcntl.ioctl(self.fd, 0x90044802, descriptor, True)  # HIDIOCGRDESC
            if (bus, vendor, product) != (3, VID, PID) or not descriptor_supported(bytes(descriptor[4:4 + count])):
                raise ValueError("Opened device identity or descriptor is unsupported")
        except BaseException:
            os.close(self.fd)
            raise

    def read(self, timeout: float) -> bytes:
        ready, _, _ = select.select([self.fd], [], [], timeout)
        if not ready:
            return b""
        data = os.read(self.fd, 4096)
        if not data:
            raise OSError("Device disconnected")
        return data

    def write(self, data: bytes) -> int:
        return os.write(self.fd, data)

    def close(self):
        os.close(self.fd)


def capture(device, emit, seconds: float, enable: bool, clock=time.monotonic):
    """One handle routes both B0 and B3. No retries or implicit activation."""
    if not 1 <= seconds <= 120:
        raise ValueError("Capture duration must be 1..120 seconds")
    started = clock()
    count = 0
    activation = "passive"
    ack_deadline = None

    def record(data, phase):
        nonlocal count, activation
        count += 1
        if data[0] not in (0xB0, 0xB3):
            return  # Do not retain unrelated vendor interfaces/reports.
        decoded = decode_report(data)
        if phase == "capture" and activation == "pending" and decoded["kind"] in ("ack", "rejected"):
            activation = decoded["kind"]
        emit({"type": "report", "elapsed_ms": round((clock() - started) * 1000),
              "phase": phase, "hex": data.hex(), "decoded": decoded})

    # Drain queued packets before a write. A delayed response from another
    # writer remains uncorrelated: ACK is observation, not transaction proof.
    # Continuous traffic causes a bounded stop, never an unbounded drain.
    for _ in range(128):
        data = device.read(0)
        if not data:
            break
        record(data, "baseline")
    else:
        raise ValueError("Baseline queue did not drain; no activation attempted")
    if enable:
        if device.write(ENABLE) != len(ENABLE):
            raise OSError("Short activation write; no retry attempted")
        activation = "pending"
        ack_deadline = clock() + 3
        emit({"type": "activation", "status": "sent_once", "length": len(ENABLE)})
    emit({"type": "ready", "seconds": seconds, "instruction": "Begin labeled button test now"})
    deadline = clock() + seconds
    while clock() < deadline and count < MAX_REPORTS:
        if activation == "pending" and clock() >= ack_deadline:
            activation = "timeout"
            emit({"type": "activation", "status": "timeout"})
            break
        limit = min(deadline, ack_deadline) if activation == "pending" else deadline
        wait = min(0.05, max(0, limit - clock()))
        data = device.read(wait)
        if activation == "pending" and clock() >= ack_deadline:
            activation = "timeout"
            if data:
                record(data, "late_response")
            emit({"type": "activation", "status": "timeout"})
            break
        if data:
            record(data, "capture")
        if activation == "rejected":
            break
    if activation == "pending":
        activation = "unconfirmed"
    result = {"type": "summary", "activation": activation, "reports": count,
              "limit_reached": count >= MAX_REPORTS, "hardware_verified": False}
    emit(result)
    return result


def discover() -> list[str]:
    found = []
    for entry in sorted(Path("/sys/class/hidraw").glob("hidraw*")):
        try:
            values = dict(line.split("=", 1) for line in (entry / "device/uevent").read_text().splitlines() if "=" in line)
            identity = tuple(int(part, 16) for part in values.get("HID_ID", "").split(":"))
            if identity == (3, VID, PID) and descriptor_supported((entry / "device/report_descriptor").read_bytes()):
                found.append("/dev/" + entry.name)
        except (OSError, ValueError):
            continue
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("list", help="Read-only enumeration of supported Linux endpoints")
    replay = sub.add_parser("replay", help="Decode local JSONL capture without hardware")
    replay.add_argument("input", type=Path)
    live = sub.add_parser("capture", help="Supervised Linux-only capture; passive by default")
    live.add_argument("--output", type=Path, required=True)
    live.add_argument("--seconds", type=int, choices=range(1, 121), default=20, metavar="1..120")
    live.add_argument("--label", choices=("baseline", "rear", "extra-left", "extra-right", "l3", "r3", "mixed"), required=True)
    live.add_argument("--enable-events", action="store_true", help="Explicitly permit one experimental SetKeyEvent write")
    args = parser.parse_args(argv)
    if args.mode == "replay":
        with args.input.open(encoding="utf-8") as source:
            for index in range(MAX_REPORTS + 141):
                line = source.readline(16385)
                if not line:
                    break
                if index >= MAX_REPORTS + 140 or len(line) > 16384:
                    raise ValueError("Replay exceeds bounded capture format")
                row = json.loads(line)
                if row.get("type") == "report":
                    print(json.dumps({"elapsed_ms": row.get("elapsed_ms"), "phase": row.get("phase"),
                                      "decoded": decode_report(bytes.fromhex(row["hex"]))}))
        return 0
    if sys.platform != "linux":
        raise ValueError("Live enumeration and capture require Linux")
    paths = discover()
    if args.mode == "list":
        print(json.dumps({"supported_endpoints": len(paths), "device": "0b05:1c92"}))
        return 0
    if len(paths) != 1:
        raise ValueError("Require exactly one descriptor-matched PC-mode dongle endpoint")
    # Exclusive creation avoids clobbering prior evidence; private local capture.
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as log:
        def emit(row):
            line = json.dumps(row, sort_keys=True)
            log.write(line + "\n")
            log.flush()
            print(line, flush=True)
        emit({"type": "metadata", "schema": 1, "device": "0b05:1c92", "label": args.label,
              "enable_requested": args.enable_events, "firmware": "not_observed"})
        device = None
        try:
            device = LinuxHidraw(paths[0], args.enable_events)
            result = capture(device, emit, args.seconds, args.enable_events)
            return 0 if result["activation"] in ("passive", "ack") else 2
        except (OSError, ValueError, KeyboardInterrupt) as error:
            emit({"type": "stopped", "reason": type(error).__name__, "hardware_verified": False})
            raise
        finally:
            if device is not None:
                device.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f"Probe stopped: {exc}", file=sys.stderr)
        raise SystemExit(2)
