"""Root-owned owner checkpoints for the prepare-and-recover session experiment.

Publication precedes scheduling. A persisted scheduling phase can only enter
recovery; it never grants permission to schedule again. restart_requested means
command intent only, not observed session recovery or hardware verification.
"""
import base64
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

from ..ports.presentation_activation import GamescopeUserContext
from .device_filter_arm import FilterArm, decode_arm, encode_arm
from .device_filter_dropin_store import DropinStore, LIMIT
from .device_filter_runtime_store import _validate
from .device_filter_trial_config import render_trial_dropin

ROOT = '/var/lib/regear/prepared-session-trial'
MAX_BYTES = LIMIT * 4
NEXT = {'prepared': ('legacy_suspending', 'recovering'),
        'legacy_suspending': ('dropin_applying', 'recovering'),
        'dropin_applying': ('arming', 'recovering'),
        'arming': ('scheduling', 'recovering'), 'scheduling': ('recovering',),
        'recovering': ('restart_requested',), 'restart_requested': ()}


@dataclass(frozen=True)
class TrialOwnerRecord:
    arm: FilterArm
    user: GamescopeUserContext
    runtime_digest: str
    runtime_path: str
    candidate: bytes
    legacy_original: bytes | None
    phase: str = 'prepared'
    hardware_verified: bool = False
    recovery_from: str | None = None


def _validate_record(record):
    if type(record) is not TrialOwnerRecord or type(record.arm) is not FilterArm:
        raise ValueError('typed owner record required')
    encode_arm(record.arm)
    user = record.user
    if (type(user) is not GamescopeUserContext or type(user.uid) is not int or user.uid != record.arm.uid
            or type(user.gid) is not int or user.gid < 0 or type(user.username) is not str
            or re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]{0,63}', user.username) is None):
        raise ValueError('independently resolved user required')
    for value in (user.home, user.runtime_directory, user.bus_path):
        if not isinstance(value, Path):
            raise ValueError('typed user paths required')
        text = value.as_posix()
        if (re.fullmatch(r'/[A-Za-z0-9_.@+/-]+', text) is None
                or any(part in ('', '.', '..') for part in text.split('/')[1:])):
            raise ValueError('safe user paths required')
    if (user.runtime_directory.as_posix() != '/run/user/' + str(user.uid)
            or user.bus_path.as_posix() != '/run/user/' + str(user.uid) + '/bus'):
        raise ValueError('fixed user bus context required')
    if (type(record.runtime_digest) is not str or re.fullmatch(r'[0-9a-f]{64}', record.runtime_digest) is None
            or record.runtime_path != '/var/lib/regear/filter-runtime/' + record.runtime_digest + '/runtime.pyz'
            or type(record.candidate) is not bytes or not 0 < len(record.candidate) <= LIMIT
            or record.legacy_original is not None and (type(record.legacy_original) is not bytes or len(record.legacy_original) > LIMIT)
            or type(record.phase) is not str or record.phase not in NEXT or record.hardware_verified is not False):
        raise ValueError('bounded nonverified trial identity required')
    if record.phase in ('recovering', 'restart_requested'):
        if record.recovery_from not in ('prepared', 'legacy_suspending', 'dropin_applying', 'arming', 'scheduling'):
            raise ValueError('durable recovery origin required')
    elif record.recovery_from is not None:
        raise ValueError('recovery origin before recovery')
    return record


def build_trial_owner_record(arm, user, runtime, *, candidate, legacy_original):
    _validate(runtime)
    if type(arm) is not FilterArm:
        raise ValueError('typed arm required')
    if render_trial_dropin(runtime, arm.unit, user=user).content != candidate:
        raise ValueError('candidate differs from exact runtime configuration')
    return _validate_record(TrialOwnerRecord(arm, user, runtime.digest, runtime.path,
                                             candidate, legacy_original))


def _encode(record):
    _validate_record(record)
    user = asdict(record.user)
    for key in ('home', 'runtime_directory', 'bus_path'):
        user[key] = user[key].as_posix()
    value = dict(schema=1, arm=json.loads(encode_arm(record.arm)), user=user,
        runtime_digest=record.runtime_digest, runtime_path=record.runtime_path,
        candidate=base64.b64encode(record.candidate).decode('ascii'),
        legacy_original=None if record.legacy_original is None else base64.b64encode(record.legacy_original).decode('ascii'),
        phase=record.phase, hardware_verified=False, recovery_from=record.recovery_from)
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('ascii')
    if len(raw) > MAX_BYTES:
        raise ValueError('owner record exceeds bound')
    return raw


def _decode(raw):
    def unique(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError('duplicate owner record field')
            value[key] = item
        return value
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_BYTES:
        raise ValueError('bounded owner bytes required')
    value = json.loads(raw.decode('ascii'), object_pairs_hook=unique)
    keys = {'schema', 'arm', 'user', 'runtime_digest', 'runtime_path', 'candidate', 'legacy_original', 'phase', 'hardware_verified', 'recovery_from'}
    if (type(value) is not dict or set(value) != keys or type(value['schema']) is not int or value['schema'] != 1
            or type(value['user']) is not dict or set(value['user']) != set(GamescopeUserContext.__dataclass_fields__)):
        raise ValueError('invalid owner record schema')
    user = value['user']
    for key in ('home', 'runtime_directory', 'bus_path'):
        if type(user[key]) is not str:
            raise ValueError('encoded user path required')
        user[key] = Path(user[key])
    return _validate_record(TrialOwnerRecord(
        decode_arm(json.dumps(value['arm'], allow_nan=False).encode('ascii')),
        GamescopeUserContext(**user), value['runtime_digest'], value['runtime_path'],
        base64.b64decode(value['candidate'], validate=True),
        None if value['legacy_original'] is None else base64.b64decode(value['legacy_original'], validate=True),
        value['phase'], value['hardware_verified'], value['recovery_from']))


class TrialOwnerStore:
    def __init__(self, *, owner_uid=None, trusted_directory_fd=None):
        self.io = DropinStore(owner_uid=owner_uid, trusted_directory_fd=trusted_directory_fd)

    @contextmanager
    def _directory(self):
        if sys.platform != 'linux' or os.geteuid() != self.io.owner:
            raise ValueError('Linux root owner required')
        import fcntl
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        fd = os.open('/', flags) if self.io.trusted is None else os.open('.', flags, dir_fd=self.io.trusted)
        try:
            parts = ROOT.strip('/').split('/') if self.io.trusted is None else ()
            for part in (None, *parts):
                if part is not None:
                    child = os.open(part, flags, dir_fd=fd)
                    os.close(fd)
                    fd = child
                info = os.fstat(fd)
                if not stat.S_ISDIR(info.st_mode) or info.st_uid != self.io.owner or info.st_mode & 0o022:
                    raise ValueError('unsafe owner directory')
            if stat.S_IMODE(os.fstat(fd).st_mode) != 0o700:
                raise ValueError('private owner directory required')
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield fd
        finally:
            os.close(fd)

    @staticmethod
    def _name(operation, unit):
        if (type(operation) is not str or re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', operation) is None
                or unit not in ('gamescope-session.service', 'steam-launcher.service')):
            raise ValueError('exact operation and service required')
        return hashlib.sha256((operation + '\0' + unit).encode('ascii')).hexdigest() + '.json'

    def _read(self, directory, operation, unit):
        snapshot = self.io._snapshot(directory, self._name(operation, unit), MAX_BYTES)
        if snapshot is None:
            return None
        if snapshot['mode'] != 0o600:
            raise ValueError('private owner file required')
        record = _decode(base64.b64decode(snapshot['data'], validate=True))
        if (record.arm.operation, record.arm.unit) != (operation, unit):
            raise ValueError('owner key differs from record')
        return record

    def _write(self, directory, record, *, exclusive=False):
        self.io._write(directory, self._name(record.arm.operation, record.arm.unit),
            dict(data=base64.b64encode(_encode(record)).decode('ascii'), mode=0o600,
                 uid=self.io.owner, gid=os.getegid()), exclusive=exclusive)

    def create(self, record):
        _validate_record(record)
        if record.phase != 'prepared':
            raise ValueError('owner must start prepared')
        with self._directory() as directory:
            self._write(directory, record, exclusive=True)
        return record

    def read(self, operation, unit):
        with self._directory() as directory:
            record = self._read(directory, operation, unit)
            os.fsync(directory)  # Reconcile a publication interrupted at directory fsync.
            return record

    def transition(self, operation, unit, expected_phase, new_phase, *, expected_record):
        _validate_record(expected_record)
        if (expected_record.phase != expected_phase or new_phase not in NEXT[expected_phase]
                or (operation, unit) != (expected_record.arm.operation, expected_record.arm.unit)):
            raise ValueError('invalid owner phase transition')
        with self._directory() as directory:
            current = self._read(directory, operation, unit)
            if current != expected_record:
                raise ValueError('owner checkpoint changed')
            result = replace(current, phase=new_phase,
                recovery_from=current.phase if new_phase == 'recovering' else current.recovery_from)
            self._write(directory, result)
            return result
