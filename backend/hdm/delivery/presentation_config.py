"""Atomic fixed-path writer for the boot-scoped Gamescope launch config."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import threading
from pathlib import Path

from ..domain.control_plane import PlacementState, TransitionBinding
from ..domain.models import ObservedSnapshot
from .gamescope_wrapper import (
    CONFIG_FILENAME,
    MAX_CONFIG_BYTES,
    GamescopeLaunchConfig,
    config_from_dict,
    config_to_dict,
)


BOOT_ID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
CONFIG_FILE_MODE = 0o644


class PresentationConfigStore:
    def __init__(self, state_root: Path) -> None:
        if not state_root.is_absolute():
            raise ValueError("presentation state root must be absolute")
        self._root = state_root
        self._target = state_root / CONFIG_FILENAME
        self._lock = threading.Lock()

    def load(self) -> GamescopeLaunchConfig | None:
        self._validate_root()
        with self._lock:
            if self._target.is_symlink():
                raise ValueError("presentation config cannot be a symlink")
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            try:
                descriptor = os.open(self._target, flags)
            except FileNotFoundError:
                return None
            with os.fdopen(descriptor, "rb") as source:
                data = source.read(MAX_CONFIG_BYTES + 1)
        if len(data) > MAX_CONFIG_BYTES:
            raise ValueError("presentation config exceeds its bound")
        value = json.loads(data.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("presentation config root must be an object")
        return config_from_dict(value)

    def restore(self, value: GamescopeLaunchConfig | None) -> None:
        """Restore an exact captured launch policy, including an absent file."""
        self._validate_root()
        with self._lock:
            if self._target.is_symlink():
                raise ValueError("presentation config cannot be a symlink")
            if value is None:
                self._target.unlink(missing_ok=True)
                self._sync_directory()
            elif isinstance(value, GamescopeLaunchConfig):
                self._save(value)
            else:
                raise ValueError("invalid original launch config")

    def write_target(
        self, *, target: PlacementState, binding: TransitionBinding,
        snapshot: ObservedSnapshot, boot_id: str,
    ) -> GamescopeLaunchConfig:
        config = self.build_target(target=target, binding=binding, snapshot=snapshot, boot_id=boot_id)
        with self._lock:
            self._save(config)
        return config

    def build_target(
        self,
        *,
        target: PlacementState,
        binding: TransitionBinding,
        snapshot: ObservedSnapshot,
        boot_id: str,
    ) -> GamescopeLaunchConfig:
        if not BOOT_ID_RE.fullmatch(boot_id):
            raise ValueError("boot identity is invalid")
        internal = tuple(
            item
            for item in snapshot.displays
            if item.stable_id == binding.internal_display_stable_id
        )
        external = tuple(
            item
            for item in snapshot.displays
            if item.stable_id == binding.external_display_stable_id
        )
        gpu = tuple(
            item
            for item in snapshot.gpus
            if item.stable_id == binding.external_gpu_stable_id
        )
        internal_gpu = tuple(
            item
            for item in snapshot.gpus
            if item.stable_id == binding.internal_gpu_stable_id
        )
        if (
            len(internal) != 1
            or len(external) != 1
            or len(gpu) != 1
            or len(internal_gpu) != 1
        ):
            raise ValueError("presentation target identities changed")
        boot_hash = hashlib.sha256(boot_id.encode("utf-8")).hexdigest()
        if target is PlacementState.PORTABLE:
            config = GamescopeLaunchConfig(
                boot_id_sha256=boot_hash,
                target="portable",
                internal_connector=internal[0].connector,
            )
        elif target is PlacementState.DOCKED_EGPU:
            config = GamescopeLaunchConfig(
                boot_id_sha256=boot_hash,
                target="docked_egpu",
                internal_connector=internal[0].connector,
                external_connector=external[0].connector,
                vendor_device=gpu[0].vendor_device,
                egpu_binding_sha256=hashlib.sha256(
                    f"{boot_id}:{binding.egpu_stable_id}".encode("utf-8")
                ).hexdigest(),
            )
        elif target is PlacementState.DOCKED_IGPU:
            config = GamescopeLaunchConfig(
                boot_id_sha256=boot_hash,
                target="docked_igpu",
                internal_connector=internal[0].connector,
                external_connector=external[0].connector,
                vendor_device=internal_gpu[0].vendor_device,
                egpu_binding_sha256=hashlib.sha256(
                    f"{boot_id}:{binding.egpu_stable_id}".encode("utf-8")
                ).hexdigest(),
            )
        else:
            raise ValueError("presentation target is unsupported")
        return config

    def _save(self, value: GamescopeLaunchConfig) -> None:
        self._validate_root()
        if self._target.is_symlink():
            raise ValueError("presentation config cannot be a symlink")
        data = (
            json.dumps(
                config_to_dict(value),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            )
            + "\n"
        ).encode("utf-8")
        if len(data) > MAX_CONFIG_BYTES:
            raise ValueError("presentation config exceeds its bound")
        temporary = self._root / f".{CONFIG_FILENAME}.{secrets.token_hex(8)}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(temporary, flags, CONFIG_FILE_MODE)
        try:
            with os.fdopen(descriptor, "wb") as target:
                if os.name == "posix":
                    os.fchmod(target.fileno(), CONFIG_FILE_MODE)
                target.write(data)
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary, self._target)
            self._sync_directory()
        except Exception:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def _validate_root(self) -> None:
        if self._root.is_symlink() or not self._root.is_dir():
            raise ValueError("presentation state root must be a real directory")

    def _sync_directory(self) -> None:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        try:
            descriptor = os.open(self._root, flags)
        except OSError:
            return
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
