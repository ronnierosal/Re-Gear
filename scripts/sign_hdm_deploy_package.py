"""Sign a verified staged Re-Gear ZIP for the Ally developer deployment helper."""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from stage_decky_update import inspect_package, staged_filename


def openssl_binary() -> str:
    """Use OpenSSL when available, including the usual Git-for-Windows path."""
    found = shutil.which("openssl")
    if found:
        return found
    program_files = os.environ.get("ProgramFiles", r"C:\\Program Files")
    candidate = Path(program_files) / "Git" / "usr" / "bin" / "openssl.exe"
    if candidate.is_file():
        return str(candidate)
    raise RuntimeError("OpenSSL is unavailable")


def sign(package: Path, key: Path, output: Path | None = None) -> tuple[Path, str]:
    metadata = inspect_package(package)
    if not key.is_file() or key.is_symlink():
        raise ValueError("signing key is invalid")
    signature = output or package.with_name(f"{staged_filename(metadata)}.sig")
    if signature.exists():
        raise ValueError("signature destination already exists")
    result = subprocess.run(
        [openssl_binary(), "pkeyutl", "-sign", "-inkey", str(key.resolve()), "-rawin", "-in", str(package.resolve()), "-out", str(signature.resolve())],
        text=True, capture_output=True, timeout=30, check=False,
    )
    if result.returncode:
        raise RuntimeError("package signing failed")
    return signature, staged_filename(metadata)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        signature, filename = sign(args.package, args.key, args.output)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print(f"Signing failed: {error}", file=sys.stderr)
        return 1
    print(f"{filename} {signature}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
