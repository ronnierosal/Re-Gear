"""One-shot power intents; no hardware operations or claim retirement.

Each operation retains its own consumed record. A new backend session cannot
resume an old request: callers must supply their freshly generated session
token, never recover it from this store. Retention cleanup is deliberately
outside this writer; old operations do not block unrelated new operations.
"""
from dataclasses import asdict, dataclass, replace
import json
import math
import os
import re
import secrets

from .whole_dock_claim import WholeDockClaim, WholeDockClaimStore, TOKEN, MAX_BYTES
from .audio_journal_filesystem import _publish_exclusive


@dataclass(frozen=True)
class DockPowerIntent:
    operation: str
    binding: str
    generation: str
    action: str
    session: str
    requested_at: float
    deadline: float
    consumed: bool = False

    def __post_init__(self):
        if (type(self.operation) is not str
                or re.fullmatch('[0-9a-f]{32}', self.operation) is None
                or any(type(v) is not str or not TOKEN.fullmatch(v)
                       for v in (self.binding, self.generation, self.session))
                or type(self.action) is not str or self.action not in ('sleep', 'shutdown')
                or type(self.consumed) is not bool
                or any(type(v) not in (int, float) or not math.isfinite(v)
                       for v in (self.requested_at, self.deadline))
                or self.requested_at < 0
                or not 0 < self.deadline - self.requested_at <= 300):
            raise ValueError('dock_power.invalid_intent')


class DockPowerIntentStore(WholeDockClaimStore):
    """Sibling records serialized with the existing secure whole-dock lock.

    bind/consume return False for a mismatched claim or existing/consumed intent.
    Invalid or unsafe storage raises; the caller must refuse power submission.
    Bounds are validated here; a live monotonic deadline check remains the
    coordinator's responsibility, immediately before and after consumption.
    A failure before replacement can leave the original unconsumed record.
    No power submission may follow that failure, and callers must not rebuild
    the same session's coordinator to retry an unresolved request. A replaced
    consumed record refuses replay even if directory fsync subsequently fails.
    """

    @staticmethod
    def _filename(intent):
        return 'dock-power-' + intent.operation + '.json'

    @staticmethod
    def _encode_intent(intent):
        return (json.dumps({'schema_version': 1, **asdict(intent)},
                           sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode('ascii')

    @classmethod
    def _decode_intent(cls, data):
        if len(data) > MAX_BYTES:
            raise ValueError('dock_power.intent_too_large')
        value = json.loads(data.decode('ascii'), object_pairs_hook=cls._pairs)
        fields = set(DockPowerIntent.__dataclass_fields__)
        if (type(value) is not dict or set(value) != fields | {'schema_version'}
                or type(value['schema_version']) is not int or value['schema_version'] != 1):
            raise ValueError('dock_power.invalid_schema')
        return DockPowerIntent(**{k: value[k] for k in fields})

    def _load_intent(self, directory, intent):
        try:
            fd = os.open(self._filename(intent), os.O_RDONLY | os.O_NOFOLLOW |
                         os.O_NONBLOCK, dir_fd=directory)
        except FileNotFoundError:
            return None
        try:
            self._secure(fd)
            data = b''
            while len(data) <= MAX_BYTES:
                chunk = os.read(fd, MAX_BYTES + 1 - len(data))
                if not chunk:
                    break
                data += chunk
        finally:
            os.close(fd)
        return self._decode_intent(data)

    def _write_intent(self, fd, intent):
        self._secure(fd)
        data = self._encode_intent(intent)
        while data:
            count = os.write(fd, data)
            if count <= 0:
                raise OSError('dock_power.write_stalled')
            data = data[count:]
        os.fsync(fd)

    def bind(self, operation, binding, generation, action, session, requested_at, deadline):
        intent = DockPowerIntent(operation, binding, generation, action, session, requested_at, deadline)
        with self._locked() as directory:
            if self._load(directory) != WholeDockClaim(operation, binding, generation, 'claimed'):
                return False
            try:
                fd = os.open(self._filename(intent), os.O_WRONLY | os.O_CREAT |
                             os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            except FileExistsError:
                return False
            # A failed partial creation intentionally blocks this operation.
            try:
                self._write_intent(fd, intent)
            finally:
                os.close(fd)
            os.fsync(directory)
            return True

    def consume(self, operation, binding, generation, action, session, requested_at, deadline):
        expected = DockPowerIntent(operation, binding, generation, action, session, requested_at, deadline)
        with self._locked() as directory:
            if self._load(directory) != WholeDockClaim(operation, binding, generation, 'software_down'):
                return False
            if self._load_intent(directory, expected) != expected:
                return False
            temporary = '.dock-power-' + secrets.token_hex(16) + '.tmp'
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                         os.O_NOFOLLOW, 0o600, dir_fd=directory)
            try:
                try:
                    self._write_intent(fd, replace(expected, consumed=True))
                finally:
                    os.close(fd)
                os.replace(temporary, self._filename(expected),
                           src_dir_fd=directory, dst_dir_fd=directory)
                os.fsync(directory)
            finally:
                try:
                    os.unlink(temporary, dir_fd=directory)
                except FileNotFoundError:
                    pass
            return True

    def retire_after_boot(self, expected_claim, current_boot_hash, guard):
        """Archive a verified completed shutdown from an earlier boot only.

        Caller holds dock mutation admission. Its fresh guard must establish
        attachment/host identity, settled helper work, no inner claims and idle
        state. A consumed intent means submission was attempted, not that the
        power request succeeded; the changed boot plus guard provide the extra
        evidence needed to retire its retained inhibition. Never handles sleep.
        """
        if (type(expected_claim) is not WholeDockClaim
                or expected_claim.stage != 'software_down'
                or type(current_boot_hash) is not str
                or re.fullmatch('[0-9a-f]{64}', current_boot_hash) is None
                or re.fullmatch('[0-9a-f]{32}', expected_claim.operation) is None):
            return False
        with self._locked() as directory:
            if self._load(directory) != expected_claim:
                return False
            # Filename lookup needs only the already-validated operation.
            intent = self._load_intent(directory, expected_claim)
            if (intent is None or not intent.consumed or intent.action != 'shutdown'
                    or (intent.operation, intent.binding, intent.generation) !=
                    (expected_claim.operation, expected_claim.binding, expected_claim.generation)
                    or re.fullmatch('[0-9a-f]{64}:[0-9a-f]{32}', intent.session) is None
                    or intent.session.split(':', 1)[0] == current_boot_hash):
                return False
            if guard() is not True or self._load(directory) != expected_claim:
                return False
            if self._load_intent(directory, expected_claim) != intent:
                return False
            audit = 'power-completed-whole-dock-' + secrets.token_hex(16) + '.json'
            from .whole_dock_claim import FILENAME
            _publish_exclusive(directory, FILENAME, audit)
            try:
                os.fsync(directory)
            except OSError as failure:
                try:
                    _publish_exclusive(directory, audit, FILENAME)
                    os.fsync(directory)
                except OSError as restore_failure:
                    raise OSError('dock_power.retirement_durability_unresolved') from restore_failure
                raise failure
            return True
