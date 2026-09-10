"""Create a local-only Ed25519 signing keypair for the Ally deploy helper."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from sign_deploy_package import openssl_binary


def generate(directory: Path) -> tuple[Path, Path]:
    if directory.exists() or directory.is_symlink():
        raise ValueError("key directory already exists")
    directory.mkdir(mode=0o700, parents=True)
    private_key = directory / "private.pem"
    public_key = directory / "public.pem"
    try:
        for command in (
            [openssl_binary(), "genpkey", "-algorithm", "ED25519", "-out", str(private_key)],
            [openssl_binary(), "pkey", "-in", str(private_key), "-pubout", "-out", str(public_key)],
        ):
            result = subprocess.run(command, text=True, capture_output=True, timeout=30, check=False)
            if result.returncode:
                raise RuntimeError("key generation failed")
    except Exception:
        private_key.unlink(missing_ok=True)
        public_key.unlink(missing_ok=True)
        directory.rmdir()
        raise
    return private_key, public_key


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    try:
        private_key, public_key = generate(args.directory)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print(f"Key generation failed: {error}", file=sys.stderr)
        return 1
    print(f"private={private_key} public={public_key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
