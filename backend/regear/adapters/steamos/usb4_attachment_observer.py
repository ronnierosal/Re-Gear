"""Bounded passive USB4 router evidence; private identifiers never leave delivery."""
from __future__ import annotations
import os
import re
import stat
import time
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True, slots=True)
class Usb4AttachmentObservation:
    state: str
    identity: tuple | None = None

class Usb4AttachmentObserver:
    ROUTER = re.compile(r'([0-9]{1,4})-([0-9a-f]{1,16})\Z')
    OTHER = re.compile(r'(?:domain[0-9]{1,4}|[0-9]{1,4}-[0-9a-f]{1,16}:[0-9]{1,4}\.[0-9]{1,4})\Z')
    UUID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z')
    def __init__(self, root=Path('/sys/bus/thunderbolt/devices'), *, devices_root=Path('/sys/devices')):
        self.root = Path(root)
        self.devices_root = Path(devices_root)

    @staticmethod
    def _read(fd, name):
        attr = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        try:
            if not stat.S_ISREG(os.fstat(attr).st_mode):
                raise ValueError('invalid attribute')
            raw = os.read(attr, 129)
            if len(raw) > 128:
                raise ValueError('oversized attribute')
            return raw.decode('ascii').strip()
        finally:
            os.close(attr)

    def _scan(self, deadline):
        entries = []
        with os.scandir(self.root) as listing:
            for entry in listing:
                if len(entries) >= 64 or time.monotonic() >= deadline:
                    raise ValueError('bounded scan')
                entries.append(entry.name)
        records = []
        allowed = self.devices_root.resolve(strict=True)
        for name in sorted(entries):
            match = self.ROUTER.fullmatch(name)
            if not match:
                if not self.OTHER.fullmatch(name):
                    raise ValueError('unknown topology')
                continue
            if int(match[2], 16) == 0:
                continue
            if time.monotonic() >= deadline:
                raise ValueError('expired scan')
            link = self.root / name
            target = link.resolve(strict=True)
            if not target.is_relative_to(allowed) or len(target.parts) > 64:
                raise ValueError('invalid target')
            fd = os.open(target, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                before = os.fstat(fd)
                uuid = self._read(fd, 'unique_id')
                authorization = self._read(fd, 'authorized')
                if not self.UUID.fullmatch(uuid) or authorization not in ('0', '1'):
                    raise ValueError('unresolved attachment')
                if link.resolve(strict=True) != target:
                    raise ValueError("changed target")
                after = link.stat()
                if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                    raise ValueError('changed attachment')
                records.append((name, str(target), before.st_dev, before.st_ino, uuid, authorization))
            finally:
                os.close(fd)
        return tuple(records)

    def observe(self):
        try:
            deadline = time.monotonic() + 1.0
            first = self._scan(deadline)
            second = self._scan(deadline)
            if first != second or time.monotonic() >= deadline:
                return Usb4AttachmentObservation('unknown')
            if not first:
                return Usb4AttachmentObservation('none')
            if len(first) != 1:
                return Usb4AttachmentObservation('ambiguous')
            record = first[0]
            return Usb4AttachmentObservation('unauthorized' if record[-1] == '0' else 'authorized', record[:-1])
        except (OSError, ValueError, UnicodeError, RuntimeError):
            return Usb4AttachmentObservation('unknown')
