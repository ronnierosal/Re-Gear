"""Suspend only the two managed legacy overrides for a supervised trial.

Root-only operation records in a fixed private directory on the home filesystem
are durable before changes. User-owned targets are
moved to private quarantine, never compare-then-unlinked. This requires the home
and backup directory to share a filesystem. No service operation is performed.

The user owns ancestors of the private root directory and can rename them. Held
FDs protect the current operation, not path rediscovery after a crash. Missing or
replaced directories fail closed and may require manual recovery; this is not an
immutable-path claim. Quarantined files are retained, never treated as authority.
"""
import base64
from contextlib import contextmanager
import hashlib
import json
import os
import re
import stat
import sys

from ..ports.presentation_activation import GamescopeUserContext
from .device_filter_dropin_store import DropinStore, LIMIT

ROOT_SUFFIX = ('.local', 'share', '.regear-filter-legacy-backups')
NAMES = {'gamescope-session.service': '90-handheld-dock-mode.conf',
         'steam-launcher.service': '90-regear-supervised-steam-trial.conf'}


class LegacyOverrideStore:
    def __init__(self, *, owner_uid=None, trusted_root_fd=None, trusted_home_fd=None):
        fixture = (owner_uid, trusted_root_fd, trusted_home_fd)
        if any(value is not None for value in fixture) and any(value is None for value in fixture):
            raise ValueError('fixture requires owner and both held directories')
        self.owner = 0 if owner_uid is None else owner_uid
        if type(self.owner) is not int or self.owner < 0:
            raise ValueError('invalid owner')
        for fd in (trusted_root_fd, trusted_home_fd):
            if fd is not None and (type(fd) is not int or fd < 0):
                raise ValueError('invalid held directory')
        self.root_fd, self.home_fd = trusted_root_fd, trusted_home_fd
        self.root_io = DropinStore() if owner_uid is None else DropinStore(owner_uid=owner_uid, trusted_directory_fd=trusted_root_fd)

    @staticmethod
    def _binding(user, unit, operation, expected):
        if (type(user) is not GamescopeUserContext or type(user.uid) is not int or user.uid <= 0
                or type(user.gid) is not int or user.gid < 0 or unit not in NAMES
                or type(operation) is not str or re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', operation) is None
                or expected is not None and (type(expected) is not bytes or len(expected) > LIMIT)):
            raise ValueError('exact user, operation, unit and expected original required')
        home = user.home.as_posix()
        if (re.fullmatch(r'/[A-Za-z0-9_.@+/-]+', home) is None
                or any(part in ('', '.', '..') for part in home.split('/')[1:])):
            raise ValueError('safe absolute home required')
        return dict(operation=operation, unit=unit, uid=user.uid, gid=user.gid, home=home,
                    expected=None if expected is None else base64.b64encode(expected).decode('ascii'))

    def _open(self, parts, *, trusted=None, owners):
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        fd = os.open('/', flags) if trusted is None else os.open('.', flags, dir_fd=trusted)
        try:
            for part in (None,) + tuple(parts):
                if part is not None:
                    child = os.open(part, flags, dir_fd=fd)
                    os.close(fd)
                    fd = child
                info = os.fstat(fd)
                if not stat.S_ISDIR(info.st_mode) or info.st_uid not in owners or info.st_mode & 0o022:
                    raise ValueError('unsafe legacy directory')
            return fd
        except BaseException:
            os.close(fd)
            raise

    @contextmanager
    def _directories(self, user, unit):
        if sys.platform != 'linux' or os.geteuid() != self.owner:
            raise ValueError('Linux root owner required')
        import fcntl
        root_parts = tuple(user.home.as_posix().strip('/').split('/')) + ROOT_SUFFIX
        root = self._open(root_parts if self.root_fd is None else (),
                          trusted=self.root_fd, owners=(self.owner, user.uid))
        target = None
        try:
            if os.fstat(root).st_uid != self.owner or stat.S_IMODE(os.fstat(root).st_mode) != 0o700:
                raise ValueError('private root backup directory required')
            fcntl.flock(root, fcntl.LOCK_EX | fcntl.LOCK_NB)
            parts = ('.config', 'systemd', 'user', unit + '.d')
            if self.home_fd is None:
                parts = tuple(user.home.as_posix().strip('/').split('/')) + parts
            target = self._open(parts, trusted=self.home_fd, owners=(self.owner, user.uid))
            if os.fstat(root).st_dev != os.fstat(target).st_dev:
                raise ValueError('same-filesystem quarantine required')
            yield root, target
        finally:
            if target is not None:
                os.close(target)
            os.close(root)

    def _save(self, root, name, record, *, exclusive=False):
        encoded = json.dumps(record, sort_keys=True, separators=(',', ':')).encode('ascii')
        self.root_io._write(root, name, dict(data=base64.b64encode(encoded).decode('ascii'),
            mode=0o600, uid=self.owner, gid=os.getegid()), exclusive=exclusive)

    def _load(self, root, name, binding):
        snapshot = self.root_io._snapshot(root, name, LIMIT * 4)
        if snapshot is None:
            return None
        if snapshot['mode'] != 0o600:
            raise ValueError('private backup required')
        record = json.loads(base64.b64decode(snapshot['data']))
        if (type(record) is not dict or set(record) != {'schema', 'binding', 'original', 'phase'}
                or type(record['schema']) is not int or record['schema'] != 1 or record['binding'] != binding
                or record['phase'] not in ('prepared', 'suspended', 'restoring', 'restored')):
            raise ValueError('backup identity changed')
        original = record['original']
        if original is None:
            if binding['expected'] is not None:
                raise ValueError('saved original missing')
        elif (type(original) is not dict or set(original) != {'data', 'mode', 'uid', 'gid'}
                or original['data'] != binding['expected'] or original['uid'] != binding['uid']
                or type(original['gid']) is not int or original['gid'] < 0
                or type(original['mode']) is not int or not 0 <= original['mode'] <= 0o7777
                or original['mode'] & 0o022):
            raise ValueError('saved original changed')
        return record

    def _operate(self, user, unit, operation, expected_original, *, restoring):
        binding = self._binding(user, unit, operation, expected_original)
        token = hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest()
        record_name, quarantine = token + '.json', token + '.held'
        user_io = DropinStore(owner_uid=user.uid, trusted_directory_fd=self.home_fd or 0)
        with self._directories(user, unit) as (root, target):
            record = self._load(root, record_name, binding)
            current = user_io._snapshot(target, NAMES[unit])
            if record is None:
                if restoring:
                    raise ValueError('no durable suspension backup')
                if (None if current is None else current['data']) != binding['expected']:
                    raise ValueError('legacy bytes differ from independent expectation')
                record = dict(schema=1, binding=binding, original=current, phase='prepared')
                self._save(root, record_name, record, exclusive=True)
            os.fsync(root)
            original = record['original']
            held = user_io._snapshot(root, quarantine)
            if held is not None and held != original:
                # Never delete an unexpected moved file. Return it without
                # replacing any new target, otherwise retain it for recovery.
                if current is None:
                    os.link(quarantine, NAMES[unit], src_dir_fd=root, dst_dir_fd=target, follow_symlinks=False)
                    os.fsync(target)
                raise ValueError('foreign quarantined file retained; recovery required')
            if current not in (None, original):
                raise ValueError('foreign legacy replacement')
            if restoring:
                if record['phase'] == 'restored':
                    if current != original:
                        raise ValueError('restored legacy file changed')
                    os.fsync(target)
                    return
                record['phase'] = 'restoring'
                self._save(root, record_name, record)
                if current is None and original is not None:
                    user_io._write(target, NAMES[unit], original, exclusive=True)
                os.fsync(target)
                record['phase'] = 'restored'
                self._save(root, record_name, record)
                return
            if record['phase'] not in ('prepared', 'suspended'):
                raise ValueError('retired suspension cannot replay')
            if record['phase'] == 'suspended' and current is not None:
                raise ValueError('suspended legacy target reappeared')
            if original is not None and held is None:
                if current != original:
                    raise ValueError('legacy source disappeared before suspension')
                # The destination is private and operation-specific under the
                # root lock. Rename retains any raced replacement for checking.
                os.rename(NAMES[unit], quarantine, src_dir_fd=target, dst_dir_fd=root)
                os.fsync(root)
                os.fsync(target)
                if user_io._snapshot(root, quarantine) != original:
                    raise ValueError('moved legacy file changed; retained for recovery')
            elif current is not None:
                raise ValueError('legacy target reappeared during suspension')
            os.fsync(target)
            record['phase'] = 'suspended'
            self._save(root, record_name, record)

    def suspend(self, user, unit, operation, *, expected_original):
        self._operate(user, unit, operation, expected_original, restoring=False)

    def restore(self, user, unit, operation, *, expected_original):
        self._operate(user, unit, operation, expected_original, restoring=True)
