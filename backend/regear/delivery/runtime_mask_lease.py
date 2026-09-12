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
import json
from contextlib import contextmanager

UNITS = frozenset(('gamescope-session.target', 'gamescope-session.service',
    'wireplumber.service', 'pipewire.service', 'pipewire.socket'))

@dataclass(frozen=True)
class MaskIdentity:
    unit: str
    token: str
    device: int
    inode: int


@dataclass(frozen=True)
class MaskLeaseIntent:
    token: str
    boot_identity: str
    prior_active: tuple[str, ...]


class MaskLeaseJournal:
    """Immutable bounded records inside an already-open private directory.

    Hold locked() across record_mask AND RuntimeMaskLease.create publication,
    and recovery revocation plus owned mask filesystem changes. Release it for
    bounded blocking recovery commands so a stalled runner cannot lock out the
    watchdog. Revocation is permanent. Parent stop dispatch uses a short lock
    across ownership_active AND dispatch, never check then release then stop.
    No cleanup/deletion API: corrupted or unfinished evidence remains intact.
    """
    def __init__(self, directory_fd, *, owner_uid):
        self.fd = None
        self._locked = False
        if type(owner_uid) is not int or owner_uid < 0 or os.geteuid() != owner_uid:
            raise ValueError('journal owner mismatch')
        self.owner_uid = owner_uid
        try:
            self.fd = os.dup(directory_fd)
            value = os.fstat(self.fd)
            if not stat.S_ISDIR(value.st_mode) or value.st_uid != owner_uid or stat.S_IMODE(value.st_mode) != 0o700:
                raise ValueError('journal directory unsafe')
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def _secure(self, fd):
        value = os.fstat(fd)
        if (not stat.S_ISREG(value.st_mode) or value.st_uid != self.owner_uid
                or stat.S_IMODE(value.st_mode) != 0o600 or value.st_nlink != 1):
            raise ValueError('journal file unsafe')

    @contextmanager
    def locked(self):
        import fcntl
        if self._locked:
            raise ValueError('journal already locked')
        fd = os.open('mask-journal.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK,
                     0o600, dir_fd=self.fd)
        try:
            self._secure(fd)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._locked = True
            try:
                yield self
            finally:
                self._locked = False
        finally:
            os.close(fd)

    def _require_lock(self):
        if not self._locked:
            raise ValueError('journal lock required')

    @contextmanager
    def recovery_locked(self):
        """Serialize recovery runners, independently of short producer locking.

        May span bounded recovery commands. Contention refuses immediately;
        it never grants authority to publish masks or change journal records.
        """
        import fcntl
        fd = os.open('recovery-executor.lock', os.O_CREAT | os.O_RDWR |
                     os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=self.fd)
        try:
            self._secure(fd)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield self
        finally:
            os.close(fd)

    def _read(self, name):
        self._require_lock()
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.fd)
        except FileNotFoundError:
            return None
        try:
            self._secure(fd)
            data = os.read(fd, 4097)
            if len(data) > 4096:
                raise ValueError('journal oversized')
            def pairs(items):
                result = {}
                for key, value in items:
                    if key in result:
                        raise ValueError('duplicate journal field')
                    result[key] = value
                return result
            result = json.loads(data.decode('utf-8'), object_pairs_hook=pairs)
            if type(result) is not dict:
                raise ValueError('journal object required')
            return result
        finally:
            os.close(fd)

    def _write(self, name, value):
        self._require_lock()
        data = json.dumps(value, sort_keys=True, separators=(',', ':')).encode('ascii')
        if len(data) > 4096:
            raise ValueError('journal oversized')
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=self.fd)
        try:
            self._secure(fd)
            if os.write(fd, data) != len(data):
                raise OSError('journal short write')
            os.fsync(fd)
        finally:
            os.close(fd)
        os.fsync(self.fd)

    @staticmethod
    def _valid_intent(intent):
        return (type(intent) is MaskLeaseIntent and type(intent.token) is str
                and re.fullmatch('[a-f0-9]{32}', intent.token)
                and type(intent.boot_identity) is str and re.fullmatch('[a-f0-9]{64}', intent.boot_identity)
                and type(intent.prior_active) is tuple
                and all(type(unit) is str and unit in UNITS for unit in intent.prior_active)
                and len(set(intent.prior_active)) == len(intent.prior_active))

    def create_intent(self, intent):
        if not self._valid_intent(intent):
            raise ValueError('journal intent invalid')
        # Existing recovery evidence must never be ignored even without intent.
        if self._read('recovering.json') is not None or self._read('finished.json') is not None:
            raise ValueError('journal recovery already started')
        self._write('intent.json', dict(schema_version=1, token=intent.token,
                    boot_identity=intent.boot_identity, prior_active=list(intent.prior_active)))
        return True

    def load_intent(self):
        value = self._read('intent.json')
        if (value is None or set(value) != {'schema_version', 'token', 'boot_identity', 'prior_active'}
                or type(value['schema_version']) is not int or value['schema_version'] != 1
                or type(value['prior_active']) is not list):
            raise ValueError('journal intent unavailable')
        intent = MaskLeaseIntent(value['token'], value['boot_identity'], tuple(value['prior_active']))
        if not self._valid_intent(intent):
            raise ValueError('journal intent invalid')
        return intent

    def _match(self, intent):
        if not self._valid_intent(intent) or self.load_intent() != intent:
            raise ValueError('journal identity changed')

    def record_mask(self, intent, identity):
        self._match(intent)
        if self._read('recovering.json') is not None or self._read('finished.json') is not None:
            raise ValueError('journal recovery already started')
        if (type(identity) is not MaskIdentity or identity.token != intent.token
                or identity.unit not in UNITS or type(identity.device) is not int or identity.device < 0
                or type(identity.inode) is not int or identity.inode <= 0):
            raise ValueError('mask identity invalid')
        self._write(identity.unit + '.mask.json', dict(unit=identity.unit, token=identity.token,
                    device=identity.device, inode=identity.inode))
        return True

    def load_masks(self, intent):
        self._match(intent)
        records = []
        for unit in sorted(UNITS):
            value = self._read(unit + '.mask.json')
            if value is None:
                continue
            if set(value) != {'unit', 'token', 'device', 'inode'}:
                raise ValueError('mask record invalid')
            identity = MaskIdentity(**value)
            if (identity.unit != unit or identity.token != intent.token
                    or type(identity.device) is not int or identity.device < 0
                    or type(identity.inode) is not int or identity.inode <= 0):
                raise ValueError('mask record invalid')
            records.append(identity)
        return tuple(records)

    def _marker(self, intent):
        return dict(schema_version=1, token=intent.token, boot_identity=intent.boot_identity)

    def _marker_matches(self, value, intent):
        return (type(value) is dict and type(value.get('schema_version')) is int
                and value == self._marker(intent))

    def is_finished(self, intent):
        """Read completion strictly; corruption never reads as incomplete."""
        self._match(intent)
        self.load_masks(intent)
        recovering = self._read('recovering.json')
        finished = self._read('finished.json')
        if recovering is not None and not self._marker_matches(recovering, intent):
            raise ValueError('recovery marker invalid')
        if finished is None:
            return False
        if not self._marker_matches(finished, intent) or recovering is None:
            raise ValueError('completion marker invalid')
        return True

    def ownership_active(self, intent):
        """Caller holds locked() across this guard and its subsequent action."""
        self._match(intent)
        self.load_masks(intent)
        finished = self.is_finished(intent)
        return not finished and self._read('recovering.json') is None

    def begin_recovery(self, intent):
        self._match(intent)
        existing = self._read('recovering.json')
        if existing is None:
            self._write('recovering.json', self._marker(intent))
        elif not self._marker_matches(existing, intent):
            raise ValueError('recovery marker invalid')
        return self.load_masks(intent)

    def finish(self, intent, verified):
        self._match(intent)
        if not self._marker_matches(self._read('recovering.json'), intent):
            raise ValueError('recovery not started')
        already_finished = self.is_finished(intent)
        before = self.load_masks(intent)
        if verified() is not True:
            raise ValueError('recovery unverified')
        self._match(intent)
        if (self.load_masks(intent) != before
                or not self._marker_matches(self._read('recovering.json'), intent)
                or self.is_finished(intent) != already_finished):
            raise ValueError('recovery evidence changed')
        if already_finished:
            return True
        self._write('finished.json', self._marker(intent))
        return True


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
