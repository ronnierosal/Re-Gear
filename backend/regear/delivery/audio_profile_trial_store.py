"""Bounded durable audio trial journal; no profile changes or record removal.

Transactions serialize all operations. A failed publication may have committed;
callers must reread in a fresh transaction before deciding recovery, never retry
blindly. Terminal records -- restored, or abandoned with their boot -- remain as
operation replay tombstones.
"""
from contextlib import contextmanager
from dataclasses import asdict, fields
import hashlib
import json
import os
import re
import threading
import uuid

from .audio_profile_trial_state import AudioTrialRecord, AudioTrialPhase, TERMINAL_PHASES
from .audio_journal_filesystem import AudioJournalFilesystem, _publish_exclusive

ROOT = "/var/lib/regear/audio-profile-trial"
MAX_BYTES = 4096
MAX_RECORDS = 256
# Every non-terminal phase may reach ABANDONED: a reboot can interrupt a trial
# at any step, and the record it leaves behind is finished wherever it stopped.
# Neither terminal phase leads anywhere -- a retired record is not resumable,
# and abandoning a restored one would lose the fact that it was restored.
_TRANSITIONS = {
    AudioTrialPhase.PREPARED: {AudioTrialPhase.OFF_REQUESTED, AudioTrialPhase.RESTORE_REQUESTED,
                             AudioTrialPhase.RESTORED, AudioTrialPhase.RECOVERY_REQUIRED,
                             AudioTrialPhase.ABANDONED},
    AudioTrialPhase.OFF_REQUESTED: {AudioTrialPhase.OFF_OBSERVED, AudioTrialPhase.RESTORE_REQUESTED,
                                  AudioTrialPhase.RESTORED, AudioTrialPhase.RECOVERY_REQUIRED,
                                  AudioTrialPhase.ABANDONED},
    AudioTrialPhase.OFF_OBSERVED: {AudioTrialPhase.RESTORE_REQUESTED, AudioTrialPhase.RESTORED,
                                 AudioTrialPhase.RECOVERY_REQUIRED, AudioTrialPhase.ABANDONED},
    AudioTrialPhase.RESTORE_REQUESTED: {AudioTrialPhase.RESTORE_REQUESTED, AudioTrialPhase.RESTORED,
                                      AudioTrialPhase.RECOVERY_REQUIRED, AudioTrialPhase.ABANDONED},
    AudioTrialPhase.RECOVERY_REQUIRED: {AudioTrialPhase.RESTORE_REQUESTED, AudioTrialPhase.RESTORED,
                                      AudioTrialPhase.ABANDONED},
    AudioTrialPhase.RESTORED: set(),
    AudioTrialPhase.ABANDONED: set(),
}


def _key(operation):
    if type(operation) is not str or re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", operation) is None:
        raise ValueError("invalid audio operation")
    return hashlib.sha256(operation.encode("ascii")).hexdigest() + ".json"


def encode_record(record):
    if type(record) is not AudioTrialRecord:
        raise ValueError("typed audio record required")
    record = AudioTrialRecord(**asdict(record))
    value = {"schema": 1, **asdict(record), "phase": record.phase.value}
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii")
    if len(raw) > MAX_BYTES:
        raise ValueError("audio record too large")
    return raw


def decode_record(raw):
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_BYTES:
        raise ValueError("invalid audio record size")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate audio record key")
            result[key] = value
        return result
    def constant(_):
        raise ValueError("nonfinite audio record")
    try:
        value = json.loads(raw.decode("ascii"), object_pairs_hook=pairs, parse_constant=constant)
        if (type(value) is not dict or set(value) != {"schema", *(f.name for f in fields(AudioTrialRecord))}
                or type(value["schema"]) is not int or value.pop("schema") != 1
                or type(value["phase"]) is not str):
            raise ValueError("invalid audio record schema")
        value["phase"] = AudioTrialPhase(value["phase"])
        return AudioTrialRecord(**value)
    except (UnicodeError, RecursionError) as error:
        raise ValueError("invalid audio record encoding") from error


class AudioTrialStore:
    """Reuse audited directory/lock checks, with a fixed independent root."""
    def __init__(self, *, owner_uid=None, trusted_directory_fd=None):
        self._filesystem = AudioJournalFilesystem(ROOT, owner_uid=owner_uid, trusted_directory_fd=trusted_directory_fd)

    def _locked(self):
        return self._filesystem._locked()

    def _secure(self, fd):
        self._filesystem._secure(fd)

    @contextmanager
    def transaction(self):
        with self._locked() as directory:
            tx = AudioTrialTransaction(self, directory)
            try:
                yield tx
            finally:
                tx.directory = None

    def _audio_read(self, directory, name):
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            self._secure(descriptor)
            raw = bytearray()
            while len(raw) <= MAX_BYTES:
                part = os.read(descriptor, MAX_BYTES + 1 - len(raw))
                if not part:
                    break
                raw.extend(part)
            record = decode_record(bytes(raw))
            if _key(record.operation) != name:
                raise ValueError("audio record filename mismatch")
            return record
        finally:
            os.close(descriptor)

    def _audio_write(self, directory, record, *, initial):
        raw = encode_record(record)
        temporary = ".pending-" + uuid.uuid4().hex
        descriptor = None
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=directory)
            position = 0
            while position < len(raw):
                count = os.write(descriptor, raw[position:])
                if count <= 0:
                    raise OSError("short audio journal write")
                position += count
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = None
            if initial:
                _publish_exclusive(directory, temporary, _key(record.operation))
            else:
                os.replace(temporary, _key(record.operation), src_dir_fd=directory, dst_dir_fd=directory)
            os.fsync(directory)
        finally:
            if descriptor is not None:
                os.close(descriptor)
            try:
                os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass


class AudioTrialTransaction:
    def __init__(self, store, directory):
        self.store, self.directory, self.thread = store, directory, threading.get_ident()

    def _check(self):
        if self.directory is None or self.thread != threading.get_ident():
            raise ValueError("audio transaction unavailable")

    def read(self, operation):
        self._check()
        return self.store._audio_read(self.directory, _key(operation))

    def _records(self):
        self._check()
        records = []
        count = 0
        entries_seen = 0
        with os.scandir(self.directory) as entries:
            for entry in entries:
                if entry.name == "journal.lock":
                    continue
                entries_seen += 1
                if entries_seen > MAX_RECORDS * 2:
                    raise ValueError("audio journal entry limit reached")
                if re.fullmatch(r"\.pending-[0-9a-f]{32}", entry.name):
                    # A crash before rename can leave an incomplete temporary
                    # file. It never authorized a command. Preserve it without
                    # treating it as an active record, under the global lock.
                    fd = os.open(entry.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                 dir_fd=self.directory)
                    try:
                        self.store._secure(fd)
                    finally:
                        os.close(fd)
                    continue
                count += 1
                if count > MAX_RECORDS or re.fullmatch(r"[0-9a-f]{64}\.json", entry.name) is None:
                    raise ValueError("audio journal enumeration unavailable")
                records.append(self.store._audio_read(self.directory, entry.name))
        return tuple(records)

    def pending(self):
        """Read-only recovery evidence; multiple active records fail closed."""
        active = tuple(record for record in self._records() if record.phase not in TERMINAL_PHASES)
        if len(active) > 1:
            raise ValueError("multiple active audio trials")
        return active[0] if active else None

    def create(self, record):
        self._check()
        encode_record(record)
        if record.revision != 1 or record.phase is not AudioTrialPhase.PREPARED:
            raise ValueError("initial prepared audio record required")
        records = self._records()
        if any(existing.phase not in TERMINAL_PHASES or existing.operation == record.operation
               for existing in records):
            raise ValueError("audio trial active or operation already consumed")
        if len(records) >= MAX_RECORDS:
            raise ValueError("audio record limit reached")
        self.store._audio_write(self.directory, record, initial=True)
        return record

    def save(self, expected_record, new_record):
        self._check()
        encode_record(expected_record)
        encode_record(new_record)
        identity = tuple(f.name for f in fields(AudioTrialRecord) if f.name not in ("phase", "revision"))
        if (new_record.phase not in _TRANSITIONS[expected_record.phase]
                or new_record.revision != expected_record.revision + 1
                or any(getattr(expected_record, key) != getattr(new_record, key) for key in identity)
                or self.read(expected_record.operation) != expected_record):
            raise ValueError("audio journal CAS or identity mismatch")
        self.store._audio_write(self.directory, new_record, initial=False)
        return new_record
