"""Root-owned durable arm, separately readable by the session wrappers.

No arm removal, session restart, listener creation or launch grant occurs here.
An authenticated absent record means unarmed; malformed/unreadable data blocks.
Arm survives backend/session crashes until coordinated recovery removes it.
"""
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import json
import math
import os
import re
import stat
import sys
import uuid

from .device_filter_journal import _publish_exclusive

ROOT = "/var/lib/regear/device-filter-arm"
MAX_BYTES = 4096
UNITS = ("gamescope-session.service", "steam-launcher.service")


@dataclass(frozen=True)
class FilterArm:
    schema: int
    operation: str
    unit: str
    uid: int
    boot_hash: str
    topology_hash: str
    config_hash: str
    previous_invocation: str
    deadline: float

    def __post_init__(self):
        if type(self.schema) is not int or self.schema != 1 or type(self.unit) is not str or self.unit not in UNITS:
            raise ValueError("invalid arm schema or service")
        if type(self.uid) is not int or self.uid <= 0:
            raise ValueError("invalid arm user")
        for value, pattern in ((self.operation, r"[A-Za-z0-9_.:-]{1,128}"),
                (self.boot_hash, r"[0-9a-f]{64}"), (self.topology_hash, r"[0-9a-f]{64}"),
                (self.config_hash, r"[0-9a-f]{64}"), (self.previous_invocation, r"[0-9a-f]{32}")):
            if type(value) is not str or re.fullmatch(pattern, value) is None:
                raise ValueError("invalid arm identity")
        if type(self.deadline) not in (int, float) or not math.isfinite(self.deadline) or self.deadline <= 0:
            raise ValueError("invalid arm deadline")

    def require_current(self, *, unit, uid, boot_hash, topology_hash, config_hash, invocation, now):
        if (type(now) not in (int, float) or not math.isfinite(now) or not 0 <= now < self.deadline
                or type(uid) is not int or uid != self.uid
                or (unit, boot_hash, topology_hash, config_hash) !=
                   (self.unit, self.boot_hash, self.topology_hash, self.config_hash)
                or type(invocation) is not str or re.fullmatch(r"[0-9a-f]{32}", invocation) is None
                or invocation == self.previous_invocation):
            raise ValueError("arm does not match a fresh intended launch")


def encode_arm(arm):
    if type(arm) is not FilterArm:
        raise ValueError("typed arm required")
    arm = FilterArm(**asdict(arm))
    raw = json.dumps(asdict(arm), sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii")
    if len(raw) > MAX_BYTES:
        raise ValueError("arm exceeds bound")
    return raw


def _pairs(items):
    value = {}
    for key, item in items:
        if key in value:
            raise ValueError("duplicate arm field")
        value[key] = item
    return value


def decode_arm(raw):
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_BYTES:
        raise ValueError("invalid arm size")
    try:
        value = json.loads(raw.decode("ascii"), object_pairs_hook=_pairs)
        if type(value) is not dict or set(value) != set(FilterArm.__dataclass_fields__):
            raise ValueError("invalid arm shape")
        return FilterArm(**value)
    except (UnicodeError, RecursionError) as error:
        raise ValueError("invalid arm encoding") from error


class FilterArmStore:
    def __init__(self, *, owner_uid=None, trusted_directory_fd=None):
        if (owner_uid is None) != (trusted_directory_fd is None):
            raise ValueError("fixture owner requires trusted directory descriptor")
        if owner_uid is not None and (type(owner_uid) is not int or owner_uid < 0
                or type(trusted_directory_fd) is not int or trusted_directory_fd < 0):
            raise ValueError("invalid fixture context")
        self.owner_uid = 0 if owner_uid is None else owner_uid
        self.trusted_directory_fd = trusted_directory_fd

    def _secure(self, fd, *, directory):
        info = os.fstat(fd)
        if (info.st_uid != self.owner_uid or info.st_mode & 0o022
                or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
                or (not directory and info.st_nlink != 1)):
            raise ValueError("unsafe arm object")

    @contextmanager
    def _directory(self, *, missing_ok=False):
        if sys.platform != "linux":
            raise ValueError("Linux arm storage required")
        fd = None
        try:
            if self.trusted_directory_fd is not None:
                fd = os.dup(self.trusted_directory_fd)
                self._secure(fd, directory=True)
            else:
                flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                fd = os.open("/", flags)
                self._secure(fd, directory=True)
                for part in ROOT.strip("/").split("/"):
                    try:
                        child = os.open(part, flags, dir_fd=fd)
                    except FileNotFoundError:
                        if missing_ok:
                            yield None
                            return
                        raise
                    os.close(fd)
                    fd = child
                    self._secure(fd, directory=True)
            yield fd
        finally:
            if fd is not None:
                os.close(fd)

    @staticmethod
    def _name(unit):
        if type(unit) is not str or unit not in UNITS:
            raise ValueError("unapproved arm service")
        return unit + ".json"

    @contextmanager
    def _writer_directory(self):
        """Nonblocking writer serialization; recovery locks journal first."""
        import fcntl
        with self._directory() as directory:
            # A new open description also serializes trusted-fd fixture callers.
            locked = os.open('.', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                             dir_fd=directory)
            try:
                self._secure(locked, directory=True)
                fcntl.flock(locked, fcntl.LOCK_EX | fcntl.LOCK_NB)
                try:
                    yield locked
                finally:
                    fcntl.flock(locked, fcntl.LOCK_UN)
            finally:
                os.close(locked)

    def read(self, unit):
        name = self._name(unit)
        with self._directory(missing_ok=True) as directory:
            if directory is None:
                return None
            try:
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            except FileNotFoundError:
                return None
            try:
                self._secure(fd, directory=False)
                raw = bytearray()
                while len(raw) <= MAX_BYTES:
                    chunk = os.read(fd, MAX_BYTES + 1 - len(raw))
                    if not chunk: break
                    raw.extend(chunk)
                arm = decode_arm(bytes(raw))
                if arm.unit != unit:
                    raise ValueError("arm service mismatch")
                return arm
            finally:
                os.close(fd)

    def arm(self, record):
        raw = encode_arm(record)
        if os.geteuid() != self.owner_uid:
            raise ValueError("arm writer must be owner")
        target = self._name(record.unit)
        with self._writer_directory() as directory:
            temporary = ".pending-" + uuid.uuid4().hex
            fd = None
            try:
                fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o644, dir_fd=directory)
                os.fchmod(fd, 0o644)
                offset = 0
                while offset < len(raw):
                    written = os.write(fd, raw[offset:])
                    if written <= 0: raise OSError("short arm write")
                    offset += written
                os.fsync(fd)
                os.close(fd)
                fd = None
                _publish_exclusive(directory, temporary, target)
                os.fsync(directory)
            finally:
                if fd is not None: os.close(fd)
                try: os.unlink(temporary, dir_fd=directory)
                except FileNotFoundError: pass
