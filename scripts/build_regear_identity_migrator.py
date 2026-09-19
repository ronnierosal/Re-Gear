#!/usr/bin/env python3
"""Build the deterministic, self-contained Re-Gear identity migrator.

The output is an executable Python zip application.  It contains the operator
CLI and the complete ``regear`` Python package from the same checkout so the
offline device migration cannot accidentally import a different installed
version.  Archive metadata is fixed and entries are sorted to make repeated
builds byte-for-byte identical.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import stat
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "migrate_regear_identity.py"
PACKAGE = ROOT / "backend" / "regear"
DEFAULT_OUTPUT = ROOT / "build" / "regear-migrate-identity"

SHEBANG = b"#!/usr/bin/python3\n"
FIXED_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
LAUNCHER = b'''"""Deterministic Re-Gear identity migrator entry point."""\nimport runpy\nrunpy.run_module("migrate_regear_identity", run_name="__main__")\n'''


def _sources() -> tuple[tuple[str, bytes], ...]:
    if not CLI.is_file() or not PACKAGE.is_dir():
        raise FileNotFoundError("identity migrator sources are unavailable")
    entries: list[tuple[str, bytes]] = [
        ("__main__.py", LAUNCHER),
        ("migrate_regear_identity.py", CLI.read_bytes()),
    ]
    for source in sorted(PACKAGE.rglob("*.py"), key=lambda path: path.as_posix()):
        relative = source.relative_to(ROOT / "backend").as_posix()
        entries.append((relative, source.read_bytes()))
    return tuple(entries)


def _write_entry(archive: zipfile.ZipFile, name: str, payload: bytes) -> None:
    info = zipfile.ZipInfo(name, FIXED_TIMESTAMP)
    info.create_system = 3
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    archive.writestr(info, payload, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def build(output: Path) -> Path:
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w+b", prefix=f".{output.name}.", dir=output.parent, delete=False
    ) as temporary:
        temporary_path = Path(temporary.name)
        try:
            temporary.write(SHEBANG)
            with zipfile.ZipFile(temporary, mode="a") as archive:
                for name, payload in _sources():
                    _write_entry(archive, name, payload)
            temporary.flush()
            os.fsync(temporary.fileno())
        except BaseException:
            temporary_path.unlink(missing_ok=True)
            raise
    try:
        os.chmod(temporary_path, 0o755)
        os.replace(temporary_path, output)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(build(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
