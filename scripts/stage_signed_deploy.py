"""Stage one verified Re-Gear ZIP and its signed direct-deploy companion."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from remote_capture import validate_destination
from stage_decky_update import (
    connection_options,
    inspect_package,
    ssh_failure_code,
    stage_package,
    staged_filename,
)


def stage_signed_package(*, package: Path, signature: Path, host: str, user: str = "deck", port: int = 22, timeout_seconds: int = 15, identity_file: Path | None = None) -> dict[str, str]:
    metadata = inspect_package(package)
    filename = staged_filename(metadata)
    expected_signature = f"{filename}.sig"
    if not signature.is_file() or signature.is_symlink() or signature.name != expected_signature or signature.stat().st_size <= 0 or signature.stat().st_size > 16 * 1024:
        raise ValueError("signature path is invalid")
    staged = stage_package(package=package, host=host, user=user, port=port, timeout_seconds=timeout_seconds, identity_file=identity_file)
    destination = validate_destination(host, user, port)
    upload = subprocess.run(
        ["scp", *connection_options(timeout_seconds=timeout_seconds, identity_file=identity_file), "-P", str(port), str(signature.resolve()), f"{destination}:Downloads/{expected_signature}"],
        text=True, capture_output=True, timeout=timeout_seconds + 30, check=False,
    )
    if upload.returncode != 0:
        raise RuntimeError(f"signature staging failed: {ssh_failure_code(upload.returncode, upload.stderr)}")
    return {**staged, "signature": expected_signature}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("signature", type=Path)
    parser.add_argument("--host", required=True)
    parser.add_argument("--user", default="deck")
    parser.add_argument("--port", type=int, default=22)
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--identity-file", type=Path)
    args = parser.parse_args()
    try:
        print(stage_signed_package(package=args.package, signature=args.signature, host=args.host, user=args.user, port=args.port, timeout_seconds=args.timeout, identity_file=args.identity_file))
        return 0
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print(f"Signed staging failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
