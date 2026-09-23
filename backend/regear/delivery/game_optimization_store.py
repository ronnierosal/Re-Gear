"""Durable optimization preferences and per-game lifecycle state.

Two kinds of record, one discipline, the same one the graphics foundation uses
for its provenance (``graphics_management_state``):

* **Absent is not unreadable.** ``load`` answers ABSENT (nothing was ever
  stored), UNTRUSTED (something was, and cannot be believed) or LOADED.
  Untrusted is never read as a default: untrusted preferences withhold
  automatic management, and an untrusted lifecycle writes nothing. Only an
  explicit ``quarantine`` -- which moves the record aside rather than deleting
  it -- lets a lane start again.
* **Every write is atomic** -- temporary file, fsync, replace, directory fsync
  where the platform has one -- so a crash leaves the previous record or the
  new one, never half of either.
* **No write loses a change it has not seen.** Each record carries a revision
  and ``save`` takes the revision the caller read. A mismatch is a
  ``StateConflict``, not an overwrite.

Records are bounded in size and count and are refused, not followed, when they
are symlinks. Nothing here writes a game's configuration.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import threading
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Generic, TypeVar

from ..domain.game_optimization_preferences import (
    PREFERENCES_VERSION,
    GameChoice,
    GamePreference,
    OptimizationPreferences,
)
from ..domain.game_optimization_state import (
    STATE_VERSION,
    Attempt,
    AttemptOutcome,
    DispatchKind,
    GameOptimizationState,
    InFlight,
    LaneKey,
    OptimizationContext,
    Phase,
    QueuedPlan,
)
from ..domain.mode_profiles import ExperienceTarget
from ..domain.models import OperatingMode
from ..domain.performance_plan import FrameGenerationRef, PerformancePlan
from ..domain.semantic_profiles import Resolution, UpscalingMode


PREFERENCES_FILENAME = "optimization-preferences.json"
STATE_DIRECTORY = "optimization-state"
QUARANTINE_DIRECTORY = "quarantine"
MAX_PREFERENCES_BYTES = 64 * 1024
MAX_STATE_BYTES = 16 * 1024
#: Quarantined records kept per lane. Older ones are removed: they were
#: already unreadable, and keeping every one would make the bound meaningless.
MAX_QUARANTINED = 3
STATE_NAME_RE = re.compile(r"^[1-9][0-9]{0,9}\.[a-z_]{1,24}\.json$")


class LoadState(StrEnum):
    ABSENT = "optimization_store.absent"
    UNTRUSTED = "optimization_store.untrusted"
    LOADED = "optimization_store.loaded"


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class Lookup(Generic[T]):
    state: LoadState
    value: T | None = None
    detail: str = ""

    @property
    def trusted(self) -> bool:
        return self.state is LoadState.LOADED and self.value is not None


class StoreError(RuntimeError):
    """A record could not be written. Callers turn this into an outcome."""


class StateConflict(StoreError):
    """The stored revision is not the one the caller read."""


class _Untrusted(ValueError):
    pass


class GameOptimizationStore:
    def __init__(self, state_root: Path) -> None:
        if not state_root.is_absolute():
            raise ValueError("optimization state root must be absolute")
        self._root = state_root
        self._states = state_root / STATE_DIRECTORY
        self._lock = threading.Lock()

    # ----------------------------------------------------------- preferences

    def load_preferences(self) -> Lookup[OptimizationPreferences]:
        return self._load(
            self._root / PREFERENCES_FILENAME, MAX_PREFERENCES_BYTES, _decode_preferences
        )

    def save_preferences(
        self, preferences: OptimizationPreferences, expected_revision: int
    ) -> None:
        """Store preferences written from ``expected_revision`` (0 when absent).

        The new value's revision must be exactly one higher, so a writer that
        read a stale copy fails here instead of undoing someone else's change.
        """
        with self._lock:
            current = self.load_preferences()
            self._require_revision(current, expected_revision, preferences.revision)
            self._write(
                self._root / PREFERENCES_FILENAME,
                _encode_preferences(preferences),
                MAX_PREFERENCES_BYTES,
            )

    def quarantine_preferences(self) -> bool:
        """Move untrusted preferences aside; absent then means opted out."""
        with self._lock:
            if self.load_preferences().state is not LoadState.UNTRUSTED:
                return False
            return self._move_aside(self._root / PREFERENCES_FILENAME, "preferences")

    # ----------------------------------------------------------------- state

    def load_state(self, key: LaneKey) -> Lookup[GameOptimizationState]:
        return self._load(self._state_path(key), MAX_STATE_BYTES, lambda value: _decode_state(value, key))

    def save_state(self, state: GameOptimizationState, expected_revision: int) -> None:
        with self._lock:
            current = self.load_state(state.key)
            self._require_revision(current, expected_revision, state.revision)
            self._write(self._state_path(state.key), _encode_state(state), MAX_STATE_BYTES)

    def lanes(self) -> tuple[LaneKey, ...]:
        """Every lane with a stored record, trusted or not. Bounded by the directory."""
        try:
            names = sorted(entry.name for entry in os.scandir(self._states) if entry.is_file(follow_symlinks=False))
        except FileNotFoundError:
            return ()
        except OSError as error:
            raise StoreError(f"optimization state is unreadable: {error}") from error
        keys = []
        for name in names:
            if not STATE_NAME_RE.fullmatch(name):
                continue
            app_id, mode, _ = name.split(".")
            try:
                keys.append(LaneKey(app_id, OperatingMode(mode)))
            except ValueError:
                continue
        return tuple(keys)

    def quarantine(self, key: LaneKey) -> bool:
        """Move an untrusted lane record aside so the lane can start again.

        Explicit, and never applied to a trusted record: this is how stale or
        corrupt state gets a resolution without being silently deleted.
        """
        with self._lock:
            if self.load_state(key).state is not LoadState.UNTRUSTED:
                return False
            return self._move_aside(self._state_path(key), key.identity)

    # ------------------------------------------------------------- internals

    def _state_path(self, key: LaneKey) -> Path:
        return self._states / f"{key.identity}.json"

    @staticmethod
    def _require_revision(current: Lookup, expected: int, new: int) -> None:
        if current.state is LoadState.UNTRUSTED:
            raise StateConflict(f"stored record is untrusted: {current.detail}")
        stored = current.value.revision if current.value is not None else 0
        if stored != expected:
            raise StateConflict(f"stored revision is {stored}, expected {expected}")
        if new <= stored:
            raise StateConflict("a saved record must advance its revision")

    @staticmethod
    def _load(path: Path, limit: int, decode) -> Lookup:
        try:
            if path.is_symlink():
                return Lookup(LoadState.UNTRUSTED, None, "record is a symlink")
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
        except FileNotFoundError:
            return Lookup(LoadState.ABSENT)
        except OSError as error:
            return Lookup(LoadState.UNTRUSTED, None, f"record is unreadable: {error}")
        try:
            with os.fdopen(descriptor, "rb") as source:
                raw = source.read(limit + 1)
        except OSError as error:
            return Lookup(LoadState.UNTRUSTED, None, f"record is unreadable: {error}")
        if len(raw) > limit:
            return Lookup(LoadState.UNTRUSTED, None, "record is oversized")
        try:
            value = json.loads(raw.decode("utf-8"))
            return Lookup(LoadState.LOADED, decode(value))
        except (UnicodeDecodeError, ValueError, KeyError, TypeError) as error:
            return Lookup(LoadState.UNTRUSTED, None, f"record is malformed: {error}")

    def _write(self, target: Path, value: dict, limit: int) -> None:
        payload = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        if len(payload) > limit:
            raise StoreError("record is too large to store")
        directory = target.parent
        temporary = directory / f".{target.name}.{secrets.token_hex(8)}.tmp"
        try:
            directory.mkdir(parents=True, exist_ok=True)
            if target.is_symlink():
                raise StoreError("refusing to replace a symlinked record")
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0),
                0o600,
            )
            with os.fdopen(descriptor, "wb") as output:
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, target)
            self._sync_directory(directory)
        except OSError as error:
            raise StoreError(f"optimization state write failed: {error}") from error
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass

    @staticmethod
    def _sync_directory(directory: Path) -> None:
        # Directories cannot be opened for fsync on Windows; the product runs
        # on Linux, where O_DIRECTORY exists and this always runs.
        flag = getattr(os, "O_DIRECTORY", None)
        if flag is None:
            return
        handle = os.open(directory, os.O_RDONLY | flag)
        try:
            os.fsync(handle)
        finally:
            os.close(handle)

    def _move_aside(self, source: Path, label: str) -> bool:
        target_dir = self._root / QUARANTINE_DIRECTORY
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            os.replace(source, target_dir / f"{label}.{secrets.token_hex(6)}.json")
            self._prune_quarantine(target_dir, label)
            self._sync_directory(source.parent)
            self._sync_directory(target_dir)
        except OSError as error:
            raise StoreError(f"could not quarantine {label}: {error}") from error
        return True

    @staticmethod
    def _prune_quarantine(directory: Path, label: str) -> None:
        prefix = f"{label}."
        entries = sorted(
            (entry for entry in os.scandir(directory) if entry.name.startswith(prefix)),
            key=lambda entry: entry.stat(follow_symlinks=False).st_mtime_ns,
        )
        for entry in entries[:-MAX_QUARANTINED]:
            os.unlink(entry.path)


# ------------------------------------------------------------------ codec


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise _Untrusted(message)


def _int(value: Any, name: str) -> int:
    _require(isinstance(value, int) and not isinstance(value, bool), f"{name} is not an integer")
    return value


def _str(value: Any, name: str) -> str:
    _require(isinstance(value, str), f"{name} is not text")
    return value


def _encode_preferences(preferences: OptimizationPreferences) -> dict:
    return {
        "record_version": PREFERENCES_VERSION,
        "revision": preferences.revision,
        "global_enabled": preferences.global_enabled,
        "default_preference": preferences.default_preference.value,
        "games": {
            app_id: {
                "choice": game.choice.value,
                "preference": game.preference.value if game.preference else None,
            }
            for app_id, game in sorted(preferences.games.items())
        },
    }


def _decode_preferences(value: Any) -> OptimizationPreferences:
    _require(isinstance(value, dict), "preferences are not an object")
    _require(value.get("record_version") == PREFERENCES_VERSION, "preferences version is not one this build wrote")
    enabled = value["global_enabled"]
    _require(type(enabled) is bool, "global enablement is not a boolean")
    games_value = value["games"]
    _require(isinstance(games_value, dict), "per-game preferences are not an object")
    games = {}
    for app_id, entry in games_value.items():
        _require(isinstance(entry, dict), "a per-game preference is not an object")
        preference = entry.get("preference")
        games[app_id] = GamePreference(
            GameChoice(_str(entry["choice"], "choice")),
            ExperienceTarget(_str(preference, "preference")) if preference is not None else None,
        )
    # Any one malformed game makes the whole record untrusted, unlike a list
    # of prompts: dropping a single MANUAL entry would silently hand that game
    # back to automatic management.
    return OptimizationPreferences(
        enabled,
        ExperienceTarget(_str(value["default_preference"], "default preference")),
        games,
        _int(value["revision"], "revision"),
    )


def _encode_resolution(resolution: Resolution | None) -> list[int] | None:
    return [resolution.width, resolution.height] if resolution is not None else None


def _decode_resolution(value: Any) -> Resolution | None:
    if value is None:
        return None
    _require(isinstance(value, list) and len(value) == 2, "resolution is not a pair")
    return Resolution(_int(value[0], "width"), _int(value[1], "height"))


def _encode_plan(plan: PerformancePlan | None) -> dict | None:
    if plan is None:
        return None
    return {
        "plan_version": plan.plan_version,
        "target_display_fps": plan.target_display_fps,
        "base_fps_target": plan.base_fps_target,
        "resolution": _encode_resolution(plan.resolution),
        "upscaling": plan.upscaling.value if plan.upscaling is not None else None,
        "frame_generation": (
            {
                "provider_id": plan.frame_generation.provider_id,
                "multiplier": plan.frame_generation.multiplier,
            }
            if plan.frame_generation is not None
            else None
        ),
        "source": plan.source,
    }


def _decode_plan(value: Any) -> PerformancePlan | None:
    if value is None:
        return None
    _require(isinstance(value, dict), "plan is not an object")
    fg = value["frame_generation"]
    upscaling = value["upscaling"]
    # PerformancePlan refuses an unknown plan_version itself, so a queued plan
    # from a future contract is untrusted here rather than reinterpreted.
    return PerformancePlan(
        target_display_fps=_int(value["target_display_fps"], "display target"),
        base_fps_target=_int(value["base_fps_target"], "base target"),
        resolution=_decode_resolution(value["resolution"]),
        upscaling=UpscalingMode(_str(upscaling, "upscaling")) if upscaling is not None else None,
        frame_generation=(
            FrameGenerationRef(_str(fg["provider_id"], "provider"), _int(fg["multiplier"], "multiplier"))
            if fg is not None
            else None
        ),
        source=_str(value["source"], "source"),
        plan_version=_int(value["plan_version"], "plan version"),
    )


def _encode_queued(queued: QueuedPlan | None) -> dict | None:
    if queued is None:
        return None
    return {
        "candidate_id": queued.candidate_id,
        "preference": queued.preference.value,
        "plan": _encode_plan(queued.plan),
    }


def _decode_queued(value: Any) -> QueuedPlan | None:
    if value is None:
        return None
    _require(isinstance(value, dict), "queued plan is not an object")
    return QueuedPlan(
        _str(value["candidate_id"], "candidate id"),
        ExperienceTarget(_str(value["preference"], "preference")),
        _decode_plan(value["plan"]),
    )


def _encode_context(context: OptimizationContext | None) -> dict | None:
    if context is None:
        return None
    return {
        "preference": context.preference.value,
        "game_version": context.game_version,
        "profile_version": context.profile_version,
        "adapter_version": context.adapter_version,
        "schema_id": context.schema_id,
    }


def _decode_context(value: Any) -> OptimizationContext | None:
    if value is None:
        return None
    _require(isinstance(value, dict), "context is not an object")
    return OptimizationContext(
        ExperienceTarget(_str(value["preference"], "preference")),
        _str(value["game_version"], "game version"),
        _int(value["profile_version"], "profile version"),
        _int(value["adapter_version"], "adapter version"),
        _str(value["schema_id"], "schema id"),
    )


_COUNTERS = (
    "learning_windows",
    "excluded_windows",
    "meets",
    "below",
    "windows",
    "degraded",
    "attempts_used",
)


def _encode_state(state: GameOptimizationState) -> dict:
    return {
        "record_version": STATE_VERSION,
        "steam_app_id": state.key.steam_app_id,
        "mode": state.key.mode.value,
        "revision": state.revision,
        "phase": state.phase.value,
        "context": _encode_context(state.context),
        "accepted": _encode_queued(state.accepted),
        "accepted_context": _encode_context(state.accepted_context),
        "candidate": _encode_queued(state.candidate),
        "restore_pending": state.restore_pending,
        "in_flight": (
            {"kind": state.in_flight.kind.value, "candidate_id": state.in_flight.candidate_id}
            if state.in_flight is not None
            else None
        ),
        "counters": {name: getattr(state, name) for name in _COUNTERS},
        "history": [
            {"candidate_id": item.candidate_id, "outcome": item.outcome.value, "detail": item.detail}
            for item in state.history
        ],
        "reason": state.reason,
    }


def _decode_state(value: Any, key: LaneKey) -> GameOptimizationState:
    _require(isinstance(value, dict), "state is not an object")
    _require(value.get("record_version") == STATE_VERSION, "state version is not one this build wrote")
    _require(
        value["steam_app_id"] == key.steam_app_id and value["mode"] == key.mode.value,
        "state names another game or mode",
    )
    restore = value["restore_pending"]
    _require(type(restore) is bool, "restore flag is not a boolean")
    flight = value["in_flight"]
    in_flight = None
    if flight is not None:
        _require(isinstance(flight, dict), "in-flight marker is not an object")
        in_flight = InFlight(DispatchKind(_str(flight["kind"], "kind")), _str(flight["candidate_id"], "candidate"))
    counters = value["counters"]
    _require(isinstance(counters, dict), "counters are not an object")
    counts = {}
    for name in _COUNTERS:
        count = _int(counters[name], name)
        _require(0 <= count <= 1_000_000, f"{name} is out of range")
        counts[name] = count
    history_value = value["history"]
    _require(isinstance(history_value, list) and len(history_value) <= 1000, "history is not a bounded list")
    history = tuple(
        Attempt(
            _str(item["candidate_id"], "candidate"),
            AttemptOutcome(_str(item["outcome"], "outcome")),
            _str(item["detail"], "detail"),
        )
        for item in history_value
    )
    state = GameOptimizationState(
        key=key,
        phase=Phase(_str(value["phase"], "phase")),
        context=_decode_context(value["context"]),
        accepted=_decode_queued(value["accepted"]),
        accepted_context=_decode_context(value["accepted_context"]),
        candidate=_decode_queued(value["candidate"]),
        restore_pending=restore,
        in_flight=in_flight,
        history=history,
        reason=_str(value["reason"], "reason"),
        revision=_int(value["revision"], "revision"),
        **counts,
    )
    _require(
        (state.candidate is not None)
        == (state.phase in (Phase.TESTING_PROFILE, Phase.VALIDATING)),
        "a candidate exists exactly while one is being tested",
    )
    _require(
        (state.accepted is None) == (state.accepted_context is None),
        "an accepted plan carries the context it was accepted under",
    )
    return state
