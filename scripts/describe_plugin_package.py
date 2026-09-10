"""Report what a built plugin archive says about itself, as JSON.

Read-only. This exists so a deployment can verify the archive it is about to
install instead of rebuilding one: ``build_plugin.py`` reserves a version exactly
once, so the archive you want to deploy is precisely the archive that can no
longer be regenerated.

Kept as a committed script rather than an inline ``python -c`` in the deployment
script, for two reasons. A multi-line program passed through PowerShell's native
argument handling is silently mangled by the quoting rules -- that was a real
defect, not a hypothetical -- and a file can be tested directly.

It answers only what the archive asserts plus the hash of its bytes. It makes no
judgement about whether the archive may be installed; the caller compares these
values against the checkout it intends to deploy from.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path
from typing import Sequence

BUILD_INFO_SUFFIX = "build_info.json"
# A provenance record is tiny. Anything larger is not one, and decoding it would
# mean parsing attacker-influenced bytes for no reason.
MAX_BUILD_INFO_BYTES = 64 * 1024


def describe(path: Path) -> dict[str, object]:
    """Return the archive's declared provenance and the hash of its bytes."""
    data = path.read_bytes()
    with zipfile.ZipFile(path) as archive:
        entries = [
            info
            for info in archive.infolist()
            if info.filename.endswith(BUILD_INFO_SUFFIX)
        ]
        if len(entries) != 1:
            raise ValueError(
                f"expected exactly one {BUILD_INFO_SUFFIX}, found {len(entries)}"
            )
        entry = entries[0]
        if entry.file_size > MAX_BUILD_INFO_BYTES:
            raise ValueError(f"{entry.filename} is too large to be a build record")
        try:
            record = json.loads(archive.read(entry))
        except json.JSONDecodeError as error:
            raise ValueError(f"{entry.filename} is not valid JSON") from error
    if not isinstance(record, dict):
        raise ValueError("build record is not an object")
    return {
        # Reported as the archive states them, including absent as "". The caller
        # decides whether that is acceptable; guessing a default here would let a
        # record with no revision pass a comparison against something.
        "revision": str(record.get("revision", "")),
        "version": str(record.get("version", "")),
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
    }


def main(argv: Sequence[str] = ()) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="the .zip to describe")
    arguments = parser.parse_args(list(argv) or None)
    try:
        described = describe(arguments.archive)
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        # Categorical and on stderr, so a caller parsing stdout as JSON never
        # mistakes an error for a description.
        print(f"Cannot describe {arguments.archive}: {error}", file=sys.stderr)
        return 1
    print(json.dumps(described, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
