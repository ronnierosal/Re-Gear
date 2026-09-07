"""Durable rollback for the two designated experimental systemd user drop-ins.

No daemon reload, service operation, or arbitrary-path interface. Each directory
retains a terminal backup record: a restored trial cannot be applied again.
Only the trusted administrator may write the directories; flock serializes users
of this store, not unrelated privileged configuration writers.
"""
import base64
from contextlib import contextmanager
import json
import os
import stat
import sys
import uuid

from .device_filter_runtime_store import _rename_exclusive

UNITS = ('steam-launcher.service', 'gamescope-session.service')
NAME = '95-regear-filter-runtime.conf'
BACKUP = '.regear-device-filter-trial-backup.json'
LIMIT = 65536


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_uid,
            info.st_gid, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


class DropinStore:
    def __init__(self, *, owner_uid=None, trusted_directory_fd=None):
        if (owner_uid is None) != (trusted_directory_fd is None):
            raise ValueError('fixture requires owner and held directory')
        self.owner = 0 if owner_uid is None else owner_uid
        self.trusted = trusted_directory_fd
        if self.trusted is not None and (type(self.trusted) is not int or self.trusted < 0):
            raise ValueError('invalid held directory')
        if type(self.owner) is not int or self.owner < 0:
            raise ValueError('invalid owner')

    @contextmanager
    def _directory(self, unit):
        if unit not in UNITS or sys.platform != 'linux' or os.geteuid() != self.owner:
            raise ValueError('exact unit and Linux owner required')
        import fcntl
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        fd = os.open('/', flags) if self.trusted is None else os.open('.', flags, dir_fd=self.trusted)
        try:
            parts = ('etc', 'systemd', 'user', unit + '.d') if self.trusted is None else (unit + '.d',)
            for part in (None,) + parts:
                if part is not None:
                    child = os.open(part, flags, dir_fd=fd)
                    os.close(fd)
                    fd = child
                info = os.fstat(fd)
                if not stat.S_ISDIR(info.st_mode) or info.st_uid != self.owner or info.st_mode & 0o022:
                    raise ValueError('unsafe drop-in directory')
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield fd
        finally:
            os.close(fd)

    def _snapshot(self, directory, name, limit=LIMIT):
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        except FileNotFoundError:
            return None
        try:
            before = os.fstat(fd)
            if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                    or before.st_uid != self.owner or before.st_mode & 0o022 or before.st_size > limit):
                raise ValueError('unsafe drop-in file')
            raw = bytearray()
            while len(raw) <= limit:
                chunk = os.read(fd, min(65536, limit + 1 - len(raw)))
                if not chunk:
                    break
                raw.extend(chunk)
            if len(raw) > limit or _identity(os.fstat(fd)) != _identity(before) or _identity(os.stat(name, dir_fd=directory, follow_symlinks=False)) != _identity(before):
                raise ValueError('drop-in changed during read')
            return dict(data=base64.b64encode(raw).decode('ascii'), mode=stat.S_IMODE(before.st_mode),
                        uid=before.st_uid, gid=before.st_gid)
        finally:
            os.close(fd)

    def _write(self, directory, name, snapshot, *, exclusive=False):
        temp = '.regear-pending-' + uuid.uuid4().hex
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        try:
            raw = base64.b64decode(snapshot['data'], validate=True)
            offset = 0
            while offset < len(raw):
                written = os.write(fd, raw[offset:])
                if written <= 0:
                    raise OSError('short drop-in write')
                offset += written
            os.fchown(fd, snapshot['uid'], snapshot['gid'])
            os.fchmod(fd, snapshot['mode'])
            os.fsync(fd)
        finally:
            os.close(fd)
        try:
            if exclusive:
                # Durable exclusive backup publication; no partial final record.
                _rename_exclusive(directory, temp, name)
            else:
                os.replace(temp, name, src_dir_fd=directory, dst_dir_fd=directory)
            os.fsync(directory)
        finally:
            try:
                os.unlink(temp, dir_fd=directory)
            except FileNotFoundError:
                pass

    def _record(self, directory, record, *, exclusive=False):
        raw = json.dumps(record, sort_keys=True, separators=(',', ':')).encode('ascii')
        self._write(directory, BACKUP, dict(data=base64.b64encode(raw).decode('ascii'),
            mode=0o600, uid=self.owner, gid=os.getegid()), exclusive=exclusive)

    def _load(self, directory, unit):
        snapshot = self._snapshot(directory, BACKUP, LIMIT * 4)
        if snapshot is None:
            return None
        if snapshot['mode'] != 0o600:
            raise ValueError('unsafe backup mode')
        record = json.loads(base64.b64decode(snapshot['data']))
        if (set(record) != {'version', 'unit', 'original', 'candidate', 'phase'} or type(record['version']) is not int or record['version'] != 1
                or record['unit'] != unit
                or record['phase'] not in ('prepared', 'restoring', 'restored')):
            raise ValueError('invalid backup record')
        for key in ('original', 'candidate'):
            value = record[key]
            if value is None and key == 'original':
                continue
            if (type(value) is not dict or set(value) != {'data', 'uid', 'gid', 'mode'}
                    or value['uid'] != self.owner or type(value['gid']) is not int or value['gid'] < 0
                    or type(value['mode']) is not int or not 0 <= value['mode'] <= 0o7777
                    or value['mode'] & 0o022 or len(base64.b64decode(value['data'], validate=True)) > LIMIT):
                raise ValueError('invalid saved file')
        return record

    def apply(self, unit, candidate):
        if type(candidate) is not bytes or not candidate or len(candidate) > LIMIT:
            raise ValueError('bounded candidate bytes required')
        with self._directory(unit) as directory:
            desired = dict(data=base64.b64encode(candidate).decode('ascii'), mode=0o644,
                           uid=self.owner, gid=os.getegid())
            record = self._load(directory, unit)
            if record is None:
                record = dict(version=1, unit=unit, original=self._snapshot(directory, NAME), candidate=desired, phase='prepared')
                self._record(directory, record, exclusive=True)
            if record['phase'] != 'prepared' or record['candidate'] != desired:
                raise ValueError('different or retired trial')
            os.fsync(directory)  # Reconcile a backup rename interrupted before directory fsync.
            current = self._snapshot(directory, NAME)
            if current not in (record['original'], desired):
                raise ValueError('foreign drop-in replacement')
            if current != desired:
                self._write(directory, NAME, desired)
            os.fsync(directory)

    def restore(self, unit, *, expected_candidate=None):
        with self._directory(unit) as directory:
            record = self._load(directory, unit)
            if record is None:
                raise ValueError('no durable backup')
            os.fsync(directory)  # Reconcile a backup rename interrupted before directory fsync.
            if expected_candidate is not None:
                if (type(expected_candidate) is not bytes or not expected_candidate
                        or base64.b64decode(record['candidate']['data'], validate=True) != expected_candidate):
                    raise ValueError('backup differs from expected trial candidate')
            current = self._snapshot(directory, NAME)
            if current not in (record['candidate'], record['original']):
                raise ValueError('foreign drop-in replacement')
            if record['phase'] == 'restored':
                if current != record['original']:
                    raise ValueError('restored file replaced')
                os.fsync(directory)
                return
            record['phase'] = 'restoring'
            self._record(directory, record)
            if current != record['original']:
                if record['original'] is None:
                    os.unlink(NAME, dir_fd=directory)
                    os.fsync(directory)
                else:
                    self._write(directory, NAME, record['original'])
            os.fsync(directory)
            record['phase'] = 'restored'
            self._record(directory, record)
