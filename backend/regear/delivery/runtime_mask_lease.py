"""Owned user-runtime masks; internal primitive, not a public executor.

Callers provide already-open runtime-unit and private lease directories and a
fsynced ownership journal callback. No path is resolved with root privileges.
Restoration quarantines an entry atomically before verifying/deleting it; an
unexpected replacement is returned without clobbering a concurrent new entry.
"""
from dataclasses import dataclass
import ctypes
import os
import re
import stat

UNITS = frozenset(('gamescope-session.target', 'gamescope-session.service',
    'wireplumber.service', 'pipewire.service', 'pipewire.socket'))

@dataclass(frozen=True)
class MaskIdentity:
    unit: str
    token: str
    device: int
    inode: int


def _rename_exclusive(source_fd, source, destination_fd, destination):
    libc = ctypes.CDLL(None, use_errno=True)
    rename = libc.renameat2
    rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    rename.restype = ctypes.c_int
    if rename(source_fd, source.encode(), destination_fd, destination.encode(), 1):
        raise OSError(ctypes.get_errno(), 'exclusive mask rename failed')


class RuntimeMaskLease:
    def __init__(self, units_fd, lease_fd, *, owner_uid):
        if type(owner_uid) is not int or owner_uid < 0 or os.geteuid() != owner_uid:
            raise ValueError('mask owner mismatch')
        self.units_fd = self.lease_fd = None
        self.owner_uid = owner_uid
        try:
            self.units_fd = os.dup(units_fd)
            self.lease_fd = os.dup(lease_fd)
            records = [os.fstat(fd) for fd in (self.units_fd, self.lease_fd)]
            if any(not stat.S_ISDIR(s.st_mode) or s.st_uid != owner_uid or s.st_mode & 0o022 for s in records):
                raise ValueError('mask directory unsafe')
            if (records[0].st_dev != records[1].st_dev
                    or records[0].st_ino == records[1].st_ino):
                raise ValueError('mask directories must be distinct on one filesystem')
        except BaseException:
            self.close()
            raise

    def close(self):
        for name in ('units_fd', 'lease_fd'):
            fd = getattr(self, name, None)
            if fd is not None:
                os.close(fd)
                setattr(self, name, None)

    @staticmethod
    def _name(unit, token):
        if type(unit) is not str or unit not in UNITS or type(token) is not str or not re.fullmatch('[a-f0-9]{32}', token):
            raise ValueError('mask identity invalid')
        return token + '-' + unit

    def _matches(self, fd, name, identity):
        try:
            value = os.stat(name, dir_fd=fd, follow_symlinks=False)
            return (stat.S_ISLNK(value.st_mode) and value.st_uid == self.owner_uid
                    and (value.st_dev, value.st_ino) == (identity.device, identity.inode)
                    and os.readlink(name, dir_fd=fd) == '/dev/null')
        except FileNotFoundError:
            return False

    def create(self, unit, token, record_intent):
        """Publish only after exact symlink identity has been durably recorded."""
        anchor = self._name(unit, token)
        os.symlink('/dev/null', anchor, dir_fd=self.lease_fd)
        os.fsync(self.lease_fd)
        value = os.stat(anchor, dir_fd=self.lease_fd, follow_symlinks=False)
        identity = MaskIdentity(unit, token, value.st_dev, value.st_ino)
        if record_intent(identity) is not True:
            raise ValueError('mask intent not confirmed')
        # Hard-link the recorded symlink inode itself, never its /dev/null target.
        os.link(anchor, unit, src_dir_fd=self.lease_fd, dst_dir_fd=self.units_fd,
                follow_symlinks=False)
        os.fsync(self.units_fd)
        return identity

    def restore(self, identity):
        """Remove only the owned inode. Caller serializes normal/watchdog cleanup."""
        if type(identity) is not MaskIdentity:
            raise ValueError('mask identity invalid')
        anchor = self._name(identity.unit, identity.token)
        retired = 'retired-' + anchor
        if not self._matches(self.lease_fd, anchor, identity):
            return False
        # Recover a previous interrupted quarantine before interpreting absence
        # of the live entry. A foreign entry must never disappear from accounting.
        try:
            os.stat(retired, dir_fd=self.lease_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            if not self._matches(self.lease_fd, retired, identity):
                try:
                    _rename_exclusive(self.lease_fd, retired, self.units_fd, identity.unit)
                    os.fsync(self.units_fd)
                    os.fsync(self.lease_fd)
                except OSError:
                    pass
                return False
            os.unlink(retired, dir_fd=self.lease_fd)
            os.fsync(self.lease_fd)
        try:
            _rename_exclusive(self.units_fd, identity.unit, self.lease_fd, retired)
        except FileNotFoundError:
            os.fsync(self.units_fd)
            return True  # Already absent; no unit configuration is removed.
        except OSError:
            return False
        if not self._matches(self.lease_fd, retired, identity):
            try:
                _rename_exclusive(self.lease_fd, retired, self.units_fd, identity.unit)
                os.fsync(self.units_fd)
            except OSError:
                pass  # Preserve displaced entry in private storage for recovery.
            os.fsync(self.lease_fd)
            return False
        os.unlink(retired, dir_fd=self.lease_fd)
        os.fsync(self.units_fd)
        os.fsync(self.lease_fd)
        # Keep anchor until journal retirement; repeated restoration stays provable.
        return True
