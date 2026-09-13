"""Constrained subprocess mechanisms with exact, shell-free command shapes."""

from __future__ import annotations

import os
import math
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from ...ports.presentation_activation import UserServiceOperation
from ...ports.device_authorization import DeviceEnrollmentResult
from ...ports.system_power import PowerOffResult
from ...ports.tdp import TdpDispatchGuard, TdpDispatchRejected


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
    """Bounded dump and numeric audio operations as the authenticated session user."""

    RUNUSER = "/usr/bin/runuser"
    ENV = "/usr/bin/env"
    PW_DUMP = "/usr/bin/pw-dump"
    WPCTL = "/usr/bin/wpctl"
    MAX_OUTPUT_BYTES = 1024 * 1024
    SAFE_USERNAME = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")

    def __init__(self, timeout_seconds: float = 5.0, effective_uid=None) -> None:
        self._timeout_seconds = timeout_seconds
        self._effective_uid = effective_uid or getattr(os, "geteuid", lambda: -1)

    def dump(self, user, *, timeout_seconds: float | None = None) -> AudioCommandResult:
        return self._run(user, (self.PW_DUMP,), capture=True, timeout_seconds=timeout_seconds)

    def set_default(self, user, object_id: int) -> AudioCommandResult:
        if type(object_id) is not int or object_id <= 0:
            return AudioCommandResult(False, code="audio.object_id_invalid")
        return self._run(
            user, (self.WPCTL, "set-default", str(object_id)), capture=False
        )

    def set_profile(self, user, object_id: int, profile_index: int, *, timeout_seconds=None) -> AudioCommandResult:
        # Authority belongs to the separate journaled audio trial, not to this
        # numeric command adapter. No profile names or arbitrary argv enter it.
        if (type(object_id) is not int or not 0 < object_id < 2**32
                or type(profile_index) is not int or not 0 <= profile_index < 2**32):
            return AudioCommandResult(False, code="audio.profile_identity_invalid")
        return self._run(user, (self.WPCTL, "set-profile", str(object_id), str(profile_index)),
                         capture=False, timeout_seconds=timeout_seconds)

    def _run(
        self, user, command: tuple[str, ...], *, capture: bool,
        timeout_seconds: float | None = None,
    ) -> AudioCommandResult:
        if (timeout_seconds is not None and (type(timeout_seconds) not in (int, float)
                or not math.isfinite(timeout_seconds) or timeout_seconds <= 0)):
            return AudioCommandResult(False, code="audio.deadline_expired")
        timeout = self._timeout_seconds if timeout_seconds is None else min(self._timeout_seconds, timeout_seconds)
        if not 0 < timeout <= self._timeout_seconds:
            return AudioCommandResult(False, code="audio.deadline_expired")
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
                timeout=timeout,
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
    #: The guard reads no environment of its own and execs systemd-inhibit by
    #: absolute path; systemd-inhibit reaches the system bus over its fixed
    #: socket. Nothing inherited is required, so this matches the allowlist the
    #: three other runners in this file use rather than chasing each new
    #: influential variable as it appears.
    CLEAN_ENVIRONMENT = {
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": "/usr/bin:/bin",
    }

    def __init__(self) -> None:
        self._process: subprocess.Popen[str] | None = None

    @staticmethod
    def argv() -> tuple[str, ...]:
        guard = Path(__file__).with_name("inhibitor_guard.py")
        return (SleepInhibitorProcess.PYTHON, str(guard), "--guard", str(os.getpid()))

    @classmethod
    def environment(cls) -> dict[str, str]:
        return dict(cls.CLEAN_ENVIRONMENT)

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
                detail or f"sleep inhibitor guard exited with status {process.returncode}",
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
            detail or f"sleep inhibitor guard exited with status {returncode}",
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
    SYSTEMCTL = "/usr/bin/systemctl"
    #: Matched as an exact absolute path. A basename comparison accepted any
    #: systemctl reachable through an inherited PATH, e.g. /tmp/evil/systemctl.
    APPROVED_BINARIES = frozenset({SYSTEMCTL})
    CLEAN_ENVIRONMENT = {
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": "/usr/bin:/bin",
    }
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
            normalized[0] in cls.APPROVED_BINARIES
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
                env=dict(self.CLEAN_ENVIRONMENT),
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
    """Execute only Re-Gear's fixed Gamescope user-service operations."""

    SYSTEMCTL = "/usr/bin/systemctl"
    RUNUSER = "/usr/bin/runuser"
    ENV = "/usr/bin/env"
    MAX_OUTPUT_BYTES = 4096
    SAFE_USERNAME = ReadOnlyCommandRunner.SAFE_USERNAME
    SUFFIXES = {
        UserServiceOperation.OBSERVE_FILTER_GAMESCOPE: (
            'show', 'gamescope-session.service', '--property=MainPID',
            '--property=InvocationID', '--property=ActiveState', '--property=ControlGroup', '--no-pager',
        ),
        UserServiceOperation.OBSERVE_FILTER_STEAM: (
            'show', 'steam-launcher.service', '--property=MainPID',
            '--property=InvocationID', '--property=ActiveState', '--property=ControlGroup', '--no-pager',
        ),
        UserServiceOperation.INSPECT_STEAM_UNIT: (
            'show', 'steam-launcher.service', '--property=LoadState',
            '--property=FragmentPath', '--property=DropInPaths',
            '--property=ExecStart', '--property=Environment', '--no-pager',
        ),
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
        UserServiceOperation.RESTART_WIREPLUMBER: (
            "--no-block",
            "restart",
            "wireplumber.service",
        ),
        UserServiceOperation.RESTART_PIPEWIRE: (
            "--no-block",
            "restart",
            "pipewire.service",
        ),
        #: Deliberately blocking, unlike every restart above it: a caller that
        #: is about to watch for something with the session down needs it
        #: actually down first. Present for one explicitly-selected recovery
        #: strategy, not for a proven gap mechanism -- see the note on the
        #: operation in `regear.ports.presentation_activation`.
        UserServiceOperation.STOP_GAMESCOPE_SESSION: (
            "stop",
            "gamescope-session.target",
        ),
        UserServiceOperation.START_GAMESCOPE_SESSION: (
            "--no-block",
            "start",
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
        timeout_seconds: float | None = None,
    ) -> UserServiceCommandResult:
        if self._effective_uid() != 0:
            return UserServiceCommandResult(operation, False, error_code="root_required")
        timeout = self._timeout_seconds
        if timeout_seconds is not None:
            if (type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds)
                    or timeout_seconds <= 0):
                return UserServiceCommandResult(operation, False, error_code="deadline_expired")
            timeout = min(timeout, timeout_seconds)
        argv = self.argv(operation, uid=uid, username=username)
        try:
            completed = subprocess.run(
                argv,
                capture_output=True,
                check=False,
                shell=False,
                text=False,
                timeout=timeout,
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

    def set_limit(self, user, watts: int, *, owner: str = "", dispatch_guard: TdpDispatchGuard | None = None) -> CommandResult:
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
            dispatch_guard=dispatch_guard,
        )

    def _run(self, user, suffix: tuple[str, ...], *, capture: bool, dispatch_guard: TdpDispatchGuard | None = None) -> CommandResult:
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
        if dispatch_guard is not None:
            try:
                allowed = dispatch_guard() is True
            except Exception:
                allowed = False
            if not allowed:
                raise TdpDispatchRejected("tdp.dispatch_rejected")
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


class BoltDeviceAuthorizationRunner:
    """Grant trust to exactly one named Thunderbolt device through `boltd`.

    Two grants, because the player is told two different things. `authorize`
    trusts the device for this attachment and stores nothing, so the next plug
    asks again -- that is the agreed scope. `enroll` stores it with the `auto`
    policy, which is what Desktop Mode already did to the dock that works
    today; it is retained but is not reachable from production wiring, because
    remembering a DMA grant is a decision nobody has approved.

    `boltd` is the system's authorization owner, so this asks it rather than
    writing `authorized` in sysfs: a direct write would leave `boltd`'s
    enrolment database disagreeing with the kernel about which devices are
    trusted, and the player would meet the prompt again on a later plug with no
    way to make it stop.

    The argv is fixed apart from the UUID, which is the only caller-supplied
    value that reaches a command line in this feature. It is matched against an
    exact pattern and refused otherwise -- not quoted, not escaped, refused.
    With `shell=False` a stray argument could not be reinterpreted anyway, but
    the boundary should not depend on that being remembered.

    `--policy auto` matches what Desktop Mode already stores for a device
    enrolled there, so a device trusted from Game Mode behaves identically
    afterwards. `--chain` is deliberately NOT passed: it authorizes parent
    devices as well, which would trust hardware the player was never shown.

    A zero exit is reported as accepted, never as verified. The caller re-reads
    the device's state to learn whether it actually became trusted.
    """

    BOLTCTL = "/usr/bin/boltctl"
    #: `boltctl list` reports this shape, and nothing else is a device id.
    UUID = re.compile(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    )
    CLEAN_ENVIRONMENT = {
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": "/usr/bin:/bin",
    }

    def __init__(self, timeout_seconds: float = 15.0, effective_uid=None) -> None:
        self._timeout_seconds = timeout_seconds
        self._effective_uid = effective_uid or getattr(os, "geteuid", lambda: -1)

    @classmethod
    def argv(cls, uuid: str) -> tuple[str, ...]:
        """The remembered grant. Unchanged, and deliberately still here.

        Not reachable from production wiring -- the delivery facade refuses the
        `enroll` action unless a caller opts in explicitly -- but kept because
        it is the grant Desktop Mode performs, and deleting it would mean
        rebuilding it from memory the day the remembered choice is approved.
        """
        if type(uuid) is not str or cls.UUID.fullmatch(uuid) is None:
            raise ValueError("device authorization uuid is invalid")
        return (cls.BOLTCTL, "enroll", "--policy", "auto", uuid)

    @classmethod
    def authorize_argv(cls, uuid: str) -> tuple[str, ...]:
        """The one-shot grant: trust this device now, remember nothing.

        `boltctl authorize` leaves the enrolment database alone, so the next
        plug asks again. That repetition is the agreed product scope, not a
        defect in it -- the player is trusting a device for this attachment,
        and nothing on disk outlives the cable.

        No `--policy`: policy is a property of a STORED device, and passing one
        here would be asking `boltd` to remember a decision the player was told
        would not be remembered. No `--chain`, for the same reason it is absent
        from enrolment: it would authorize parent devices the player was never
        shown.

        The UUID is validated identically and refused rather than quoted.
        """
        if type(uuid) is not str or cls.UUID.fullmatch(uuid) is None:
            raise ValueError("device authorization uuid is invalid")
        return (cls.BOLTCTL, "authorize", uuid)

    def enroll(self, uuid: str) -> DeviceEnrollmentResult:
        return self._grant(self.argv, uuid, "enroll")

    def authorize(self, uuid: str) -> DeviceEnrollmentResult:
        return self._grant(self.authorize_argv, uuid, "authorize")

    def _grant(self, build, uuid: str, action: str) -> DeviceEnrollmentResult:
        """Run one fixed-argv grant, and report what happened to the COMMAND.

        Shared by both grants on purpose: two copies of a subprocess boundary
        are two places to remember `shell=False`, the clean environment and the
        timeout, and the second copy is the one that gets missed. `action` only
        names the outcome codes -- it never reaches the command line, which is
        built by `build` from a fixed tuple.
        """
        try:
            argv = build(uuid)
        except ValueError:
            return DeviceEnrollmentResult(
                False, "device_authorization.uuid_invalid"
            )
        if self._effective_uid() != 0:
            return DeviceEnrollmentResult(
                False, "device_authorization.root_required"
            )
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
            return DeviceEnrollmentResult(
                False, f"device_authorization.{action}_timeout"
            )
        except (OSError, subprocess.SubprocessError):
            return DeviceEnrollmentResult(
                False, f"device_authorization.{action}_unavailable"
            )
        if completed.returncode != 0:
            return DeviceEnrollmentResult(
                False, f"device_authorization.{action}_failed"
            )
        return DeviceEnrollmentResult(
            True, f"device_authorization.{action}_accepted_unverified"
        )
