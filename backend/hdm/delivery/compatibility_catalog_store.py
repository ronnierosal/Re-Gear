"""Fixed-path, atomic persistence for reviewed compatibility catalogs.

The store deliberately has no Decky delivery surface.  A future reviewed catalog
workflow may construct it beneath Re-Gear's fixed state directory, but a frontend
never selects paths, writes raw JSON, or bypasses the domain promotion rules.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import threading
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from ..domain.game_compatibility import (
    CompatibilityPromotion,
    EgpuHandoffStatus,
    GameCompatibilityRecord,
    GameSaveCapability,
)
from ..domain.hardware_compatibility import (
    HardwareCapability,
    HardwareCapabilityClaim,
    HardwareCatalogStatus,
    HardwareCompatibilityRecord,
    HardwarePromotion,
)


SCHEMA_VERSION = 1
GAME_CATALOG_FILENAME = "game-compatibility.json"
HARDWARE_CATALOG_FILENAME = "hardware-compatibility.json"
MAX_CATALOG_BYTES = 256 * 1024
MAX_GAME_RECORDS = 256
MAX_HARDWARE_RECORDS = 128
TEMP_TOKEN_RE = re.compile(r"^[a-zA-Z0-9_-]{8,48}$")


class FileCompatibilityCatalogStore:
    """Persist canonical catalog records without permitting history regression."""

    def __init__(
        self,
        state_root: Path,
        *,
        replace: Callable[[str | os.PathLike[str], str | os.PathLike[str]], None] = os.replace,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        if not state_root.is_absolute():
            raise ValueError("compatibility catalog state root must be absolute")
        self._root = state_root
        self._replace = replace
        self._token_factory = token_factory or (lambda: secrets.token_hex(8))
        self._lock = threading.RLock()

    def load_games(self) -> tuple[GameCompatibilityRecord, ...]:
        with self._lock:
            value = self._load(GAME_CATALOG_FILENAME)
            if value is None:
                return ()
            return self._decode_games(value)

    def save_games(self, records: Iterable[GameCompatibilityRecord]) -> None:
        normalized = self._normalize_games(records)
        with self._lock:
            current = self.load_games()
            self._validate_game_progress(current, normalized)
            self._save(GAME_CATALOG_FILENAME, {"schema_version": SCHEMA_VERSION, "records": [self._game_to_dict(item) for item in normalized]})

    def update_games(
        self,
        update: Callable[
            [tuple[GameCompatibilityRecord, ...]], Iterable[GameCompatibilityRecord]
        ],
    ) -> tuple[GameCompatibilityRecord, ...]:
        """Apply one validated catalog update while this store owns the lock."""
        with self._lock:
            current = self.load_games()
            replacement = self._normalize_games(update(current))
            self._validate_game_progress(current, replacement)
            if replacement != current:
                self._save(
                    GAME_CATALOG_FILENAME,
                    {
                        "schema_version": SCHEMA_VERSION,
                        "records": [self._game_to_dict(item) for item in replacement],
                    },
                )
            return replacement

    def load_hardware(self) -> tuple[HardwareCompatibilityRecord, ...]:
        with self._lock:
            value = self._load(HARDWARE_CATALOG_FILENAME)
            if value is None:
                return ()
            return self._decode_hardware(value)

    def save_hardware(self, records: Iterable[HardwareCompatibilityRecord]) -> None:
        normalized = self._normalize_hardware(records)
        with self._lock:
            current = self.load_hardware()
            self._validate_hardware_progress(current, normalized)
            self._save(HARDWARE_CATALOG_FILENAME, {"schema_version": SCHEMA_VERSION, "records": [self._hardware_to_dict(item) for item in normalized]})

    def update_hardware(
        self,
        update: Callable[
            [tuple[HardwareCompatibilityRecord, ...]], Iterable[HardwareCompatibilityRecord]
        ],
    ) -> tuple[HardwareCompatibilityRecord, ...]:
        """Apply one validated catalog update while this store owns the lock."""
        with self._lock:
            current = self.load_hardware()
            replacement = self._normalize_hardware(update(current))
            self._validate_hardware_progress(current, replacement)
            if replacement != current:
                self._save(
                    HARDWARE_CATALOG_FILENAME,
                    {
                        "schema_version": SCHEMA_VERSION,
                        "records": [self._hardware_to_dict(item) for item in replacement],
                    },
                )
            return replacement

    def _load(self, filename: str) -> dict[str, Any] | None:
        self._validate_root()
        target = self._root / filename
        if target.is_symlink():
            raise ValueError("compatibility catalog target cannot be a symlink")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(target, flags)
        except FileNotFoundError:
            return None
        with os.fdopen(descriptor, "rb") as source:
            data = source.read(MAX_CATALOG_BYTES + 1)
        if len(data) > MAX_CATALOG_BYTES:
            raise ValueError("compatibility catalog exceeds its byte bound")
        try:
            value = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("compatibility catalog JSON is invalid") from error
        if not isinstance(value, dict):
            raise ValueError("compatibility catalog root must be an object")
        return value

    def _save(self, filename: str, value: dict[str, Any]) -> None:
        data = (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("utf-8")
        if len(data) > MAX_CATALOG_BYTES:
            raise ValueError("compatibility catalog exceeds its byte bound")
        target = self._root / filename
        token = self._token_factory()
        if not TEMP_TOKEN_RE.fullmatch(token):
            raise ValueError("compatibility catalog temporary token is invalid")
        temporary = self._root / f".{filename}.{token}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(temporary, flags, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            self._replace(temporary, target)
            try:
                os.chmod(target, 0o600)
            except OSError:
                pass
            self._sync_directory()
        except Exception:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def _validate_root(self) -> None:
        try:
            metadata = self._root.lstat()
        except OSError as error:
            raise ValueError("compatibility catalog state root is unavailable") from error
        if self._root.is_symlink() or not self._root.is_dir() or not metadata:
            raise ValueError("compatibility catalog state root must be a real directory")

    @staticmethod
    def _normalize_games(records: Iterable[GameCompatibilityRecord]) -> tuple[GameCompatibilityRecord, ...]:
        result = tuple(records)
        if len(result) > MAX_GAME_RECORDS or any(not isinstance(item, GameCompatibilityRecord) for item in result):
            raise ValueError("game compatibility catalog records are invalid")
        if len({item.catalog_id for item in result}) != len(result):
            raise ValueError("game compatibility catalog IDs must be unique")
        return tuple(sorted(result, key=lambda item: item.catalog_id))

    @staticmethod
    def _normalize_hardware(records: Iterable[HardwareCompatibilityRecord]) -> tuple[HardwareCompatibilityRecord, ...]:
        result = tuple(records)
        if len(result) > MAX_HARDWARE_RECORDS or any(not isinstance(item, HardwareCompatibilityRecord) for item in result):
            raise ValueError("hardware compatibility catalog records are invalid")
        if len({item.catalog_id for item in result}) != len(result):
            raise ValueError("hardware compatibility catalog IDs must be unique")
        return tuple(sorted(result, key=lambda item: item.catalog_id))

    @classmethod
    def _decode_games(cls, value: dict[str, Any]) -> tuple[GameCompatibilityRecord, ...]:
        cls._require_exact(value, {"schema_version", "records"})
        if value["schema_version"] != SCHEMA_VERSION or not isinstance(value["records"], list):
            raise ValueError("game compatibility catalog schema is invalid")
        try:
            records = tuple(cls._game_from_dict(item) for item in value["records"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("game compatibility catalog record is invalid") from error
        return cls._normalize_games(records)

    @classmethod
    def _decode_hardware(cls, value: dict[str, Any]) -> tuple[HardwareCompatibilityRecord, ...]:
        cls._require_exact(value, {"schema_version", "records"})
        if value["schema_version"] != SCHEMA_VERSION or not isinstance(value["records"], list):
            raise ValueError("hardware compatibility catalog schema is invalid")
        try:
            records = tuple(cls._hardware_from_dict(item) for item in value["records"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("hardware compatibility catalog record is invalid") from error
        return cls._normalize_hardware(records)

    @staticmethod
    def _game_to_dict(record: GameCompatibilityRecord) -> dict[str, Any]:
        return {"catalog_id": record.catalog_id, "title": record.title, "host_profile_id": record.host_profile_id, "egpu_profile_id": record.egpu_profile_id, "steam_app_id": record.steam_app_id, "egpu_handoff": record.egpu_handoff.value, "save_sleep": record.save_sleep.value, "promotions": [{"evidence_id": item.evidence_id, "dimension": item.dimension, "from_status": item.from_status, "to_status": item.to_status} for item in record.promotions]}

    @classmethod
    def _game_from_dict(cls, value: Any) -> GameCompatibilityRecord:
        if not isinstance(value, dict):
            raise ValueError("game compatibility catalog record is invalid")
        cls._require_exact(value, {"catalog_id", "title", "host_profile_id", "egpu_profile_id", "steam_app_id", "egpu_handoff", "save_sleep", "promotions"})
        promotions = tuple(cls._game_promotion_from_dict(item) for item in cls._list(value["promotions"]))
        return GameCompatibilityRecord(value["catalog_id"], value["title"], value["host_profile_id"], value["egpu_profile_id"], value["steam_app_id"], EgpuHandoffStatus(value["egpu_handoff"]), GameSaveCapability(value["save_sleep"]), promotions)

    @staticmethod
    def _game_promotion_from_dict(value: Any) -> CompatibilityPromotion:
        if not isinstance(value, dict) or set(value) != {"evidence_id", "dimension", "from_status", "to_status"}:
            raise ValueError("game compatibility promotion is invalid")
        return CompatibilityPromotion(value["evidence_id"], value["dimension"], value["from_status"], value["to_status"])

    @staticmethod
    def _hardware_to_dict(record: HardwareCompatibilityRecord) -> dict[str, Any]:
        return {"catalog_id": record.catalog_id, "host_profile_id": record.host_profile_id, "egpu_profile_id": record.egpu_profile_id, "combination_status": record.combination_status.value, "claims": [{"capability": item.capability.value, "status": item.status.value, "evidence_id": item.evidence_id} for item in record.claims], "promotions": [{"capability": item.capability.value, "from_status": item.from_status.value, "to_status": item.to_status.value, "evidence_id": item.evidence_id} for item in record.promotions]}

    @classmethod
    def _hardware_from_dict(cls, value: Any) -> HardwareCompatibilityRecord:
        if not isinstance(value, dict):
            raise ValueError("hardware compatibility catalog record is invalid")
        cls._require_exact(value, {"catalog_id", "host_profile_id", "egpu_profile_id", "combination_status", "claims", "promotions"})
        claims = tuple(cls._hardware_claim_from_dict(item) for item in cls._list(value["claims"]))
        promotions = tuple(cls._hardware_promotion_from_dict(item) for item in cls._list(value["promotions"]))
        return HardwareCompatibilityRecord(value["catalog_id"], value["host_profile_id"], value["egpu_profile_id"], HardwareCatalogStatus(value["combination_status"]), claims, promotions)

    @staticmethod
    def _hardware_claim_from_dict(value: Any) -> HardwareCapabilityClaim:
        if not isinstance(value, dict) or set(value) != {"capability", "status", "evidence_id"}:
            raise ValueError("hardware compatibility claim is invalid")
        return HardwareCapabilityClaim(HardwareCapability(value["capability"]), HardwareCatalogStatus(value["status"]), value["evidence_id"])

    @staticmethod
    def _hardware_promotion_from_dict(value: Any) -> HardwarePromotion:
        if not isinstance(value, dict) or set(value) != {"capability", "from_status", "to_status", "evidence_id"}:
            raise ValueError("hardware compatibility promotion is invalid")
        return HardwarePromotion(HardwareCapability(value["capability"]), HardwareCatalogStatus(value["from_status"]), HardwareCatalogStatus(value["to_status"]), value["evidence_id"])

    @classmethod
    def _validate_game_progress(cls, current: tuple[GameCompatibilityRecord, ...], replacement: tuple[GameCompatibilityRecord, ...]) -> None:
        next_by_id = {item.catalog_id: item for item in replacement}
        for previous in current:
            later = next_by_id.get(previous.catalog_id)
            if later is None:
                raise ValueError("game compatibility catalog records cannot be removed")
            if (previous.title, previous.host_profile_id, previous.egpu_profile_id, previous.steam_app_id) != (later.title, later.host_profile_id, later.egpu_profile_id, later.steam_app_id):
                raise ValueError("game compatibility catalog identity cannot change")
            if later.promotions[: len(previous.promotions)] != previous.promotions:
                raise ValueError("game compatibility catalog history cannot diverge")

    @classmethod
    def _validate_hardware_progress(cls, current: tuple[HardwareCompatibilityRecord, ...], replacement: tuple[HardwareCompatibilityRecord, ...]) -> None:
        next_by_id = {item.catalog_id: item for item in replacement}
        for previous in current:
            later = next_by_id.get(previous.catalog_id)
            if later is None:
                raise ValueError("hardware compatibility catalog records cannot be removed")
            if (previous.host_profile_id, previous.egpu_profile_id) != (later.host_profile_id, later.egpu_profile_id):
                raise ValueError("hardware compatibility catalog identity cannot change")
            if later.promotions[: len(previous.promotions)] != previous.promotions:
                raise ValueError("hardware compatibility catalog history cannot diverge")

    @staticmethod
    def _require_exact(value: dict[str, Any], expected: set[str]) -> None:
        if set(value) != expected:
            raise ValueError("compatibility catalog fields are invalid")

    @staticmethod
    def _list(value: Any) -> list[Any]:
        if not isinstance(value, list):
            raise ValueError("compatibility catalog list is invalid")
        return value

    def _sync_directory(self) -> None:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        try:
            descriptor = os.open(self._root, flags)
        except OSError:
            return
        try:
            os.fsync(descriptor)
        except OSError:
            pass
        finally:
            os.close(descriptor)
