"""Constrained subprocess mechanisms with exact, shell-free command shapes."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from ...ports.presentation_activation import UserServiceOperation
from ...ports.system_power import PowerOffResult


@dataclass(frozen=True, slots=True)
class CommandResult:
    argv: tuple[str, ...]
    returncode: int | None
    stdout: str
    stderr: str
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.error


@dataclass(frozen=True, slots=True)
class ManagedProcessStatus:
    running: bool
    error: str = ""


@dataclass(frozen=True, slots=True)
class UserServiceCommandResult:
    operation: UserServiceOperation
    ok: bool
    returncode: int | None = None
    output: str = ""
    error_code: str = ""


@dataclass(frozen=True, slots=True)
class AudioCommandResult:
    ok: bool
    output: bytes = b""
    code: str = ""


class PipeWireCommandRunner:
    """Run only a bounded dump or numeric default-sink mutation as Gamescope user."""

    RUNUSER = "/usr/bin/runuser"
    ENV = "/usr/bin/env"
    PW_DUMP = "/usr/bin/pw-dump"
    WPCTL = "/usr/bin/wpctl"
    MAX_OUTPUT_BYTES = 1024 * 1024
    SAFE_USERNAME = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")

    def __init__(self, timeout_seconds: float = 5.0, effective_uid=None) -> None:
        self._timeout_seconds = timeout_seconds
        self._effective_uid = effective_uid or getattr(os, "geteuid", lambda: -1)

    def dump(self, user) -> AudioCommandResult:
        return self._run(user, (self.PW_DUMP,), capture=True)

    def set_default(self, user, object_id: int) -> AudioCommandResult:
        if type(object_id) is not int or object_id <= 0:
            return AudioCommandResult(False, code="audio.object_id_invalid")
        return self._run(
            user, (self.WPCTL, "set-default", str(object_id)), capture=False
        )

    def _run(
        self, user, command: tuple[str, ...], *, capture: bool
    ) -> AudioCommandResult:
        if self._effective_uid() != 0:
            return AudioCommandResult(False, code="audio.root_required")
        if not self.SAFE_USERNAME.fullmatch(user.username) or user.uid <= 0:
            return AudioCommandResult(False, code="audio.user_invalid")
        argv = (
            self.RUNUSER,
            "-u",
            user.username,
            "--",
            self.ENV,
            f"XDG_RUNTIME_DIR=/run/user/{user.uid}",
            f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{user.uid}/bus",
            *command,
        )
        try:
            completed = subprocess.run(
                argv,
                capture_output=True,
                check=False,
                shell=False,
                timeout=self._timeout_seconds,
                env={"LANG": "C", "LC_ALL": "C", "PATH": "/usr/bin:/bin"},
            )
        except subprocess.TimeoutExpired:
            return AudioCommandResult(False, code="audio.command_timeout")
        except (OSError, subprocess.SubprocessError):
            return AudioCommandResult(False, code="audio.command_unavailable")
        output = bytes(completed.stdout or b"")
        error = bytes(completed.stderr or b"")
        if len(output) + len(error) > self.MAX_OUTPUT_BYTES:
            return AudioCommandResult(False, code="audio.output_too_large")
        if completed.returncode != 0:
            return AudioCommandResult(False, code="audio.command_failed")
        return AudioCommandResult(True, output if capture else b"")


class SleepInhibitorProcess:
    """Own the exact systemd-inhibit process used by the G1 sleep guard."""

    STARTUP_GRACE_SECONDS = 0.25
    STOP_TIMEOUT_SECONDS = 2.0
    PYTHON = "/usr/bin/python"
    EXCLUDED_ENVIRONMENT = frozenset(
        {"LD_LIBRARY_PATH", "LD_PRELOAD", "PYTHONHOME", "PYTHONPATH"}
    )

    def __init__(self) -> None:
        self._process: subprocess.Popen[str] | None = None

    @staticmethod
    def argv() -> tuple[str, ...]:
        guard = Path(__file__).with_name("inhibitor_guard.py")
        return (SleepInhibitorProcess.PYTHON, str(guard), "--guard", str(os.getpid()))

    @classmethod
    def environment(cls) -> dict[str, str]:
        return {
            key: value
            for key, value in os.environ.items()
            if key not in cls.EXCLUDED_ENVIRONMENT
        }

    def start(self) -> ManagedProcessStatus:
        status = self.status()
        if status.running:
            return status
        argv = self.argv()
        try:
            process = subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                env=self.environment(),
                shell=False,
                text=True,
            )
            self._process = process
            try:
                process.wait(timeout=self.STARTUP_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                return ManagedProcessStatus(True)
            detail = (process.stderr.read() if process.stderr else "").strip()[:512]
            self._process = None
            return ManagedProcessStatus(
                False,
                detail or f"systemd-inhibit exited with status {process.returncode}",
            )
        except (OSError, subprocess.SubprocessError) as error:
            self._process = None
            return ManagedProcessStatus(False, str(error))

    def stop(self) -> ManagedProcessStatus:
        process = self._process
        self._process = None
        if process is None or process.poll() is not None:
            return ManagedProcessStatus(False)
        try:
            process.terminate()
            process.wait(timeout=self.STOP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=self.STOP_TIMEOUT_SECONDS)
        except OSError as error:
            return ManagedProcessStatus(False, str(error))
        return ManagedProcessStatus(False)

    def status(self) -> ManagedProcessStatus:
        process = self._process
        if process is None:
            return ManagedProcessStatus(False)
        returncode = process.poll()
        if returncode is None:
            return ManagedProcessStatus(True)
        detail = (process.stderr.read() if process.stderr else "").strip()[:512]
        self._process = None
        return ManagedProcessStatus(
            False,
            detail or f"systemd-inhibit exited with status {returncode}",
        )


class ReadOnlyCommandRunner:
    """Run a small allowlist without a shell or mutation-shaped arguments."""

    SYSTEMCTL_SCOPE_QUERY = (
        "--user",
        "list-units",
        "--type=scope",
        "--state=running",
        "--plain",
        "--no-legend",
        "--no-pager",
    )
    SAFE_USERNAME = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*[$]?")
    FORBIDDEN_ARGUMENTS = frozenset(
        {
            "daemon-reload",
            "disable",
            "edit",
            "enable",
            "isolate",
            "kill",
            "mask",
            "reenable",
            "reload",
            "reset-failed",
            "restart",
            "set-default",
            "set-environment",
            "set-property",
            "start",
            "stop",
            "unmask",
            "unset-environment",
        }
    )

    def __init__(self, timeout_seconds: float = 5.0) -> None:
        self._timeout_seconds = timeout_seconds

    @classmethod
    def validate(cls, argv: Sequence[str]) -> tuple[str, ...]:
        normalized = tuple(str(part) for part in argv)
        if not normalized:
            raise ValueError("Command argv must not be empty")
        forbidden = cls.FORBIDDEN_ARGUMENTS.intersection(
            part.lower() for part in normalized[1:]
        )
        if forbidden:
            raise ValueError(
                "Mutation-shaped command arguments are forbidden: "
                + ", ".join(sorted(forbidden))
            )
        if (
            Path(normalized[0]).name.lower() == "systemctl"
            and normalized[1:] == cls.SYSTEMCTL_SCOPE_QUERY
        ):
            return normalized
        if cls._is_user_systemctl_scope_query(normalized):
            return normalized
        raise ValueError("Command is not approved as a read-only discovery query")

    @classmethod
    def _is_user_systemctl_scope_query(cls, argv: tuple[str, ...]) -> bool:
        prefix_length = 8
        if len(argv) != prefix_length + len(cls.SYSTEMCTL_SCOPE_QUERY):
            return False
        runuser, user_flag, username, separator, env, runtime, bus, systemctl = argv[:8]
        if (
            runuser != "/usr/bin/runuser"
            or user_flag != "-u"
            or not cls.SAFE_USERNAME.fullmatch(username)
            or separator != "--"
            or env != "/usr/bin/env"
            or systemctl != "/usr/bin/systemctl"
            or argv[8:] != cls.SYSTEMCTL_SCOPE_QUERY
        ):
            return False
        runtime_match = re.fullmatch(r"XDG_RUNTIME_DIR=/run/user/([0-9]+)", runtime)
        bus_match = re.fullmatch(
            r"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/([0-9]+)/bus", bus
        )
        return bool(
            runtime_match
            and bus_match
            and runtime_match.group(1) == bus_match.group(1)
        )

    def run(self, argv: Sequence[str]) -> CommandResult:
        normalized = self.validate(argv)
        try:
            completed = subprocess.run(
                normalized,
                capture_output=True,
                check=False,
                shell=False,
                text=True,
                timeout=self._timeout_seconds,
            )
        except (OSError, subprocess.SubprocessError) as error:
            return CommandResult(normalized, None, "", "", str(error))
        return CommandResult(
            normalized,
            completed.returncode,
            completed.stdout,
            completed.stderr,
        )


class UserServiceCommandRunner:
    """Execute only HDM's fixed Gamescope user-service operations."""

    SYSTEMCTL = "/usr/bin/systemctl"
    RUNUSER = "/usr/bin/runuser"
    ENV = "/usr/bin/env"
    MAX_OUTPUT_BYTES = 4096
    SAFE_USERNAME = ReadOnlyCommandRunner.SAFE_USERNAME
    SUFFIXES = {
        UserServiceOperation.DAEMON_RELOAD: ("daemon-reload",),
        UserServiceOperation.VERIFY_GAMESCOPE_UNIT: (
            "show",
            "gamescope-session.service",
            "--property=LoadState",
            "--value",
            "--no-pager",
        ),
        UserServiceOperation.RESTART_GAMESCOPE_SESSION: (
            "--no-block",
            "restart",
            "gamescope-session.target",
        ),
    }
    CLEAN_ENVIRONMENT = {
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": "/usr/bin:/bin",
    }

    def __init__(
        self,
        timeout_seconds: float = 8.0,
        effective_uid=None,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._effective_uid = effective_uid or getattr(os, "geteuid", lambda: -1)

    @classmethod
    def argv(
        cls,
        operation: UserServiceOperation,
        *,
        uid: int,
        username: str,
    ) -> tuple[str, ...]:
        if type(uid) is not int or uid <= 0:
            raise ValueError("Gamescope user uid is invalid")
        if not cls.SAFE_USERNAME.fullmatch(username):
            raise ValueError("Gamescope username is invalid")
        try:
            suffix = cls.SUFFIXES[operation]
        except (KeyError, TypeError) as error:
            raise ValueError("User-service operation is not approved") from error
        return (
            cls.RUNUSER,
            "-u",
            username,
            "--",
            cls.ENV,
            f"XDG_RUNTIME_DIR=/run/user/{uid}",
            f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus",
            cls.SYSTEMCTL,
            "--user",
            *suffix,
        )

    def run(
        self,
        operation: UserServiceOperation,
        *,
        uid: int,
        username: str,
    ) -> UserServiceCommandResult:
        if self._effective_uid() != 0:
            return UserServiceCommandResult(operation, False, error_code="root_required")
        argv = self.argv(operation, uid=uid, username=username)
        try:
            completed = subprocess.run(
                argv,
                capture_output=True,
                check=False,
                shell=False,
                text=False,
                timeout=self._timeout_seconds,
                env=dict(self.CLEAN_ENVIRONMENT),
            )
        except subprocess.TimeoutExpired:
            return UserServiceCommandResult(operation, False, error_code="timeout")
        except (OSError, subprocess.SubprocessError):
            return UserServiceCommandResult(
                operation, False, error_code="command_unavailable"
            )
        output = bytes(completed.stdout or b"")
        error = bytes(completed.stderr or b"")
        if len(output) + len(error) > self.MAX_OUTPUT_BYTES:
            return UserServiceCommandResult(
                operation,
                False,
                returncode=completed.returncode,
                error_code="output_too_large",
            )
        decoded = output.decode("utf-8", errors="replace").strip()
        if completed.returncode != 0:
            return UserServiceCommandResult(
                operation,
                False,
                returncode=completed.returncode,
                error_code="nonzero_exit",
            )
        if (
            operation is UserServiceOperation.VERIFY_GAMESCOPE_UNIT
            and decoded != "loaded"
        ):
            return UserServiceCommandResult(
                operation,
                False,
                returncode=completed.returncode,
                output=decoded,
                error_code="unit_not_loaded",
            )
        return UserServiceCommandResult(
            operation,
            True,
            returncode=completed.returncode,
            output=decoded,
        )


class SystemPowerCommandRunner:
    """Queue only the fixed, ordinary system power-off operation."""

    SYSTEMCTL = "/usr/bin/systemctl"
    COMMAND = (SYSTEMCTL, "--no-block", "poweroff")
    CLEAN_ENVIRONMENT = {
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": "/usr/bin:/bin",
    }

    def __init__(self, timeout_seconds: float = 5.0, effective_uid=None) -> None:
        self._timeout_seconds = timeout_seconds
        self._effective_uid = effective_uid or getattr(os, "geteuid", lambda: -1)

    def request_poweroff(self) -> PowerOffResult:
        if self._effective_uid() != 0:
            return PowerOffResult(False, "safe_disconnect.root_required")
        try:
            completed = subprocess.run(
                self.COMMAND,
                capture_output=True,
                check=False,
                shell=False,
                text=False,
                timeout=self._timeout_seconds,
                env=dict(self.CLEAN_ENVIRONMENT),
            )
        except subprocess.TimeoutExpired:
            return PowerOffResult(False, "safe_disconnect.poweroff_timeout")
        except (OSError, subprocess.SubprocessError):
            return PowerOffResult(False, "safe_disconnect.poweroff_unavailable")
        if completed.returncode != 0:
            return PowerOffResult(False, "safe_disconnect.poweroff_failed")
        return PowerOffResult(
            True, "safe_disconnect.poweroff_request_accepted_unverified"
        )


class SteamOsTdpCommandRunner:
    """Fixed SteamOSManager session-bus operations; callers own device-range gates.

    A successful set only means the property command succeeded. Callers must
    independently read back the setting before claiming it was applied.
    """

    BUSCTL = "/usr/bin/busctl"
    RUNUSER = "/usr/bin/runuser"
    ENV = "/usr/bin/env"
    SERVICE = "com.steampowered.SteamOSManager1"
    OBJECT_PATH = "/com/steampowered/SteamOSManager1"
    INTERFACE = "com.steampowered.SteamOSManager1.TdpLimit1"
    MAX_OUTPUT_BYTES = 4096
    TIMEOUT_SECONDS = 8.0
    UINT32_MAX = (1 << 32) - 1
    SAFE_USERNAME = re.compile(r"[A-Za-z_][A-Za-z0-9_-]{0,31}[$]?")
    UNIQUE_OWNER = re.compile(r":[0-9]{1,10}\.[0-9]{1,10}")

    def __init__(self, effective_uid=None) -> None:
        self._effective_uid = effective_uid or getattr(os, "geteuid", lambda: -1)

    def read(self, user) -> CommandResult:
        return self._run(
            user,
            (
                "get-property", self.SERVICE, self.OBJECT_PATH, self.INTERFACE,
                "TdpLimit", "TdpLimitMin", "TdpLimitMax",
            ),
            capture=True,
        )

    def owner(self, user) -> CommandResult:
        return self._run(
            user,
            (
                "call", "org.freedesktop.DBus", "/org/freedesktop/DBus",
                "org.freedesktop.DBus", "GetNameOwner", "s", self.SERVICE,
            ),
            capture=True,
        )

    def set_limit(self, user, watts: int, *, owner: str = "") -> CommandResult:
        # An omitted owner fails categorically instead of falling back to SERVICE.
        if type(owner) is not str or not self.UNIQUE_OWNER.fullmatch(owner):
            return CommandResult((), None, "", "", "tdp.owner_invalid")
        if type(watts) is not int or not 0 < watts <= self.UINT32_MAX:
            return CommandResult((), None, "", "", "tdp.limit_invalid")
        return self._run(
            user,
            (
                "set-property", owner, self.OBJECT_PATH, self.INTERFACE,
                "TdpLimit", "u", str(watts),
            ),
            capture=False,
        )

    def _run(self, user, suffix: tuple[str, ...], *, capture: bool) -> CommandResult:
        from ...ports.presentation_activation import GamescopeUserContext

        if (
            not isinstance(user, GamescopeUserContext)
            or type(user.uid) is not int
            or not 0 < user.uid < self.UINT32_MAX
            or type(user.username) is not str
            or not self.SAFE_USERNAME.fullmatch(user.username)
            or user.runtime_directory != Path(f"/run/user/{user.uid}")
            or user.bus_path != Path(f"/run/user/{user.uid}/bus")
        ):
            return CommandResult((), None, "", "", "tdp.user_invalid")
        effective_uid = self._effective_uid()
        if type(effective_uid) is not int or effective_uid not in (0, user.uid):
            return CommandResult((), None, "", "", "tdp.uid_mismatch")
        prefix = (
            (self.RUNUSER, "-u", user.username, "--") if effective_uid == 0 else ()
        )
        argv = (
            *prefix,
            self.ENV,
            f"XDG_RUNTIME_DIR=/run/user/{user.uid}",
            f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{user.uid}/bus",
            self.BUSCTL,
            "--user",
            "--auto-start=no",
            "--allow-interactive-authorization=no",
            "--timeout=2s",
            *suffix,
        )
        try:
            completed = subprocess.run(
                argv,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                check=False,
                shell=False,
                text=False,
                timeout=self.TIMEOUT_SECONDS,
                env={"LANG": "C", "LC_ALL": "C", "PATH": "/usr/bin:/bin"},
            )
        except subprocess.TimeoutExpired:
            return CommandResult(argv, None, "", "", "tdp.command_timeout")
        except (OSError, subprocess.SubprocessError):
            return CommandResult(argv, None, "", "", "tdp.command_unavailable")
        output = bytes(completed.stdout or b"")
        error = bytes(completed.stderr or b"")
        if len(output) + len(error) > self.MAX_OUTPUT_BYTES:
            return CommandResult(argv, completed.returncode, "", "", "tdp.output_too_large")
        if completed.returncode != 0:
            return CommandResult(argv, completed.returncode, "", "", "tdp.command_failed")
        try:
            decoded = output.decode("ascii") if capture else ""
        except UnicodeDecodeError:
            return CommandResult(argv, completed.returncode, "", "", "tdp.output_invalid")
        return CommandResult(argv, completed.returncode, decoded, "")
