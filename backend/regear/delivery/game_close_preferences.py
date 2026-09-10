"""Atomic fixed-path persistence for per-game close preferences.

What is stored is one player answer to one prompt: "do not ask again before
closing *this* game for *this* action", and whether to reopen it afterwards.
Both keys are part of the record rather than derived at read time, so a record
can never be applied to a game or an action the player did not answer about.

Losing a record is deliberately harmless: the player is asked again, which is
the state they were in before they ticked anything. So when the file is missing,
truncated, oversized or unparseable, this reports nothing stored rather than
raising -- with one exception. A file that is a symlink is refused loudly,
because that is not a corrupt preference, it is someone redirecting a
root-written file somewhere else.

The bound works the same way. When the store is full the oldest record is
dropped rather than the new one refused, so a player's most recent answer is
always the one that survives and the cost of the bound is an extra prompt.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
from pathlib import Path
from typing import Any

from ..domain.game_close_consent import GameClosePreference, InterruptIntent
from ..domain.game_compatibility import STEAM_APP_ID_RE


FILENAME = "game-close-preferences.json"
SCHEMA_VERSION = 1
MAX_BYTES = 64 * 1024
#: Enough for a large library's worth of answers; small enough that a corrupt
#: or hostile file cannot make a read expensive.
MAX_RECORDS = 256


class GameClosePreferenceStore:
    """Remember, per game and per intent, what the player already answered."""

    def __init__(self, state_root: Path) -> None:
        if not state_root.is_absolute():
            raise ValueError("game close preference state root must be absolute")
        self._root = state_root
        self._lock = threading.Lock()

    def load(
        self, steam_app_id: str, intent: InterruptIntent
    ) -> GameClosePreference | None:
        """The player's standing answer for one game and one intent, if any."""
        for record in self.load_all():
            if record.steam_app_id == steam_app_id and record.intent is intent:
                return record
        return None

    def load_all(self) -> tuple[GameClosePreference, ...]:
        with self._lock:
            return tuple(self._load_locked())

    def remember(self, preference: GameClosePreference) -> None:
        """Replace this game's answer for this intent, keeping every other."""
        self._validate(preference)
        with self._lock:
            kept = [
                record
                for record in self._load_locked()
                if not (
                    record.steam_app_id == preference.steam_app_id
                    and record.intent is preference.intent
                )
            ]
            kept.append(preference)
            # Newest last, so dropping from the front discards the answer the
            # player is least likely to still be relying on.
            self._save_locked(tuple(kept[-MAX_RECORDS:]))

    def forget(self, steam_app_id: str, intent: InterruptIntent) -> None:
        """Return this game to being asked about, for this intent only."""
        with self._lock:
            kept = tuple(
                record
                for record in self._load_locked()
                if not (record.steam_app_id == steam_app_id and record.intent is intent)
            )
            self._save_locked(kept)

    @staticmethod
    def _validate(preference: GameClosePreference) -> None:
        if not STEAM_APP_ID_RE.fullmatch(preference.steam_app_id):
            raise ValueError("game close preference app id is invalid")
        if not isinstance(preference.intent, InterruptIntent):
            raise ValueError("game close preference intent is invalid")
        if type(preference.skip_confirmation) is not bool:
            raise ValueError("game close preference confirmation flag is invalid")
        if type(preference.relaunch_after) is not bool:
            raise ValueError("game close preference relaunch flag is invalid")

    def _target(self) -> Path:
        target = self._root / FILENAME
        if target.is_symlink():
            raise ValueError("game close preferences cannot be a symlink")
        return target

    def _load_locked(self) -> list[GameClosePreference]:
        target = self._target()
        try:
            descriptor = os.open(target, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except FileNotFoundError:
            return []
        except OSError:
            return []
        with os.fdopen(descriptor, "rb") as source:
            raw = source.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            return []
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return []
        if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
            return []
        entries = value.get("preferences")
        if not isinstance(entries, list):
            return []
        records: list[GameClosePreference] = []
        seen: set[tuple[str, InterruptIntent]] = set()
        for entry in entries[:MAX_RECORDS]:
            record = self._decode(entry)
            if record is None:
                # One unreadable entry discards that entry, not the file: the
                # rest are still the player's answers.
                continue
            key = (record.steam_app_id, record.intent)
            if key in seen:
                continue
            seen.add(key)
            records.append(record)
        return records

    @staticmethod
    def _decode(entry: Any) -> GameClosePreference | None:
        if not isinstance(entry, dict):
            return None
        app_id = entry.get("steam_app_id")
        intent = entry.get("intent")
        skip = entry.get("skip_confirmation")
        relaunch = entry.get("relaunch_after")
        if not isinstance(app_id, str) or not STEAM_APP_ID_RE.fullmatch(app_id):
            return None
        if type(skip) is not bool or type(relaunch) is not bool:
            return None
        try:
            parsed = InterruptIntent(intent)
        except ValueError:
            return None
        return GameClosePreference(app_id, parsed, skip, relaunch)

    def _save_locked(self, records: tuple[GameClosePreference, ...]) -> None:
        target = self._target()
        raw = (
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "preferences": [
                        {
                            "steam_app_id": record.steam_app_id,
                            "intent": record.intent.value,
                            "skip_confirmation": record.skip_confirmation,
                            "relaunch_after": record.relaunch_after,
                        }
                        for record in records
                    ],
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("ascii")
        if len(raw) > MAX_BYTES:
            raise ValueError("game close preferences are too large to store")
        temporary = self._root / f".{FILENAME}.{secrets.token_hex(8)}.tmp"
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(raw)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, target)
            os.chmod(target, 0o600)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
