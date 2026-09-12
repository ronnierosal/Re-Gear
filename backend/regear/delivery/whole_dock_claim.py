"""Durable whole-dock inhibition. No operation here grants unplug clearance."""
from contextlib import contextmanager
from dataclasses import dataclass, asdict
import json
import os
import re
import secrets
import stat

from .audio_journal_filesystem import AudioJournalFilesystem, _acquire_lock, _publish_exclusive

FILENAME = "whole-dock-claim.json"
MAX_BYTES = 4096
STAGES = ("claimed", "release_intent", "gpu_removed", "prepared", "usb_remove_intent", "usb_removed",
          "tunnel_remove_intent", "software_down", "reauthorize_intent",
          "software_reconnected")
TOKEN = re.compile(r"[A-Za-z0-9_.:-]{1,256}\Z")


@dataclass(frozen=True)
class WholeDockClaim:
    operation: str
    binding: str
    generation: str
    stage: str = "claimed"

    def __post_init__(self):
        for value in (self.operation, self.binding, self.generation):
            if type(value) is not str or not TOKEN.fullmatch(value):
                raise ValueError("invalid whole-dock identity")
        if self.stage not in STAGES:
            raise ValueError("invalid whole-dock stage")


class WholeDockClaimStore(AudioJournalFilesystem):
    """Fixed-path claim, retained on partial writes, failures and completion.

    Root must already exist. Production validates every ancestor. Tests may use
    the same explicit trusted-directory-FD fixture boundary as audio journals.
    """

    @contextmanager
    def _locked(self):
        import fcntl
        directory = self._directory()
        lock = None
        try:
            if stat.S_IMODE(os.fstat(directory).st_mode) != 0o700:
                raise ValueError("whole-dock directory must be private")
            lock = os.open("whole-dock-claim.lock", os.O_RDWR | os.O_CREAT |
                           os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=directory)
            self._secure(lock)
            _acquire_lock(lock, fcntl)
            yield directory
        finally:
            if lock is not None:
                os.close(lock)
            os.close(directory)

    @staticmethod
    def _encode(claim):
        return (json.dumps({"schema_version": 1, **asdict(claim)},
                           separators=(",", ":"), sort_keys=True) + "\n").encode("ascii")

    @staticmethod
    def _pairs(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate whole-dock field")
            value[key] = item
        return value

    def _load(self, directory):
        try:
            descriptor = os.open(FILENAME, os.O_RDONLY | os.O_NOFOLLOW |
                                 os.O_NONBLOCK, dir_fd=directory)
        except FileNotFoundError:
            return None
        try:
            self._secure(descriptor)
            data = b""
            while len(data) <= MAX_BYTES:
                chunk = os.read(descriptor, MAX_BYTES + 1 - len(data))
                if not chunk:
                    break
                data += chunk
        finally:
            os.close(descriptor)
        if len(data) > MAX_BYTES:
            raise ValueError("whole-dock claim too large")
        value = json.loads(data.decode("ascii"), object_pairs_hook=self._pairs)
        if (type(value) is not dict or set(value) !=
                {"schema_version", "operation", "binding", "generation", "stage"}
                or type(value["schema_version"]) is not int or value["schema_version"] != 1):
            raise ValueError("invalid whole-dock schema")
        return WholeDockClaim(**{k: v for k, v in value.items() if k != "schema_version"})

    def load(self):
        with self._locked() as directory:
            return self._load(directory)

    def inhibited(self):
        try:
            return self.load() is not None
        except Exception:
            return True

    def _write(self, descriptor, claim):
        self._secure(descriptor)
        data = self._encode(claim)
        while data:
            count = os.write(descriptor, data)
            if count <= 0:
                raise OSError("whole-dock write did not advance")
            data = data[count:]
        os.fsync(descriptor)

    def claim(self, operation, binding, generation):
        claim = WholeDockClaim(operation, binding, generation)
        with self._locked() as directory:
            try:
                descriptor = os.open(FILENAME, os.O_WRONLY | os.O_CREAT |
                                     os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            except FileExistsError:
                return False
            try:
                self._write(descriptor, claim)
            finally:
                os.close(descriptor)
            # Never delete a claim after failure: even truncated data inhibits.
            os.fsync(directory)
            return True

    def record(self, operation, stage):
        with self._locked() as directory:
            current = self._load(directory)
            if current is None or current.operation != operation:
                raise ValueError("whole-dock claim owner mismatch")
            updated = WholeDockClaim(current.operation, current.binding, current.generation, stage)
            if STAGES.index(stage) < STAGES.index(current.stage):
                raise ValueError("whole-dock stage cannot regress")
            temporary = ".whole-dock-" + secrets.token_hex(16) + ".tmp"
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                                 os.O_NOFOLLOW, 0o600, dir_fd=directory)
            try:
                try:
                    self._write(descriptor, updated)
                finally:
                    os.close(descriptor)
                os.replace(temporary, FILENAME, src_dir_fd=directory, dst_dir_fd=directory)
                os.fsync(directory)
            finally:
                try:
                    os.unlink(temporary, dir_fd=directory)
                except FileNotFoundError:
                    pass

    def retire_reconnected(self, operation, binding, generation, guard):
        """Archive only an exactly verified software-reconnected transaction.

        Caller holds mutation admission and supplies fresh topology/idle checks.
        If directory fsync fails, restore inhibition before propagating failure.
        If restoration also fails, the completed audit may remain without an
        active claim: caller must retain admission/fail closed pending recovery.
        A successful return is the audit filename, never unplug clearance.
        """
        expected = WholeDockClaim(operation, binding, generation, "software_reconnected")
        with self._locked() as directory:
            if self._load(directory) != expected:
                raise ValueError("whole-dock reconnect claim mismatch")
            if guard() is not True:
                raise ValueError("whole-dock reconnect guard refused")
            if self._load(directory) != expected:
                raise ValueError("whole-dock reconnect claim changed")
            audit = "completed-whole-dock-" + secrets.token_hex(16) + ".json"
            # Atomic no-replace publication preserves any previous audit, even
            # if a token collision or unexpected pre-existing path occurs.
            _publish_exclusive(directory, FILENAME, audit)
            try:
                os.fsync(directory)
            except OSError as failure:
                try:
                    _publish_exclusive(directory, audit, FILENAME)
                    os.fsync(directory)
                except OSError as restore_failure:
                    raise OSError("whole-dock retirement durability and restoration unresolved") from restore_failure
                raise failure
            return audit

    def retire_abandoned(self, expected, guard):
        """Archive a verified early abort; caller holds dock mutation admission.

        Stage alone is insufficient: guard must establish attached operation and
        absence of outstanding inner removal, filter and held-session work.
        """
        if type(expected) is not WholeDockClaim or expected.stage not in ('claimed', 'release_intent'):
            raise ValueError('whole-dock abort stage refused')
        with self._locked() as directory:
            if self._load(directory) != expected or guard() is not True:
                raise ValueError('whole-dock abort guard refused')
            if self._load(directory) != expected:
                raise ValueError('whole-dock abort changed')
            audit = 'aborted-whole-dock-' + secrets.token_hex(16) + '.json'
            _publish_exclusive(directory, FILENAME, audit)
            try:
                os.fsync(directory)
            except OSError as failure:
                try:
                    _publish_exclusive(directory, audit, FILENAME)
                    os.fsync(directory)
                except OSError as restore_failure:
                    raise OSError('whole-dock abort durability unresolved') from restore_failure
                raise failure
            return audit


def inner_removal_records_absent(filesystem=None):
    """Read only fixed root-owned records; absent is different from unreadable."""
    from pathlib import Path
    filesystem = filesystem or AudioJournalFilesystem(Path('/var/lib/regear/egpu'))
    try:
        directory = filesystem._directory()
    except FileNotFoundError:
        return True
    try:
        for name in ('removal-transaction.json', 'filter-ownership.json'):
            try:
                os.stat(name, dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError:
                continue
            return False
        return True
    finally:
        os.close(directory)
