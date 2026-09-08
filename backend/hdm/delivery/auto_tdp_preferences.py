"""Strict atomic persistence for player-authored per-placement Auto TDP intent.

Missing storage has no defaults and enables nothing. This file contains policy
preferences only; hardware, thermal, telemetry, ownership and admission evidence
belong to their existing independent sources.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

from ..domain.auto_tdp import AutoTdpPolicy
from ..domain.auto_tdp_preferences import (
    AutoTdpModePreference,
    AutoTdpPreferenceSet,
)
from ..domain.control_plane import PlacementState


FILENAME = "auto-tdp-preferences.json"
MAX_BYTES = 8192


@dataclass(frozen=True, slots=True)
class AutoTdpPreferencesStorageResult:
    code: str
    preferences: AutoTdpPreferenceSet | None = None


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate Auto TDP preference key")
        result[key] = value
    return result


def decode_auto_tdp_preferences(raw: bytes) -> AutoTdpPreferenceSet:
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
        raise ValueError("Auto TDP preferences exceed byte bound")
    value = json.loads(raw, object_pairs_hook=_unique)
    if not isinstance(value, dict) or set(value) != {"schema_version", "preferences"}:
        raise ValueError("Auto TDP preference root is invalid")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("Auto TDP preference schema is invalid")
    rows = value["preferences"]
    if not isinstance(rows, list) or not rows:
        raise ValueError("Auto TDP preferences require a nonempty list")
    decoded = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {
            "placement", "minimum_watts", "maximum_watts", "target_fps"
        }:
            raise ValueError("Auto TDP preference entry is invalid")
        try:
            placement = PlacementState(row["placement"])
        except (TypeError, ValueError) as error:
            raise ValueError("Auto TDP preference placement is invalid") from error
        decoded.append(AutoTdpModePreference(placement, AutoTdpPolicy(
            row["minimum_watts"], row["maximum_watts"], row["target_fps"]
        )))
    return AutoTdpPreferenceSet(tuple(decoded))


def encode_auto_tdp_preferences(preferences: AutoTdpPreferenceSet) -> bytes:
    if type(preferences) is not AutoTdpPreferenceSet:
        raise ValueError("Validated Auto TDP preferences are required")
    for item in preferences.preferences:
        if item.policy != AutoTdpPolicy(
            item.minimum_watts, item.maximum_watts, item.target_fps
        ):
            raise ValueError("Custom Auto TDP tuning is not a saved player preference")
    value = {
        "schema_version": 1,
        "preferences": [
            {
                "placement": item.placement.value,
                "minimum_watts": item.minimum_watts,
                "maximum_watts": item.maximum_watts,
                "target_fps": item.target_fps,
            }
            for item in sorted(preferences.preferences, key=lambda item: item.placement.value)
        ],
    }
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("ascii")
    if len(raw) > MAX_BYTES:
        raise ValueError("Auto TDP preferences exceed byte bound")
    decode_auto_tdp_preferences(raw)
    return raw


class FileAutoTdpPreferences:
    """Load or replace one mode while preserving every other stored mode."""

    def __init__(self, state_root: Path) -> None:
        if not state_root.is_absolute() or state_root == Path(state_root.anchor):
            raise ValueError("Auto TDP preference root must be a narrow absolute path")
        self._root = Path(state_root)
        self._target = self._root / FILENAME
        self._lock = threading.RLock()

    @staticmethod
    def _owner(metadata) -> None:
        if os.name != "nt" and (metadata.st_uid != os.geteuid() or metadata.st_mode & 0o022):
            raise ValueError("Auto TDP preference storage is writable by another owner")

    def _validate_root_and_target(self) -> bool:
        metadata = self._root.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or self._root.is_symlink():
            raise ValueError("Auto TDP preference root must be a real directory")
        self._owner(metadata)
        try:
            metadata = self._target.lstat()
        except FileNotFoundError:
            return False
        if not stat.S_ISREG(metadata.st_mode) or self._target.is_symlink():
            raise ValueError("Auto TDP preferences must be a regular file")
        self._owner(metadata)
        return True

    def _read(self) -> AutoTdpPreferenceSet | None:
        if not self._validate_root_and_target():
            return None
        descriptor = os.open(
            self._target,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
        )
        with os.fdopen(descriptor, "rb") as source:
            actual = os.fstat(source.fileno())
            if not stat.S_ISREG(actual.st_mode):
                raise ValueError("Auto TDP preference descriptor must be regular")
            self._owner(actual)
            raw = source.read(MAX_BYTES + 1)
        return decode_auto_tdp_preferences(raw)

    def load(self) -> AutoTdpPreferencesStorageResult:
        with self._lock:
            try:
                preferences = self._read()
                return AutoTdpPreferencesStorageResult(
                    "auto_tdp_preferences.missing" if preferences is None else "auto_tdp_preferences.loaded",
                    preferences,
                )
            except Exception:
                return AutoTdpPreferencesStorageResult("auto_tdp_preferences.invalid")

    def save_preference(
        self,
        preference: AutoTdpModePreference,
    ) -> AutoTdpPreferencesStorageResult:
        with self._lock:
            try:
                if type(preference) is not AutoTdpModePreference:
                    raise ValueError("A validated Auto TDP mode preference is required")
                # Validate the reduced storage contract before any filesystem read.
                encode_auto_tdp_preferences(AutoTdpPreferenceSet((preference,)))
                current = self._read()
                items = [] if current is None else [
                    item for item in current.preferences
                    if item.placement is not preference.placement
                ]
                preferences = AutoTdpPreferenceSet(tuple(items + [preference]))
                raw = encode_auto_tdp_preferences(preferences)
                descriptor, name = tempfile.mkstemp(
                    prefix=".auto-tdp-preferences.", suffix=".tmp", dir=self._root
                )
                temporary = Path(name)
                try:
                    with os.fdopen(descriptor, "wb") as target:
                        target.write(raw)
                        target.flush()
                        os.fsync(target.fileno())
                    os.replace(temporary, self._target)
                    if os.name != "nt":
                        directory = os.open(self._root, os.O_RDONLY | os.O_DIRECTORY)
                        try:
                            os.fsync(directory)
                        finally:
                            os.close(directory)
                finally:
                    temporary.unlink(missing_ok=True)
                return AutoTdpPreferencesStorageResult("auto_tdp_preferences.saved", preferences)
            except Exception:
                return AutoTdpPreferencesStorageResult("auto_tdp_preferences.save_failed")
