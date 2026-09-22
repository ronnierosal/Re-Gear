"""Reading and atomically writing a game's configuration file.

The store knows about bytes and durability; it does not know what a profile is.
A write replaces the whole file in one step and preserves the file's existing
permission bits, so a game keeps reading a file it owns rather than one Re-Gear
re-created with a fresh mode.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path


MAX_CONFIG_BYTES = 2 * 1024 * 1024
ENCODING = "utf-8"


class ConfigIoError(RuntimeError):
    """The file could not be read or written. Never raised past the service."""


class ConfigChangedError(ConfigIoError):
    """The target changed between the decision to write and the write itself.

    A subclass of ConfigIoError so no caller can accidentally ignore it, but
    distinct so the service can report a conflict rather than a failure -- and
    so it never triggers a rollback over bytes that are not Re-Gear's.
    """


@dataclass(frozen=True, slots=True)
class ConfigBytes:
    payload: bytes
    text: str


class GraphicsConfigStore:
    """Byte-level access to one configuration file at a time."""

    def read(self, path: Path) -> ConfigBytes:
        try:
            if path.is_symlink():
                raise ConfigIoError("refusing to read a configuration through a symlink")
            if not path.is_file():
                raise ConfigIoError("configuration is not a regular file")
            if path.stat().st_size > MAX_CONFIG_BYTES:
                raise ConfigIoError("configuration is too large to manage")
            payload = path.read_bytes()
        except OSError as error:
            raise ConfigIoError(f"configuration is unreadable: {error}") from error
        try:
            text = payload.decode(ENCODING)
        except UnicodeDecodeError as error:
            raise ConfigIoError(f"configuration is not {ENCODING} text: {error}") from error
        return ConfigBytes(payload=payload, text=text)

    def write(self, path: Path, text: str, expected: bytes | None = None) -> bytes:
        """Atomically replace the file with this text; return the bytes written.

        When ``expected`` is given, the target is re-read immediately before the
        replacement and the write is refused if it no longer holds those bytes.
        """
        payload = text.encode(ENCODING)
        if len(payload) > MAX_CONFIG_BYTES:
            raise ConfigIoError("refusing to write an oversized configuration")
        if path.is_symlink():
            raise ConfigIoError("refusing to write a configuration through a symlink")
        if expected is not None and not path.exists():
            # Checked before the permission stat so a target that vanished is
            # reported as the change it is, rather than as an unwritable file.
            raise ConfigChangedError(
                "the configuration no longer exists, so it was not recreated"
            )
        try:
            mode = path.stat().st_mode & 0o7777
        except OSError as error:
            raise ConfigIoError(f"configuration is not writable: {error}") from error
        directory = path.parent
        temporary = directory / f".{path.name}.{secrets.token_hex(8)}.tmp"
        try:
            with open(temporary, "wb") as output:
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            os.chmod(temporary, mode)
            if expected is not None:
                # The last look before the point of no return. A target that
                # vanished counts as changed; this write does not recreate it.
                if not path.exists():
                    raise ConfigChangedError(
                        "the configuration no longer exists, so it was not recreated"
                    )
                current = path.read_bytes()
                if current != expected:
                    raise ConfigChangedError(
                        "the configuration changed between the decision to write "
                        "and the write itself"
                    )
            os.replace(temporary, path)
            handle = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(handle)
            finally:
                os.close(handle)
        except ConfigChangedError:
            self._discard(temporary)
            raise
        except OSError as error:
            self._discard(temporary)
            raise ConfigIoError(f"atomic configuration write failed: {error}") from error
        return payload

    @staticmethod
    def _discard(temporary: Path) -> None:
        try:
            temporary.unlink()
        except OSError:
            pass
