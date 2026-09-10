"""Experimental root-owned CAS journal; no RPC or kernel authority.

Only a newly committed grant returns delivery_granted. Reads are observations,
never redelivery authority. Startup must explicitly call recover under CAS;
status inspection does not change phases. Kernel ownership evidence remains
the adapter's responsibility; this module neither pins nor detaches filters.
"""
from contextlib import contextmanager
import ctypes
from dataclasses import asdict, dataclass, fields
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import time
import uuid

from .device_filter_lifecycle import (FilterLifecycle, LaunchBinding, OwnedFilter, Phase,
    PairedOwnership, PairedStage, PairedReceiveIdentity, DirectCleanupStage)

MAX_BYTES = 8192
DEFAULT_ROOT = Path("/var/lib/regear/device-filter")


class JournalInitialPublicationUncertain(OSError):
    """This create exclusively published its binding; durability needs readback."""
    def __init__(self,binding):
        if type(binding) is not LaunchBinding:raise ValueError('exact initial binding required')
        self.binding=binding
        super().__init__('initial journal publication requires reconciliation')


def _acquire_lock(lock, locking, *, wait=time.sleep):
    """Bound contention; a stalled writer cannot hang the launch handshake."""
    for attempt in range(50):
        try:
            locking.flock(lock, locking.LOCK_EX | locking.LOCK_NB)
            return
        except BlockingIOError:
            if attempt == 49:
                raise TimeoutError("filter journal writer busy")
            wait(0.02)


def _publish_exclusive(directory, temporary, target):
    # One atomic no-replace rename avoids a crash window with two hard links
    # to the initial record, which strict recovery would correctly reject.
    library = ctypes.CDLL(None, use_errno=True)
    try:
        rename = library.renameat2
    except AttributeError as error:
        raise OSError("atomic exclusive publication unavailable") from error
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(directory, temporary.encode("ascii"), directory, target.encode("ascii"), 1) != 0:
        raise OSError(ctypes.get_errno(), "exclusive journal publication failed")


@dataclass(frozen=True)
class JournalRecord:
    revision: int
    lifecycle: FilterLifecycle
    delivery_granted: bool = False
    paired: PairedOwnership | None = None
    direct_cleanup: DirectCleanupStage | None = None

    def __post_init__(self):
        if self.direct_cleanup is not None:
            if (type(self.direct_cleanup) is not DirectCleanupStage
                    or self.lifecycle.phase is not Phase.CANCELLED
                    or not self.lifecycle.owned_detach_allowed or self.delivery_granted is not False
                    or (self.paired is not None and (type(self.paired) is not PairedOwnership
                        or self.paired.stage is not PairedStage.COMPLETE))):
                raise ValueError('direct cleanup requires cancelled owned identity and complete pair')
        if self.paired is not None:
            if (type(self.paired) is not PairedOwnership or self.delivery_granted is not False
                    or self.lifecycle.phase is Phase.GRANTED):
                raise ValueError('paired ownership is recovery-only')
            if (self.paired.stage in (PairedStage.RECEIVE_RELEASE_PENDING,PairedStage.RECEIVE_RELEASED,
                    PairedStage.RETENTION_RELEASE_PENDING,PairedStage.COMPLETE)
                    and self.lifecycle.phase is not Phase.CANCELLED):
                raise ValueError('paired release metadata requires cancelled lifecycle')


def encode_record(record):
    if type(record) is not JournalRecord or type(record.revision) is not int or record.revision < 1:
        raise ValueError("invalid journal revision")
    state = record.lifecycle
    value = dict(schema=1, revision=record.revision, binding=asdict(state.binding),
                 phase=state.phase.value, owned=asdict(state.owned) if state.owned else None)
    if record.paired is not None:
        value['schema']=2
        value['paired']=dict(map_id=record.paired.map_id,stage=record.paired.stage.value,
            receive=asdict(record.paired.receive) if record.paired.receive else None)
    if record.direct_cleanup is not None:
        value['schema']=3
        value.setdefault('paired',None)
        value['direct_cleanup']=record.direct_cleanup.value
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(raw) > MAX_BYTES:
        raise ValueError("journal record exceeds bound")
    return raw


def _pairs(values):
    result = {}
    for key, value in values:
        if key in result:
            raise ValueError("duplicate journal key")
        result[key] = value
    return result


def _nonfinite(value):
    raise ValueError("nonfinite journal number")


def decode_record(raw):
    if type(raw) is not bytes or not raw or len(raw) > MAX_BYTES:
        raise ValueError("invalid journal size")
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_nonfinite)
    if (type(value) is not dict or type(value.get('schema')) is not int or value['schema'] not in (1,2,3)
            or set(value) != {"schema", "revision", "binding", "phase", "owned"} | ({'paired'} if value['schema']>=2 else set()) | ({'direct_cleanup'} if value['schema']==3 else set())
            or type(value["revision"]) is not int or value["revision"] < 1):
        raise ValueError("invalid journal envelope")
    binding = value["binding"]
    if type(binding) is not dict or set(binding) != {field.name for field in fields(LaunchBinding)}:
        raise ValueError("invalid journal binding")
    owned = value["owned"]
    if owned is not None:
        if type(owned) is not dict or set(owned) != {field.name for field in fields(OwnedFilter)}:
            raise ValueError("invalid journal ownership")
        owned = OwnedFilter(**owned)
    paired=None
    if value['schema']>=2 and (value['schema']==2 or value['paired'] is not None):
        metadata=value['paired']
        if type(metadata) is not dict or set(metadata)!={'map_id','stage','receive'}:
            raise ValueError('invalid paired envelope')
        receive=metadata['receive']
        if receive is not None:
            if type(receive) is not dict or set(receive)!={field.name for field in fields(PairedReceiveIdentity)}:
                raise ValueError('invalid paired receive fields')
            receive=PairedReceiveIdentity(**receive)
        paired=PairedOwnership(metadata['map_id'],PairedStage(metadata['stage']),receive)
    return JournalRecord(value["revision"], FilterLifecycle(
        LaunchBinding(**binding), Phase(value["phase"]), owned),paired=paired,
        direct_cleanup=DirectCleanupStage(value['direct_cleanup']) if value['schema']==3 else None)


def _key(operation, unit):
    if (not isinstance(operation, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", operation)
            or unit not in ("gamescope-session.service", "steam-launcher.service")):
        raise ValueError("invalid journal key")
    return hashlib.sha256((operation + "\0" + unit).encode()).hexdigest() + ".json"


class FilterJournal:
    def __init__(self, root=DEFAULT_ROOT, *, owner_uid=None, trusted_directory_fd=None):
        """Parents must exist. Fixtures require an explicit trusted directory FD.

        Production checks every ancestor's root ownership/write permissions.
        The caller retains the fixture FD for the journal's lifetime; every
        operation duplicates and validates it. owner_uid alone never relaxes
        production path checks.
        """
        self.root = Path(root)
        if not self.root.is_absolute() or any(part in (".", "..") for part in self.root.parts):
            raise ValueError("absolute journal directory required")
        if owner_uid is not None and (type(owner_uid) is not int or owner_uid < 0):
            raise ValueError("invalid fixture owner")
        if (owner_uid is None) != (trusted_directory_fd is None):
            raise ValueError("fixture requires explicit owner and trusted directory FD")
        if trusted_directory_fd is not None and (type(trusted_directory_fd) is not int or trusted_directory_fd < 0):
            raise ValueError("invalid trusted directory FD")
        self.owner_uid = 0 if owner_uid is None else owner_uid
        self.trusted_directory_fd = trusted_directory_fd

    def _secure(self, fd, *, directory=False):
        info = os.fstat(fd)
        valid_type = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
        if (not valid_type or info.st_uid != self.owner_uid or info.st_mode & 0o022
                or (not directory and (info.st_nlink != 1 or info.st_mode & 0o077))):
            raise ValueError("unsafe journal filesystem object")

    def _directory(self):
        if sys.platform != "linux" or os.geteuid() != self.owner_uid:
            raise ValueError("journal requires its Linux owner")
        if self.trusted_directory_fd is not None:
            fd = os.dup(self.trusted_directory_fd)
            try:
                self._secure(fd, directory=True)
                return fd
            except BaseException:
                os.close(fd)
                raise
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            self._secure(fd, directory=True)
            parts = self.root.parts[1:]
            for part in parts:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
                self._secure(fd, directory=True)
            return fd
        except BaseException:
            os.close(fd)
            raise

    @contextmanager
    def _locked(self):
        import fcntl
        directory = self._directory()
        lock = None
        try:
            lock = os.open("journal.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                           0o600, dir_fd=directory)
            self._secure(lock)
            _acquire_lock(lock, fcntl)
            yield directory
        finally:
            if lock is not None:
                os.close(lock)
            os.close(directory)

    def _read(self, directory, operation, unit):
        descriptor = os.open(_key(operation, unit), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=directory)
        try:
            self._secure(descriptor)
            raw = bytearray()
            while len(raw) <= MAX_BYTES:
                part = os.read(descriptor, MAX_BYTES + 1 - len(raw))
                if not part:
                    break
                raw.extend(part)
            record = decode_record(bytes(raw))
            if (record.lifecycle.binding.operation, record.lifecycle.binding.unit) != (operation, unit):
                raise ValueError("journal identity mismatch")
            return record
        finally:
            os.close(descriptor)

    def _write(self, directory, record, *, initial=False):
        target = _key(record.lifecycle.binding.operation, record.lifecycle.binding.unit)
        temporary = ".pending-" + uuid.uuid4().hex
        descriptor = None
        published = False
        try:
            try:
                descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                     0o600, dir_fd=directory)
                raw = encode_record(record)
                offset = 0
                while offset < len(raw):
                    written = os.write(descriptor, raw[offset:])
                    if written <= 0:
                        raise OSError("short journal write")
                    offset += written
                os.fsync(descriptor)
                os.close(descriptor)
                descriptor = None
                if initial:
                    # Atomic exclusive publication; a competing existing record is
                    # never replaced, including a symlink or malformed file.
                    _publish_exclusive(directory, temporary, target)
                    published = True
                else:
                    os.replace(temporary, target, src_dir_fd=directory, dst_dir_fd=directory)
                os.fsync(directory)
            finally:
                if descriptor is not None:
                    os.close(descriptor)
                try:
                    os.unlink(temporary, dir_fd=directory)
                except FileNotFoundError:
                    pass
        except BaseException as error:
            if initial and published:
                raise JournalInitialPublicationUncertain(record.lifecycle.binding) from error
            raise

    def create(self, binding):
        record = JournalRecord(1, FilterLifecycle(binding))
        published = False
        try:
            with self._locked() as directory:
                try:
                    self._write(directory, record, initial=True)
                    published = True
                except JournalInitialPublicationUncertain:
                    published = True
                    raise
        except BaseException as error:
            if published:
                if type(error) is JournalInitialPublicationUncertain and error.binding == binding:
                    raise
                raise JournalInitialPublicationUncertain(binding) from error
            raise
        return record

    @contextmanager
    def transaction(self):
        """Serialize a bounded trusted-controller operation, including pin I/O.

        Calls on the yielded view persist individually; exceptions do not roll
        back kernel operations or prior durable writes. Never hold this across
        a child wait. The view expires on exit and cannot be used by another
        thread. Normal public journal methods must not be nested inside it.
        """
        with self._locked() as directory:
            view = JournalTransaction(self, directory)
            try:
                yield view
            finally:
                view._expire()

    def _change(self, operation, unit, revision, action, **evidence):
        with self.transaction() as transaction:
            return transaction.change(operation, unit, revision, action, **evidence)

    def _change_locked(self, directory, operation, unit, revision, action, **evidence):
        if type(revision) is not int or revision < 1:
            raise ValueError("expected revision required")
        current = self._read(directory, operation, unit)
        if current.revision != revision:
            raise ValueError("stale journal revision")
        state = current.lifecycle
        paired=current.paired
        if action in ('direct_detached_verified','direct_cleanup_complete'):
            if evidence or not state.owned_detach_allowed or (paired is not None and paired.stage is not PairedStage.COMPLETE):
                raise ValueError('direct cleanup prerequisites unavailable')
            required=None if action=='direct_detached_verified' else DirectCleanupStage.DETACHED_VERIFIED
            if current.direct_cleanup is not required:raise ValueError('direct cleanup cannot replay or skip')
            stage=DirectCleanupStage.DETACHED_VERIFIED if action=='direct_detached_verified' else DirectCleanupStage.COMPLETE
            result=JournalRecord(revision+1,state,paired=paired,direct_cleanup=stage)
            self._write(directory,result)
            return result
        paired_actions={'retention_intent','retention_confirmed','receive_intent','receive_confirmed',
                        'receive_release_pending','receive_released','retention_release_pending','paired_complete'}
        if action in paired_actions:
            if action=='retention_intent':
                if paired is not None or state.phase is not Phase.REQUESTED or set(evidence)!={'map_id'}:
                    raise ValueError('retention intent cannot replay')
                paired=PairedOwnership(evidence['map_id'],PairedStage.RETENTION_INTENT)
            else:
                if paired is None:raise ValueError('paired ownership absent')
                if action in {'receive_release_pending','receive_released','retention_release_pending','paired_complete'}:
                    if state.phase is not Phase.CANCELLED:raise ValueError('paired release requires cancellation')
                elif state.phase is not Phase.REQUESTED:
                    raise ValueError('paired publication requires pending request')
                paired=paired.advance(action,**evidence)
            result=JournalRecord(revision+1,state,paired=paired)
            self._write(directory,result)
            return result
        if action=='grant' and paired is not None:
            raise ValueError('paired records cannot grant launch')
        if action == "prepare_pin":
            next_state = state.prepare_pin(**evidence)
        elif action == "attach":
            next_state = state.attach(**evidence)
        elif action == "grant":
            next_state = state.grant(**evidence)
        elif action == "cancel":
            next_state = state.cancel()
        elif action == "recover":
            next_state = state.after_crash()
        else:
            raise ValueError("unknown journal transition")
        if next_state == state:
            raise ValueError("terminal journal transition cannot replay")
        result = JournalRecord(revision + 1, next_state,
                               action == "grant" and next_state.phase is Phase.GRANTED,paired,current.direct_cleanup)
        self._write(directory, result)
        return result

    def prepare_pin(self, operation, unit, expected_revision, *, owned, observed, now):
        return self._change(operation, unit, expected_revision, "prepare_pin",
                            owned=owned, observed=observed, now=now)

    def attach(self, operation, unit, expected_revision, *, owned, observed, now):
        return self._change(operation, unit, expected_revision, "attach", owned=owned, observed=observed, now=now)

    def grant(self, operation, unit, expected_revision, *, observed, now, no_game,
              inherited_scan_complete, inherited_descriptors_free):
        return self._change(operation, unit, expected_revision, "grant", observed=observed, now=now,
            no_game=no_game, inherited_scan_complete=inherited_scan_complete,
            inherited_descriptors_free=inherited_descriptors_free)

    def cancel(self, operation, unit, expected_revision):
        return self._change(operation, unit, expected_revision, "cancel")

    def recover(self, operation, unit, expected_revision):
        return self._change(operation, unit, expected_revision, "recover")

    def read(self, operation, unit):
        """Observation only, including GRANTED; never authorizes redelivery."""
        with self._locked() as directory:
            return self._read(directory, operation, unit)


class JournalTransaction:
    """Internal controller view; no launch or kernel authority on its own."""

    def __init__(self, journal, directory):
        import threading
        self._journal = journal
        self._directory = directory
        self._thread = threading.get_ident()

    def _expire(self):
        self._directory = None

    def _check(self):
        import threading
        if self._directory is None or threading.get_ident() != self._thread:
            raise ValueError("journal transaction unavailable")

    def read(self, operation, unit):
        self._check()
        return self._journal._read(self._directory, operation, unit)

    def create(self, binding):
        self._check()
        record = JournalRecord(1, FilterLifecycle(binding))
        self._journal._write(self._directory, record, initial=True)
        return record

    def change(self, operation, unit, revision, action, **evidence):
        self._check()
        return self._journal._change_locked(self._directory, operation, unit,
                                            revision, action, **evidence)
