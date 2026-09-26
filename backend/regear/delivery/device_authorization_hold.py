"""Durable remembered-trust hold for a software-disconnected USB4 dock.

The record contains an internal boltd UUID and therefore never crosses an RPC,
diagnostic or log boundary.  It is kept in the existing private root-owned
runtime directory and serialized with the whole-dock claim lock.
"""
from dataclasses import asdict, dataclass, replace
import json
import os
import re
import secrets

from .whole_dock_claim import MAX_BYTES, TOKEN, WholeDockClaim, WholeDockClaimStore


FILENAME = "device-authorization-hold.json"
UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)


@dataclass(frozen=True, slots=True)
class DeviceAuthorizationHold:
    operation: str
    binding: str
    generation: str
    uuid: str
    state: str = "prepared"

    def __post_init__(self):
        if any(type(value) is not str or TOKEN.fullmatch(value) is None
               for value in (self.operation, self.binding, self.generation)):
            raise ValueError("device_authorization_hold.identity_invalid")
        if type(self.uuid) is not str or UUID.fullmatch(self.uuid) is None:
            raise ValueError("device_authorization_hold.uuid_invalid")
        if self.state not in ("prepared", "manual"):
            raise ValueError("device_authorization_hold.state_invalid")


class DeviceAuthorizationHoldStore(WholeDockClaimStore):
    """Store one exact auto-to-manual policy hold beside its dock claim."""

    @staticmethod
    def _encode_hold(hold):
        return (
            json.dumps(
                {"schema_version": 1, **asdict(hold)},
                sort_keys=True,
                separators=(",", ":"),
            ) + "\n"
        ).encode("ascii")

    @classmethod
    def _decode_hold(cls, data):
        if len(data) > MAX_BYTES:
            raise ValueError("device_authorization_hold.too_large")
        value = json.loads(data.decode("ascii"), object_pairs_hook=cls._pairs)
        fields = set(DeviceAuthorizationHold.__dataclass_fields__)
        if (type(value) is not dict or set(value) != fields | {"schema_version"}
                or type(value["schema_version"]) is not int
                or value["schema_version"] != 1):
            raise ValueError("device_authorization_hold.schema_invalid")
        return DeviceAuthorizationHold(**{name: value[name] for name in fields})

    def _load_hold(self, directory):
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
        return self._decode_hold(data)

    def load_hold(self):
        with self._locked() as directory:
            return self._load_hold(directory)

    def _write_hold(self, descriptor, hold):
        self._secure(descriptor)
        data = self._encode_hold(hold)
        while data:
            count = os.write(descriptor, data)
            if count <= 0:
                raise OSError("device_authorization_hold.write_stalled")
            data = data[count:]
        os.fsync(descriptor)

    def prepare(self, operation, binding, generation, uuid, guard):
        hold = DeviceAuthorizationHold(operation, binding, generation, uuid)
        expected_claim = WholeDockClaim(operation, binding, generation,
                                        "tunnel_remove_intent")
        with self._locked() as directory:
            if self._load(directory) != expected_claim or guard() is not True:
                return None
            if self._load(directory) != expected_claim:
                return None
            existing = self._load_hold(directory)
            if existing is not None:
                return existing if existing == hold else None
            descriptor = os.open(FILENAME, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                                 os.O_NOFOLLOW, 0o600, dir_fd=directory)
            try:
                self._write_hold(descriptor, hold)
            finally:
                os.close(descriptor)
            os.fsync(directory)
            return hold

    def mark_manual(self, expected, guard):
        if type(expected) is not DeviceAuthorizationHold:
            return None
        expected_claim = WholeDockClaim(expected.operation, expected.binding,
                                        expected.generation, "tunnel_remove_intent")
        with self._locked() as directory:
            current = self._load_hold(directory)
            if (current != expected or self._load(directory) != expected_claim
                    or guard() is not True or self._load_hold(directory) != expected):
                return None
            if current.state == "manual":
                return current
            updated = replace(current, state="manual")
            temporary = ".device-authorization-hold-" + secrets.token_hex(16) + ".tmp"
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                                 os.O_NOFOLLOW, 0o600, dir_fd=directory)
            try:
                try:
                    self._write_hold(descriptor, updated)
                finally:
                    os.close(descriptor)
                os.replace(temporary, FILENAME, src_dir_fd=directory,
                           dst_dir_fd=directory)
                os.fsync(directory)
            finally:
                try:
                    os.unlink(temporary, dir_fd=directory)
                except FileNotFoundError:
                    pass
            return updated

    def clear_after_absence(self, expected, guard):
        if type(expected) is not DeviceAuthorizationHold:
            return False
        with self._locked() as directory:
            if self._load_hold(directory) != expected or guard() is not True:
                return False
            if self._load_hold(directory) != expected:
                return False
            os.unlink(FILENAME, dir_fd=directory)
            os.fsync(directory)
            return True
