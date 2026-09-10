"""Atomic fixed-path persistence for the one TV a player last docked to.

At most one, replaced rather than accumulated. A list of TVs is a list of
displays the handheld might switch itself to, and only the most recent one is
the intent this records -- a player who docks somewhere new has told us where
they are now, not added a candidate.

Unlike a relaunch intent, reading does **not** consume it. This is a standing
preference, not a one-shot: the same TV is resumed to every time it appears,
until the player docks somewhere else or forgets it.

Every read failure is "nothing remembered", which fails toward doing nothing.
Treating an unreadable file as a TV to switch to would move a player's display
on the strength of corruption. The one exception is a symlink, refused loudly,
because that is not corruption but someone redirecting the file.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import threading
from pathlib import Path

from ..domain.saved_tv import SavedTvProfile


FILENAME = "saved-tv.json"
SCHEMA_VERSION = 1
MAX_BYTES = 1024
#: Display identities as the adapters render them: "display:<edid digest>",
#: "internal-panel", "observed-display:<card>:<connector>".
STABLE_ID_RE = re.compile(r"[A-Za-z0-9_.:@+-]{1,128}")
#: A label comes from EDID, which is attacker-adjacent text off a cable. It is
#: presentation only and never matched on, so it is bounded and stripped of
#: anything that could reflow a line rather than being trusted.
MAX_LABEL = 64


def _clean_label(value: str) -> str:
    if not isinstance(value, str):
        return ""
    return "".join(c for c in value if c.isprintable())[:MAX_LABEL]


class SavedTvStore:
    """Remember the TV to resume to when it next appears."""

    def __init__(self, state_root: Path) -> None:
        if not state_root.is_absolute():
            raise ValueError("saved TV state root must be absolute")
        self._root = state_root
        self._lock = threading.Lock()

    def record(self, profile: SavedTvProfile) -> None:
        """Replace any remembered TV with this one."""
        if not STABLE_ID_RE.fullmatch(profile.display_stable_id):
            raise ValueError("saved TV display identity is invalid")
        if not isinstance(profile.edid_identified, bool):
            raise ValueError("saved TV identity grade is invalid")
        raw = (
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "display_stable_id": profile.display_stable_id,
                    "edid_identified": profile.edid_identified,
                    "label": _clean_label(profile.label),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        if len(raw) > MAX_BYTES:
            raise ValueError("saved TV record exceeds its bound")
        with self._lock:
            self._write_locked(raw)

    def load(self) -> SavedTvProfile | None:
        """The remembered TV, or None. Reading never consumes it."""
        with self._lock:
            return self._read_locked()

    def forget(self) -> None:
        with self._lock:
            self._clear_locked()

    def _target(self) -> Path:
        target = self._root / FILENAME
        if target.is_symlink():
            raise ValueError("saved TV record cannot be a symlink")
        return target

    def _read_locked(self) -> SavedTvProfile | None:
        target = self._target()
        try:
            descriptor = os.open(target, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except FileNotFoundError:
            return None
        except OSError:
            return None
        with os.fdopen(descriptor, "rb") as source:
            raw = source.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            return None
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
            return None
        stable_id = value.get("display_stable_id")
        edid_identified = value.get("edid_identified")
        if not isinstance(stable_id, str) or not STABLE_ID_RE.fullmatch(stable_id):
            return None
        if not isinstance(edid_identified, bool):
            # A record that cannot say how the TV was identified cannot say
            # whether resuming to it is safe, so it is not a record.
            return None
        return SavedTvProfile(
            display_stable_id=stable_id,
            edid_identified=edid_identified,
            label=_clean_label(value.get("label", "")),
        )

    def _clear_locked(self) -> None:
        try:
            self._target().unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass

    def _write_locked(self, raw: bytes) -> None:
        target = self._target()
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
