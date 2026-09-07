"""Stage one provenance-checked HDM ZIP for Decky's native installer.

This developer tool uploads a verified HDM package to the fixed Decky user's
home directory (``/home/deck/``), then reads back its digest. It deliberately does *not*
call an undocumented Decky endpoint, replace a live plugin directory, reload
Decky, or alter Gamescope, sleep, hardware, or the current session.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

from remote_capture import ssh_failure_code, validate_destination


PLUGIN_DIRECTORY = "HandheldDockMode"
BUILD_INFO_NAME = f"{PLUGIN_DIRECTORY}/build_info.json"
PACKAGE_NAME = f"{PLUGIN_DIRECTORY}/package.json"
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
VERSION_RE = re.compile(r"^[0-9]+(?:\.[0-9]+){2}(?:[-+][A-Za-z0-9.-]+)?$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_PACKAGE_BYTES = 32 * 1024 * 1024


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(64 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_package(package: Path) -> dict[str, str]:
    """Fail closed unless this is one complete, provenance-bearing HDM ZIP."""
    path = package.resolve()
    if not path.is_file() or path.is_symlink() or path.suffix.casefold() != ".zip":
        raise ValueError("package path is invalid")
    if path.stat().st_size <= 0 or path.stat().st_size > MAX_PACKAGE_BYTES:
        raise ValueError("package size is invalid")
    try:
        with zipfile.ZipFile(path) as archive:
            names = tuple(archive.namelist())
            if not names or {name.split("/", 1)[0] for name in names} != {PLUGIN_DIRECTORY}:
                raise ValueError("package layout is invalid")
            if any(name.startswith("/") or ".." in Path(name).parts for name in names):
                raise ValueError("package contains unsafe paths")
            build: Any = json.loads(archive.read(BUILD_INFO_NAME).decode("utf-8"))
            manifest: Any = json.loads(archive.read(PACKAGE_NAME).decode("utf-8"))
    except (OSError, KeyError, UnicodeDecodeError, ValueError, zipfile.BadZipFile) as error:
        raise ValueError("package metadata is invalid") from error
    if (
        not isinstance(build, dict)
        or set(build) != {"schema_version", "version", "revision"}
        or build.get("schema_version") != 1
        or not isinstance(build.get("version"), str)
        or not VERSION_RE.fullmatch(build["version"])
        or not isinstance(build.get("revision"), str)
        or not REVISION_RE.fullmatch(build["revision"])
        or not isinstance(manifest, dict)
        or manifest.get("version") != build["version"]
    ):
        raise ValueError("package provenance is invalid")
    return {"version": build["version"], "revision": build["revision"], "sha256": sha256(path)}


def staged_filename(metadata: dict[str, str]) -> str:
    version = metadata.get("version", "")
    revision = metadata.get("revision", "")
    if not VERSION_RE.fullmatch(version) or not REVISION_RE.fullmatch(revision):
        raise ValueError("package metadata is invalid")
    return f"HDM-update-{version}-{revision[:12]}.zip"


def connection_options(*, timeout_seconds: int, identity_file: Path | None) -> list[str]:
    if timeout_seconds < 1 or timeout_seconds > 60:
        raise ValueError("SSH timeout must be between 1 and 60 seconds")
    options = ["-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes", "-o", f"ConnectTimeout={timeout_seconds}"]
    if identity_file is not None:
        if not identity_file.is_file() or identity_file.is_symlink():
            raise ValueError("SSH identity file is invalid")
        options.extend(("-i", str(identity_file.resolve())))
    return options


def _validate_filename(filename: str) -> None:
    if not re.fullmatch(r"HDM-update-[A-Za-z0-9.+-]+-[0-9a-f]{12}\.zip", filename):
        raise ValueError("remote filename is invalid")


def build_scp_argv(*, package: Path, host: str, user: str, port: int, timeout_seconds: int, identity_file: Path | None, filename: str) -> list[str]:
    destination = validate_destination(host, user, port)
    _validate_filename(filename)
    return ["scp", *connection_options(timeout_seconds=timeout_seconds, identity_file=identity_file), "-P", str(port), str(package.resolve()), f"{destination}:{filename}"]


def build_hash_argv(*, host: str, user: str, port: int, timeout_seconds: int, identity_file: Path | None, filename: str) -> list[str]:
    destination = validate_destination(host, user, port)
    _validate_filename(filename)
    return ["ssh", *connection_options(timeout_seconds=timeout_seconds, identity_file=identity_file), "-p", str(port), destination, "sha256sum", "--", f"/home/{user}/{filename}"]


def parse_remote_digest(stdout: str, *, user: str, filename: str) -> str:
    rows = stdout.splitlines()
    expected_path = f"/home/{user}/{filename}"
    if len(rows) != 1:
        raise ValueError("remote package verification returned an unexpected response")
    parts = rows[0].split(maxsplit=1)
    if len(parts) != 2 or parts[1].removeprefix(" ") != expected_path or not SHA256_RE.fullmatch(parts[0]):
        raise ValueError("remote package verification returned an unexpected response")
    return parts[0]


def stage_package(*, package: Path, host: str, user: str = "deck", port: int = 22, timeout_seconds: int = 15, identity_file: Path | None = None) -> dict[str, str]:
    """Upload and verify bytes only; native Decky installation remains external."""
    metadata = inspect_package(package)
    filename = staged_filename(metadata)
    upload = subprocess.run(build_scp_argv(package=package, host=host, user=user, port=port, timeout_seconds=timeout_seconds, identity_file=identity_file, filename=filename), text=True, capture_output=True, timeout=timeout_seconds + 30, check=False)
    if upload.returncode != 0:
        raise RuntimeError(f"package staging failed: {ssh_failure_code(upload.returncode, upload.stderr)}")
    verify = subprocess.run(build_hash_argv(host=host, user=user, port=port, timeout_seconds=timeout_seconds, identity_file=identity_file, filename=filename), text=True, capture_output=True, timeout=timeout_seconds + 30, check=False)
    if verify.returncode != 0:
        raise RuntimeError(f"remote package verification failed: {ssh_failure_code(verify.returncode, verify.stderr)}")
    if parse_remote_digest(verify.stdout, user=user, filename=filename) != metadata["sha256"]:
        raise RuntimeError("remote package checksum mismatch")
    return {"state": "staged", "filename": filename, "revision": metadata["revision"][:12], "version": metadata["version"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("--host", required=True)
    parser.add_argument("--user", default="deck")
    parser.add_argument("--port", type=int, default=22)
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--identity-file", type=Path)
    args = parser.parse_args()
    try:
        result = stage_package(package=args.package, host=args.host, user=args.user, port=args.port, timeout_seconds=args.timeout, identity_file=args.identity_file)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Staging failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
