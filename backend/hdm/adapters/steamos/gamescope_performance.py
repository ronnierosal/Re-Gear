"""Bounded one-shot Gamescope v6 performance query; no compositor mutations.

Original minimal Wayland wire client for the private gamescope_control protocol.
Only registry, sync, bind and request_app_performance_stats requests are emitted.
The caller must resolve the exact workload and compositor before each query.
One presentation delta is not an average FPS or GPU utilization measurement.
"""

from __future__ import annotations

import array
import os
import socket
import stat
import struct
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True, slots=True)
class PerformanceTarget:
    socket_path: Path
    uid: int
    compositor_pid: int
    app_id: int
    context_key: str
    process_start_ticks: int

    def __post_init__(self) -> None:
        if not self.socket_path.is_absolute() or not self.context_key or len(self.context_key) > 256:
            raise ValueError("Performance target identity is invalid")
        if any(type(value) is not int or not 0 < value <= 0xFFFFFFFF for value in (self.uid, self.compositor_pid, self.app_id)):
            raise ValueError("Performance target identifiers are invalid")
        if type(self.process_start_ticks) is not int or self.process_start_ticks <= 0:
            raise ValueError("Compositor process generation is invalid")


@dataclass(frozen=True, slots=True)
class PerformanceReading:
    code: str
    context_key: str = ""
    received_at_ms: int | None = None
    frame_time_ns: int | None = None

    @property
    def instantaneous_fps(self) -> float | None:
        return 1_000_000_000 / self.frame_time_ns if self.frame_time_ns else None


def _uint(*values: int) -> bytes:
    return struct.pack("=" + "I" * len(values), *values)


def _string(value: str) -> bytes:
    data = value.encode("ascii") + b"\0"
    return _uint(len(data)) + data + b"\0" * (-len(data) % 4)


def _connect(target: PerformanceTarget, timeout: float) -> socket.socket:
    # A Linux peer credential match ties the endpoint to the discovered process,
    # rather than trusting the socket filename or the current shell environment.
    if not hasattr(socket, "SO_PEERCRED"):
        raise OSError("Peer credentials unavailable")
    metadata = target.socket_path.lstat()
    if not stat.S_ISSOCK(metadata.st_mode) or metadata.st_uid != target.uid:
        raise OSError("Socket identity mismatch")
    stream = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        stream.settimeout(timeout)
        stream.connect(str(target.socket_path))
        pid, uid, _ = struct.unpack("=iii", stream.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        if pid != target.compositor_pid or uid != target.uid:
            raise OSError("Peer identity mismatch")
        return stream
    except Exception:
        stream.close()
        raise


def _same_process(target: PerformanceTarget) -> bool:
    try:
        with (Path("/proc") / str(target.compositor_pid) / "stat").open("rb") as stream:
            data = stream.read(4097)
        if len(data) > 4096:
            return False
        fields = data[data.rindex(b")") + 2:].split()
        return fields[0] in (b"R", b"S", b"D", b"T", b"t", b"W", b"K", b"P", b"I") and int(fields[19]) == target.process_start_ticks
    except (OSError, ValueError, IndexError):
        return False


class _Wire:
    def __init__(self, stream: socket.socket, clock: Callable[[], float], deadline: float):
        self.stream, self.clock, self.deadline = stream, clock, deadline
        self.received = 0
        self.messages = 0

    def _timeout(self):
        remaining = self.deadline - self.clock()
        if remaining <= 0:
            raise TimeoutError
        self.stream.settimeout(remaining)

    def send(self, obj: int, opcode: int, payload: bytes):
        self._timeout()
        self.stream.sendall(_uint(obj, ((len(payload) + 8) << 16) | opcode) + payload)

    def _read(self, size: int) -> bytes:
        data = bytearray()
        while len(data) < size:
            self._timeout()
            part, ancillary, flags, _ = self.stream.recvmsg(size - len(data), socket.CMSG_SPACE(64))
            for level, kind, value in ancillary:
                if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                    descriptors = array.array("i")
                    descriptors.frombytes(value[:len(value) - len(value) % descriptors.itemsize])
                    for descriptor in descriptors:
                        os.close(descriptor)
            if ancillary or flags & (socket.MSG_CTRUNC | socket.MSG_TRUNC):
                raise ValueError("Unexpected ancillary data")
            if not part:
                raise OSError("Disconnected")
            self.received += len(part)
            if self.received > 65_536:
                raise ValueError("Response budget exceeded")
            data.extend(part)
        return bytes(data)

    def event(self) -> tuple[int, int, bytes]:
        self.messages += 1
        if self.messages > 512:
            raise ValueError("Event budget exceeded")
        obj, word = struct.unpack("=II", self._read(8))
        size, opcode = word >> 16, word & 0xFFFF
        if size < 8 or size > 16_384 or size % 4:
            raise ValueError("Invalid event length")
        payload = self._read(size - 8)
        if obj == 1 and opcode == 0:
            raise ValueError("Compositor protocol error")
        return obj, opcode, payload


def _global(payload: bytes) -> tuple[int, str, int]:
    if len(payload) < 16:
        raise ValueError("Invalid registry event")
    name, length = struct.unpack("=II", payload[:8])
    end = 8 + ((length + 3) // 4) * 4
    if not 1 <= length <= 256 or end + 4 != len(payload):
        raise ValueError("Invalid interface string")
    value = payload[8:8 + length]
    if value[-1:] != b"\0" or b"\0" in value[:-1]:
        raise ValueError("Invalid interface name")
    return name, value[:-1].decode("ascii"), struct.unpack("=I", payload[end:])[0]


class GamescopePerformanceReader:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic,
                 connect: Callable[[PerformanceTarget, float], socket.socket] = _connect,
                 same_process: Callable[[PerformanceTarget], bool] = _same_process,
                 timeout_seconds: float = 0.5):
        if type(timeout_seconds) not in (int, float) or not 0 < timeout_seconds <= 2:
            raise ValueError("Performance query deadline is invalid")
        self._clock, self._connect, self._timeout = clock, connect, timeout_seconds
        self._same_process = same_process

    def observe(self, target: PerformanceTarget) -> PerformanceReading:
        stream = None
        try:
            deadline = self._clock() + self._timeout
            if not self._same_process(target):
                return PerformanceReading("performance.context_changed")
            remaining = deadline - self._clock()
            if remaining <= 0:
                raise TimeoutError
            stream = self._connect(target, remaining)
            wire = _Wire(stream, self._clock, deadline)
            wire.send(1, 1, _uint(2))  # wl_display.get_registry
            wire.send(1, 0, _uint(3))  # wl_display.sync
            candidates = {}
            while True:
                obj, opcode, data = wire.event()
                if obj == 3 and opcode == 0 and len(data) == 4:
                    break
                if obj == 2 and opcode == 0:
                    name, interface, version = _global(data)
                    if interface == "gamescope_control":
                        candidates[name] = version
                elif obj == 2 and opcode == 1 and len(data) == 4:
                    candidates.pop(struct.unpack("=I", data)[0], None)
            if len(candidates) != 1 or next(iter(candidates.values())) < 6:
                return PerformanceReading("performance.protocol_unavailable")
            name = next(iter(candidates))
            wire.send(2, 0, _uint(name) + _string("gamescope_control") + _uint(6, 4))
            wire.send(1, 0, _uint(5))
            feature = False
            while True:
                obj, opcode, data = wire.event()
                if obj == 5 and opcode == 0 and len(data) == 4:
                    break
                if obj == 4 and opcode == 0 and len(data) == 12:
                    kind, version, flags = struct.unpack("=III", data)
                    if kind == 7:
                        feature = version == 1 and flags == 0
                if obj == 2 and opcode == 1 and data == _uint(name):
                    return PerformanceReading("performance.protocol_unavailable")
            if not feature:
                return PerformanceReading("performance.feature_unavailable")
            wire.send(4, 6, _uint(target.app_id))
            while True:
                obj, opcode, data = wire.event()
                if obj == 2 and opcode == 1 and data == _uint(name):
                    return PerformanceReading("performance.protocol_unavailable")
                if obj == 4 and opcode == 3:
                    received = self._clock()
                    if len(data) != 12:
                        raise ValueError("Invalid performance response")
                    app_id, low, high = struct.unpack("=III", data)
                    delta = (high << 32) | low
                    if app_id != target.app_id or delta == 0:
                        raise ValueError("Mismatched performance response")
                    if not self._same_process(target):
                        return PerformanceReading("performance.context_changed")
                    if self._clock() >= deadline:
                        raise TimeoutError
                    return PerformanceReading("performance.observed", target.context_key,
                                              int(received * 1000), delta)
        except TimeoutError:
            return PerformanceReading("performance.timeout")
        except (OSError, ValueError, struct.error):
            return PerformanceReading("performance.unavailable")
        finally:
            if stream is not None:
                stream.close()
