"""Explicit, bounded virtual-target observation. Importing performs no I/O.

No production registration or command-line entry point. A separately approved
caller must supply fresh target provenance and the verified virtual key codes.
"""

from __future__ import annotations

import math
import os
import re
import stat
import struct
import sys
import time
from dataclasses import dataclass
from typing import Callable, Protocol


OPEN_FLAGS = (os.O_RDONLY | getattr(os, "O_NONBLOCK", 0x800)
              | getattr(os, "O_CLOEXEC", 0x80000) | getattr(os, "O_NOFOLLOW", 0x20000))


@dataclass(frozen=True)
class NodeIdentity:
    mode: int
    fs_device: int
    inode: int
    rdev: int


@dataclass(frozen=True)
class VerifiedTarget:
    path: str
    fs_device: int
    inode: int
    rdev: int
    verified_at: float
    virtual_confirmed: bool
    menu_code: int
    a_code: int
    word_bits: int
    byteorder: str


@dataclass(frozen=True)
class Limits:
    seconds: float = 45.0
    max_records: int = 2048
    max_facts: int = 64
    poll_seconds: float = 0.05


@dataclass(frozen=True)
class Fact:
    button: str
    kind: str
    offset_us: int
    duration_us: int | None = None


@dataclass(frozen=True)
class Observation:
    reason: str
    facts: tuple[Fact, ...]
    record_count: int
    elapsed_ms: int
    descriptor_closed: bool
    timing_valid: bool


class ObserverIO(Protocol):
    def monotonic(self) -> float: ...
    def lstat(self, path: str) -> NodeIdentity: ...
    def open(self, path: str, flags: int) -> int: ...
    def fstat(self, fd: int) -> NodeIdentity: ...
    def wait(self, fd: int, timeout: float) -> str: ...
    def read(self, fd: int, size: int) -> bytes: ...
    def close(self, fd: int) -> None: ...


class SystemIO:
    """Linux-only syscall adapter; construction/import does not open anything."""

    monotonic = staticmethod(time.monotonic)

    @staticmethod
    def _identity(value: os.stat_result) -> NodeIdentity:
        return NodeIdentity(value.st_mode, value.st_dev, value.st_ino, value.st_rdev)

    def lstat(self, path: str) -> NodeIdentity:
        if sys.platform != "linux":
            raise OSError("unsupported platform")
        return self._identity(os.lstat(path))

    def open(self, path: str, flags: int) -> int:
        if sys.platform != "linux" or flags != OPEN_FLAGS:
            raise OSError("unsupported open")
        return os.open(path, flags)

    def fstat(self, fd: int) -> NodeIdentity:
        return self._identity(os.fstat(fd))

    @staticmethod
    def wait(fd: int, timeout: float) -> str:
        import select
        poller = select.poll()
        poller.register(fd, select.POLLIN | select.POLLHUP | select.POLLERR | select.POLLNVAL)
        events = poller.poll(max(1, math.ceil(timeout * 1000)))
        if not events:
            return "timeout"
        flags = events[0][1]
        if flags & (select.POLLERR | select.POLLNVAL):
            return "error"
        if flags & select.POLLHUP:
            return "disconnected"
        return "ready" if flags & select.POLLIN else "error"

    read = staticmethod(os.read)
    close = staticmethod(os.close)


class _Stop(Exception):
    pass


def _integer(value: object, low: int, high: int) -> bool:
    return type(value) is int and low <= value <= high


def _number(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def observe(target: VerifiedTarget, *, io: ObserverIO | None = None,
            limits: Limits = Limits(), cancelled: Callable[[], bool] = lambda: False) -> Observation:
    """Observe only the supplied target. Never scan, reopen, recover or mutate it.

    The receipt's virtual identity/key mapping is caller-verified provenance,
    not discovered or certified by this function. Facts contain no path, device
    IDs, absolute kernel times, raw input bytes or exception details.
    """
    port = io if io is not None else SystemIO()
    facts: list[Fact] = []
    count = 0
    fd: int | None = None
    closed = True
    start = last_now = 0.0
    reason = "invalid_request"
    phase = "clock"
    deadline = 0.0
    first_stamp: int | None = None
    previous_stamp: int | None = None
    pressed: dict[str, int | None] = {"menu": None, "a": None}
    overlap_start: int | None = None

    def clock() -> float:
        nonlocal last_now
        now = port.monotonic()
        if not _number(now) or now < last_now:
            raise _Stop("clock_invalid")
        last_now = now
        return now

    def gate() -> None:
        if cancelled():
            raise _Stop("cancelled")
        if clock() >= deadline:
            raise _Stop("deadline")

    def identity(actual: NodeIdentity) -> bool:
        return (isinstance(actual, NodeIdentity) and stat.S_ISCHR(actual.mode)
                and (actual.fs_device, actual.inode, actual.rdev)
                == (target.fs_device, target.inode, target.rdev))

    def add(button: str, kind: str, offset: int, duration: int | None = None) -> None:
        if len(facts) >= limits.max_facts:
            raise _Stop("output_limit")
        facts.append(Fact(button, kind, offset, duration))

    try:
        now = port.monotonic()
        if not _number(now) or now < 0:
            raise _Stop("clock_invalid")
        start = last_now = now
        valid = (isinstance(target, VerifiedTarget) and isinstance(limits, Limits)
                 and isinstance(target.path, str)
                 and re.fullmatch(r"/dev/input/event(?:0|[1-9][0-9]{0,4})", target.path)
                 and all(_integer(v, 1, 2**64 - 1) for v in
                         (target.fs_device, target.inode, target.rdev))
                 and target.virtual_confirmed is True
                 and _number(target.verified_at) and 0 <= now - target.verified_at <= 2.0
                 and _integer(target.menu_code, 1, 0x2FF)
                 and _integer(target.a_code, 1, 0x2FF) and target.menu_code != target.a_code
                 and type(target.word_bits) is int and target.word_bits in (32, 64)
                 and target.byteorder in ("little", "big")
                 and _number(limits.seconds) and 0 < limits.seconds <= 45.0
                 and _number(limits.poll_seconds) and 0 < limits.poll_seconds <= 0.1
                 and _integer(limits.max_records, 1, 4096)
                 and _integer(limits.max_facts, 1, 128))
        if not valid:
            raise _Stop("invalid_request")
        if isinstance(port, SystemIO) and (sys.platform != "linux"
                or target.word_bits != struct.calcsize("@l") * 8
                or target.byteorder != sys.byteorder):
            raise _Stop("invalid_request")
        deadline = start + limits.seconds
        layout = struct.Struct(("<" if target.byteorder == "little" else ">")
                               + ("qqHHi" if target.word_bits == 64 else "iiHHi"))
        gate()
        phase = "identity"
        if not identity(port.lstat(target.path)):
            raise _Stop("identity_mismatch")
        gate()
        if last_now - target.verified_at > 2.0:
            raise _Stop("invalid_request")
        phase = "open"
        fd = port.open(target.path, OPEN_FLAGS)
        if type(fd) is not int or fd < 0:
            fd = None
            raise _Stop("open_error")
        closed = False
        phase = "identity"
        if not identity(port.fstat(fd)):
            raise _Stop("identity_mismatch")
        for _ in range(4096):
            gate()
            if count >= limits.max_records:
                raise _Stop("record_limit")
            if len(facts) >= limits.max_facts:
                raise _Stop("output_limit")
            phase = "poll"
            ready = port.wait(fd, min(limits.poll_seconds, deadline - last_now))
            gate()
            if ready == "timeout":
                continue
            if ready == "disconnected":
                raise _Stop("disconnected")
            if ready != "ready":
                raise _Stop("poll_error")
            phase = "identity"
            if not identity(port.fstat(fd)):
                raise _Stop("identity_mismatch")
            gate()
            phase = "read"
            size = layout.size * min(32, limits.max_records - count)
            data = port.read(fd, size)
            gate()
            if type(data) is not bytes or len(data) > size:
                raise _Stop("read_error")
            if not data:
                raise _Stop("disconnected")
            if len(data) % layout.size:
                raise _Stop("truncated_record")
            for sec, usec, kind, code, value in layout.iter_unpack(data):
                gate()
                if count >= limits.max_records:
                    raise _Stop("record_limit")
                count += 1
                if sec < 0 or not 0 <= usec < 1_000_000:
                    raise _Stop("event_clock_invalid")
                stamp = sec * 1_000_000 + usec
                if first_stamp is None:
                    first_stamp = stamp
                if ((previous_stamp is not None and stamp < previous_stamp)
                        or stamp - first_stamp > limits.seconds * 1_000_000):
                    raise _Stop("event_clock_invalid")
                previous_stamp = stamp
                if kind == 0 and code == 3:
                    raise _Stop("event_loss")
                if kind != 1 or code not in (target.menu_code, target.a_code):
                    continue
                if value not in (0, 1, 2):
                    raise _Stop("invalid_event")
                button = "menu" if code == target.menu_code else "a"
                offset = stamp - first_stamp
                began = pressed[button]
                if value == 1:
                    add(button, "press" if began is None else "duplicate_press", offset)
                    if began is None:
                        pressed[button] = stamp
                    if overlap_start is None and all(v is not None for v in pressed.values()):
                        overlap_start = stamp
                elif value == 2:
                    add(button, "repeat", offset)
                else:
                    add(button, "release", offset, stamp - began if began is not None else None)
                    if overlap_start is not None:
                        add("both", "overlap", offset, stamp - overlap_start)
                        overlap_start = None
                    pressed[button] = None
        raise _Stop("poll_limit")
    except _Stop as stop:
        reason = str(stop)
    except KeyboardInterrupt:
        reason = "cancelled"
    except Exception:
        reason = phase + "_error"
    finally:
        if fd is not None:
            try:
                port.close(fd)
                closed = True
            except BaseException:
                reason = "close_error"
                closed = False
    valid_timing = reason in ("deadline", "cancelled")
    return Observation(reason, tuple(facts), count, max(0, int((last_now - start) * 1000)),
                       closed, valid_timing)
