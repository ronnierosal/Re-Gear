"""Fixed Linux teardown primitives, not a production topology/claim executor.

The caller must supply independently established attachment topology, pinned
identities and a durable exclusive claim. The guard revalidates that claim and
all release/storage permissions. Local one-shot protection is not crash recovery.
Successful writes alone never establish physical unplug clearance.
"""
from dataclasses import dataclass
import os
from pathlib import Path
import re
import stat
from threading import Lock
from typing import Callable

SYSFS_DEVICES_ROOT = Path("/sys/devices")


@dataclass(frozen=True)
class NodeIdentity:
    device: int
    inode: int


@dataclass(frozen=True)
class SysfsTarget:
    # Canonical path components, excluding /sys/devices; no bus symlinks.
    parts: tuple[str, ...]
    # Root identity followed by each component's identity.
    identities: tuple[NodeIdentity, ...]


class WriterRefused(ValueError):
    pass


class WholeDockSysfsWriter:
    def __init__(self):
        self._lock = Lock()
        self._used: set[str] = set()
        self._unresolved = False

    def remove_usb(self, target: SysfsTarget, guard: Callable[[], bool]) -> None:
        self._write(target, guard, usb=True)

    def deauthorize(self, target: SysfsTarget, guard: Callable[[], bool]) -> None:
        self._write(target, guard, usb=False)

    @staticmethod
    def _identity(fd: int, expected: NodeIdentity) -> None:
        current = os.fstat(fd)
        if (current.st_dev, current.st_ino) != (expected.device, expected.inode):
            raise WriterRefused("dock_teardown.target_changed")
        if not stat.S_ISDIR(current.st_mode):
            raise WriterRefused("dock_teardown.target_not_directory")

    @staticmethod
    def _read(directory: int, name: str) -> str:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise WriterRefused("dock_teardown.attribute_invalid")
            return os.read(fd, 128).decode("ascii").strip()
        finally:
            os.close(fd)

    def _write(self, target: SysfsTarget, guard: Callable[[], bool], *, usb: bool) -> None:
        operation = "usb" if usb else "tunnel"
        if not self._lock.acquire(blocking=False):
            raise WriterRefused("dock_teardown.writer_busy")
        try:
            if self._unresolved:
                raise WriterRefused("dock_teardown.previous_write_unresolved")
            if operation in self._used:
                raise WriterRefused("dock_teardown.write_already_attempted")
            self._used.add(operation)
            self._unresolved = True
            if not hasattr(os, "O_NOFOLLOW") or os.open not in os.supports_dir_fd:
                raise WriterRefused("dock_teardown.platform_unsupported")
            if (type(target) is not SysfsTarget or type(target.parts) is not tuple
                    or not target.parts or type(target.identities) is not tuple
                    or len(target.identities) != len(target.parts) + 1
                    or any(type(p) is not str or not re.fullmatch(r"[A-Za-z0-9_.:-]+", p)
                           or p in (".", "..") for p in target.parts)
                    or any(type(i) is not NodeIdentity for i in target.identities)):
                raise WriterRefused("dock_teardown.target_invalid")
            leaf = target.parts[-1]
            if usb:
                valid = re.fullmatch(r"[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]", leaf)
            else:
                valid = re.fullmatch(r"\d+-[1-9a-f][0-9a-f]*", leaf)
                valid = valid and any(re.fullmatch(r"domain\d+", p) for p in target.parts[:-1])
            if not valid:
                raise WriterRefused("dock_teardown.target_kind_invalid")
            descriptors: list[int] = []
            attribute = None
            try:
                flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                descriptors.append(os.open(SYSFS_DEVICES_ROOT, flags))
                self._identity(descriptors[-1], target.identities[0])
                for part, expected in zip(target.parts, target.identities[1:]):
                    descriptors.append(os.open(part, flags, dir_fd=descriptors[-1]))
                    self._identity(descriptors[-1], expected)
                directory = descriptors[-1]
                if usb and self._read(directory, "class") != "0x0c0330":
                    raise WriterRefused("dock_teardown.not_usb_controller")
                if not usb and self._read(directory, "authorized") != "1":
                    raise WriterRefused("dock_teardown.router_not_authorized")
                if not usb:
                    domains = [index for index, part in enumerate(target.parts)
                               if re.fullmatch(r"domain\d+", part)]
                    if len(domains) != 1 or self._read(
                            descriptors[domains[0] + 1], "deauthorization") != "1":
                        raise WriterRefused("dock_teardown.deauthorization_unsupported")
                attribute = os.open("remove" if usb else "authorized",
                                    os.O_WRONLY | os.O_NOFOLLOW, dir_fd=directory)
                if not stat.S_ISREG(os.fstat(attribute).st_mode):
                    raise WriterRefused("dock_teardown.attribute_invalid")
                if guard() is not True:
                    raise WriterRefused("dock_teardown.guard_refused")
                for fd, expected in zip(descriptors, target.identities):
                    self._identity(fd, expected)
                if os.write(attribute, b"1" if usb else b"0") != 1:
                    raise OSError("dock_teardown.short_write")
            finally:
                cleanup_error = None
                closing = ([attribute] if attribute is not None else []) + list(reversed(descriptors))
                for fd in closing:
                    try:
                        os.close(fd)
                    except OSError as error:
                        cleanup_error = error
                if cleanup_error is not None:
                    raise cleanup_error
            self._unresolved = False
        finally:
            self._lock.release()
