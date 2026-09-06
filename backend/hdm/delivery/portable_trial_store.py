"""Durable one-shot launch intent; consumed records deliberately remain blocked."""
from __future__ import annotations

import json
import math
import os
import re
import stat
from pathlib import Path

from .gamescope_wrapper import (
    CONNECTOR_RE, SHA256_RE, VENDOR_DEVICE_RE, GamescopeLaunchConfig,
    config_from_dict, config_to_dict,
)

_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_FIELDS = frozenset(("schema_version", "operation_id", "boot_id_sha256", "generation",
                     "internal_gpu", "internal_connector", "egpu_binding_sha256",
                     "original_config", "expected_config", "expires_at"))
_MAX_BYTES = 16384
_INVOCATION = re.compile(r"^[0-9a-f]{32}$")


class PortableTrialStore:
    def __init__(self, root: Path):
        if not root.is_absolute():
            raise ValueError("trial root must be absolute")
        self._root = root
        self._record = root / "portable-vulkan-trial.json"
        self._consumed = root / "portable-vulkan-trial.consumed"
        self._steam_consumed = root / "portable-vulkan-trial.steam-consumed"
        self._receipt = root / "portable-vulkan-trial.gamescope-launch"

    def _validate_root(self):
        if self._root.is_symlink() or not self._root.is_dir():
            raise ValueError("trial root must be a real directory")

    @staticmethod
    def _validate(value):
        if not isinstance(value, dict) or set(value) != _FIELDS:
            raise ValueError("invalid trial record shape")
        if type(value["schema_version"]) is not int or value["schema_version"] != 1:
            raise ValueError("invalid trial schema")
        for key, pattern in (("operation_id", _IDENTIFIER), ("generation", _IDENTIFIER),
                             ("boot_id_sha256", SHA256_RE), ("egpu_binding_sha256", SHA256_RE),
                             ("internal_gpu", VENDOR_DEVICE_RE), ("internal_connector", CONNECTOR_RE)):
            if not isinstance(value[key], str) or not pattern.fullmatch(value[key]):
                raise ValueError("invalid trial identity")
        expiry = value["expires_at"]
        if type(expiry) not in (int, float) or not math.isfinite(expiry) or expiry <= 0:
            raise ValueError("invalid trial expiry")
        if not isinstance(value["expected_config"], dict) or (value["original_config"] is not None and not isinstance(value["original_config"], dict)):
            raise ValueError("invalid trial configuration")
        expected = config_from_dict(value["expected_config"])
        if expected.target != "portable" or expected.boot_id_sha256 != value["boot_id_sha256"] or expected.internal_connector != value["internal_connector"]:
            raise ValueError("trial config identity mismatch")
        if value["original_config"] is not None:
            config_from_dict(value["original_config"])
        return value

    def _sync_directory(self):
        if os.name != "posix":
            return
        descriptor = os.open(self._root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _exclusive_write(self, path, data, *, mode):
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), mode)
        with os.fdopen(descriptor, "wb") as output:
            if os.name == "posix":
                os.fchmod(output.fileno(), mode)
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        self._sync_directory()

    def arm(self, *, operation_id: str, boot_id_sha256: str, generation: str,
            internal_gpu: str, internal_connector: str, egpu_binding_sha256: str,
            original_config: GamescopeLaunchConfig | None,
            expected_config: GamescopeLaunchConfig, expires_at: float):
        self._validate_root()
        value = self._validate(dict(schema_version=1, operation_id=operation_id,
            boot_id_sha256=boot_id_sha256, generation=generation, internal_gpu=internal_gpu,
            internal_connector=internal_connector, egpu_binding_sha256=egpu_binding_sha256,
            original_config=config_to_dict(original_config) if original_config is not None else None,
            expected_config=config_to_dict(expected_config), expires_at=expires_at))
        if any(path.exists() or path.is_symlink() for path in
               (self._consumed, self._steam_consumed, self._receipt)):
            raise ValueError("trial reconciliation required")
        data = json.dumps(value, allow_nan=False, separators=(",", ":")).encode("utf-8")
        if len(data) > _MAX_BYTES:
            raise ValueError("trial record too large")
        # Root stages this sanitized record; the session-user wrapper reads it.
        self._exclusive_write(self._record, data, mode=0o644)

    def read(self) -> dict | None:
        self._validate_root()
        if self._record.is_symlink():
            raise ValueError("trial record cannot be a symlink")
        try:
            descriptor = os.open(self._record, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        except FileNotFoundError:
            return None
        with os.fdopen(descriptor, "rb") as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise ValueError("trial record must be a regular file")
            data = source.read(_MAX_BYTES + 1)
        if len(data) > _MAX_BYTES:
            raise ValueError("trial record too large")
        def unique_object(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate trial field")
                result[key] = value
            return result
        return self._validate(json.loads(data, object_pairs_hook=unique_object))

    def consume(self) -> dict | None:
        value = self.read()
        if value is None:
            return None
        try:
            self._exclusive_write(self._consumed, value["operation_id"].encode("ascii"), mode=0o600)
        except FileExistsError:
            return None
        return value

    def cancel(self, operation_id: str) -> None:
        value = self.read()
        if value is None or value["operation_id"] != operation_id:
            raise ValueError("trial operation mismatch")
        # Burn Steam first. A later Gamescope receipt cannot revive authority.
        self._claim_steam(operation_id)
        self.consume()

    def _claim_steam(self, operation_id):
        try:
            self._exclusive_write(self._steam_consumed, operation_id.encode('ascii'), mode=0o600)
        except FileExistsError:
            return False
        return True

    def _read_small_file(self, path):
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
                             | getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(descriptor, 'rb') as source:
            if path.is_symlink() or not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise ValueError('trial receipt must be a regular file')
            value = source.read(513)
        if len(value) > 512:
            raise ValueError('trial receipt exceeds bound')
        return value.decode('ascii')

    def publish_gamescope_launch(self, operation_id, invocation_id):
        """Receipt means validated launch attempt, never exec or release success."""
        self._validate_root()
        value = self.read()
        if (value is None or value['operation_id'] != operation_id
                or not _INVOCATION.fullmatch(invocation_id)
                or self._read_small_file(self._consumed) != operation_id):
            raise ValueError('trial launch receipt identity mismatch')
        self._exclusive_write(self._receipt,
            f'{operation_id}\n{invocation_id}'.encode('ascii'), mode=0o600)

    def consume_steam(self):
        """Burn before receipt or live validation; cancellation competes here."""
        value = self.read()
        if value is None or not self._claim_steam(value['operation_id']):
            return None
        if self._read_small_file(self._consumed) != value['operation_id']:
            raise ValueError('Gamescope trial was not consumed')
        parts = self._read_small_file(self._receipt).split('\n')
        if (len(parts) != 2 or parts[0] != value['operation_id']
                or not _INVOCATION.fullmatch(parts[1])):
            raise ValueError('invalid Gamescope launch receipt')
        return value, parts[1]

    def restore_original(self, config_store, operation_id):
        value = self.read()
        if value is None or value["operation_id"] != operation_id:
            raise ValueError("trial operation mismatch")
        expected = config_from_dict(value["expected_config"])
        original = config_from_dict(value["original_config"]) if value["original_config"] is not None else None
        current = config_store.load()
        if current != expected and current != original:
            raise ValueError("presentation config changed outside trial")
        self.cancel(operation_id)
        config_store.restore(original)
