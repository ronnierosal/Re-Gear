"""Capture a bounded read-only Re-Gear report from an Ally over SSH."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = Path(__file__).with_name("remote_capture_payload.py")
MAX_CAPTURE_BYTES = 512 * 1024
HOST_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")
USER_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
CODE_RE = re.compile(r"^[a-z0-9_.-]{1,96}$")
FORBIDDEN_KEYS = frozenset(
    {
        "address",
        "argv",
        "bdf",
        "command",
        "command_line",
        "environment",
        "hostname",
        "ip",
        "mac",
        "path",
        "pid",
        "ssid",
        "username",
    }
)


def ssh_failure_code(returncode: int, stderr: str) -> str:
    """Classify local OpenSSH failure without returning its untrusted output."""
    if returncode != 255:
        return "ssh.remote_command_failed"
    message = stderr.casefold()
    if "permission denied" in message:
        return "ssh.authentication_failed"
    if "host key verification failed" in message:
        return "ssh.host_key_unverified"
    if "could not resolve hostname" in message:
        return "ssh.host_unresolved"
    if "connection refused" in message:
        return "ssh.connection_refused"
    if "no route to host" in message or "network is unreachable" in message:
        return "ssh.network_unreachable"
    if "connection timed out" in message or "operation timed out" in message:
        return "ssh.connection_timed_out"
    return "ssh.connection_failed"


def validate_destination(host: str, user: str, port: int) -> str:
    if not HOST_RE.fullmatch(host):
        raise ValueError("host must be a DNS name or IPv4 address without options")
    if not USER_RE.fullmatch(user):
        raise ValueError("SSH user is invalid")
    if port < 1 or port > 65535:
        raise ValueError("SSH port is invalid")
    return f"{user}@{host}"


def build_ssh_argv(
    *,
    host: str,
    user: str,
    port: int,
    timeout_seconds: int,
    identity_file: Path | None = None,
    root_read_only: bool = False,
) -> list[str]:
    destination = validate_destination(host, user, port)
    if timeout_seconds < 1 or timeout_seconds > 60:
        raise ValueError("SSH timeout must be between 1 and 60 seconds")
    argv = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={timeout_seconds}",
        "-p",
        str(port),
    ]
    if identity_file is not None:
        if not identity_file.is_file():
            raise ValueError("SSH identity file does not exist")
        argv.extend(("-i", str(identity_file.resolve())))
    argv.append(destination)
    if root_read_only:
        argv.extend(("sudo", "-n", "/usr/bin/python3", "-"))
    else:
        argv.extend(("python3", "-"))
    return argv


def _validate_safe_shape(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).casefold()
            if (
                normalized in FORBIDDEN_KEYS
                or normalized.endswith("_path")
                or normalized.endswith("_pid")
                or normalized.endswith("_bdf")
            ):
                raise ValueError(f"capture contains forbidden field: {normalized}")
            _validate_safe_shape(item)
    elif isinstance(value, list):
        for item in value:
            _validate_safe_shape(item)


def _validate_wake_diagnostics(value: Any) -> None:
    """Accept only the documented aggregate, identity-free wake schema."""
    if value is None:
        return
    if not isinstance(value, dict) or set(value) != {
        "applicable",
        "bridge_wakeup",
        "function_wakeup",
        "function_runtime",
        "reason",
    }:
        raise ValueError("remote wake diagnostics schema is unsupported")
    if not isinstance(value["applicable"], bool):
        raise ValueError("remote wake diagnostics applicability is invalid")
    if value["bridge_wakeup"] not in {"enabled", "disabled", "unknown"}:
        raise ValueError("remote wake diagnostics bridge state is invalid")
    if not isinstance(value["reason"], str) or not CODE_RE.fullmatch(value["reason"]):
        raise ValueError("remote wake diagnostics reason is invalid")
    for key in ("function_wakeup", "function_runtime"):
        counts = value[key]
        expected_keys = (
            {"enabled", "disabled", "unknown"}
            if key == "function_wakeup"
            else {"active", "suspended", "unknown"}
        )
        if not isinstance(counts, dict) or set(counts) != expected_keys:
            raise ValueError("remote wake diagnostics aggregate is invalid")
        if any(type(count) is not int or count < 0 or count > 64 for count in counts.values()):
            raise ValueError("remote wake diagnostics count is invalid")


def parse_capture(
    stdout: str,
    payload_sha256: str,
    *,
    expected_privilege: str | None = None,
) -> dict[str, Any]:
    if len(stdout.encode("utf-8")) > MAX_CAPTURE_BYTES:
        raise ValueError("remote capture exceeds its size bound")
    try:
        value = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise ValueError("remote capture did not return one JSON object") from error
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("remote capture schema is unsupported")
    collector = value.get("collector")
    if not isinstance(collector, dict):
        raise ValueError("remote capture collector metadata is missing")
    if collector.get("read_only") is not True:
        raise ValueError("remote capture did not declare read-only execution")
    if collector.get("remote_files_written") is not False:
        raise ValueError("remote capture did not declare no remote file writes")
    if collector.get("transport") != "ssh_stdin":
        raise ValueError("remote capture transport is unsupported")
    privilege = collector.get("execution_privilege")
    if privilege not in {"unprivileged", "root_read_only"}:
        raise ValueError("remote capture privilege is unsupported")
    if expected_privilege is not None and privilege != expected_privilege:
        raise ValueError("remote capture did not run with the requested privilege")
    collector["payload_sha256"] = payload_sha256
    _validate_safe_shape(value)
    _validate_wake_diagnostics(value.get("wake_diagnostics"))
    return value


def collect_remote(
    *,
    host: str,
    user: str = "deck",
    port: int = 22,
    timeout_seconds: int = 10,
    identity_file: Path | None = None,
    root_read_only: bool = False,
) -> dict[str, Any]:
    payload = PAYLOAD.read_text(encoding="utf-8")
    payload_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    result = subprocess.run(
        build_ssh_argv(
            host=host,
            user=user,
            port=port,
            timeout_seconds=timeout_seconds,
            identity_file=identity_file,
            root_read_only=root_read_only,
        ),
        input=payload,
        text=True,
        capture_output=True,
        timeout=timeout_seconds + 20,
        check=False,
    )
    if result.returncode != 0:
        if root_read_only:
            raise RuntimeError(
                "non-interactive root read-only capture unavailable "
                f"(SSH status {result.returncode})"
            )
        raise RuntimeError(
            "read-only SSH capture failed: "
            f"{ssh_failure_code(result.returncode, result.stderr)}"
        )
    return parse_capture(
        result.stdout,
        payload_hash,
        expected_privilege=("root_read_only" if root_read_only else "unprivileged"),
    )


def save_capture(value: dict[str, Any], output: Path | None = None) -> Path:
    if output is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output = ROOT / "out" / "remote-captures" / f"capture-{stamp}.json"
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    if len(text.encode("utf-8")) > MAX_CAPTURE_BYTES:
        raise ValueError("encoded remote capture exceeds its size bound")
    with output.open("x", encoding="utf-8", newline="\n") as target:
        target.write(text)
    return output


def load_saved_capture(path: Path) -> dict[str, Any]:
    """Load a local capture only after its normal privacy/schema validation."""
    resolved = path.resolve()
    data = resolved.read_bytes()
    if len(data) > MAX_CAPTURE_BYTES:
        raise ValueError("saved capture exceeds its size bound")
    try:
        text = data.decode("utf-8")
        raw = json.loads(text)
        payload_hash = raw["collector"]["payload_sha256"]
    except (KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("saved capture is malformed") from error
    if (
        not isinstance(payload_hash, str)
        or len(payload_hash) != 64
        or any(char not in "0123456789abcdef" for char in payload_hash)
    ):
        raise ValueError("saved capture payload identity is invalid")
    return parse_capture(text, payload_hash)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--user", default="deck")
    parser.add_argument("--port", type=int, default=22)
    parser.add_argument("--timeout", type=int, default=10)
    parser.add_argument("--identity-file", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--root-read-only",
        action="store_true",
        help="run the fixed collector through non-interactive sudo",
    )
    args = parser.parse_args()
    try:
        value = collect_remote(
            host=args.host,
            user=args.user,
            port=args.port,
            timeout_seconds=args.timeout,
            identity_file=args.identity_file,
            root_read_only=args.root_read_only,
        )
        output = save_capture(value, args.output)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Capture failed: {error}", file=sys.stderr)
        return 1
    diagnostics = value.get("diagnostics") or {}
    snapshot = diagnostics.get("snapshot") or {}
    print(f"Saved read-only capture: {output}")
    print(
        "Observed: "
        f"support={snapshot.get('support_tier', 'unknown')} "
        f"game={snapshot.get('game_state', 'unknown')} "
        f"errors={len(value.get('errors', []))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
