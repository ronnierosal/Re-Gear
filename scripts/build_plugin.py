"""Create a deterministic Decky plugin archive from verified build outputs."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import zipfile
from collections.abc import Sequence
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_VERSION = str(
    json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"]
)
OUTPUT = ROOT / "out" / f"Re-Gear-{PACKAGE_VERSION}.zip"
PLUGIN_DIRECTORY = "Re-Gear"
BUILD_INFO_FILENAME = "build_info.json"
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
#: Produced by `pnpm build` and deliberately absent from version control, so
#: this script cannot find them in a fresh clone until that build has run.
GENERATED_BUILD_OUTPUTS = ("dist/index.js", "dist/index.js.map")
TOP_LEVEL_FILES = (
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "main.py",
    "package.json",
    "plugin.json",
)
# Reviewed read-only diagnostics only. Never recursively include scripts/: it
# also contains deployment and other mutating maintainer helpers.
READ_ONLY_PROBES = ("scripts/probe_safe_undock_readiness.py",)


def included_files() -> tuple[Path, ...]:
    paths = [ROOT / relative for relative in TOP_LEVEL_FILES]
    paths.extend(ROOT / relative for relative in READ_ONLY_PROBES)
    paths.append(ROOT / "dist" / "index.js")
    paths.append(ROOT / "dist" / "index.js.map")
    paths.append(ROOT / "bin" / "gamescope")
    paths.append(ROOT / "bin" / "steam-launcher")
    paths.extend(
        path
        for path in sorted((ROOT / "backend" / "hdm").rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    )
    return tuple(paths)


def archive_name(path: Path) -> str:
    """Place every file below Decky's single required plugin directory."""
    return f"{PLUGIN_DIRECTORY}/{path.relative_to(ROOT).as_posix()}"


def archive_mode(path: Path) -> int:
    return 0o100755 if path in (ROOT / "bin" / "gamescope", ROOT / "bin" / "steam-launcher") else 0o100644


def archive_bytes(path: Path) -> bytes:
    """Canonicalize the Linux launcher even in an older Windows checkout.

    Git attributes protect new checkouts, but do not rewrite existing CRLF
    files. Normalize only CRLF pairs, leaving all other source bytes intact;
    invalid shebangs or remaining bare CR bytes must fail closed.
    """
    content = path.read_bytes()
    if path in (ROOT / "bin" / "gamescope", ROOT / "bin" / "steam-launcher"):
        content = content.replace(b"\r\n", b"\n")
        validate_launcher_bytes(content)
    return content


def validate_launcher_bytes(content: bytes) -> None:
    """Check bytes, not universal-newline text, before Linux executes them."""
    if not content.startswith(b"#!/usr/bin/python3\n") or b"\r" in content:
        raise ValueError("Gamescope shim must have an LF-only /usr/bin/python3 shebang and body")


def _git_status(*args: str) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ("git", *args),
            cwd=ROOT,
            check=False,
            text=True,
            capture_output=True,
        )
    except OSError:
        return None


def source_revision() -> str:
    """Return a commit only when no tracked or untracked source is pending.

    ``included_files`` discovers every backend file below ``backend/hdm``. An
    untracked module could therefore enter an archive even when ``git diff`` is
    empty, so a full porcelain status check is required before the archive may
    claim a clean commit.
    """
    status = _git_status("status", "--porcelain=v1", "--untracked-files=all")
    if status is None or status.returncode != 0:
        return "unavailable"
    if _has_unexpected_worktree_changes(status.stdout):
        return "uncommitted"
    revision = _git_status("rev-parse", "HEAD")
    value = revision.stdout.strip() if revision is not None and revision.returncode == 0 else ""
    return value if REVISION_RE.fullmatch(value) else "unavailable"


def _has_unexpected_worktree_changes(status: str) -> bool:
    """Refuse a clean-commit claim for any pending change at all.

    The archive is built after ``pnpm build``.  That build used to rewrite the
    two tracked UI outputs, so this had to tolerate exactly those unstaged
    modifications or no CI archive could ever claim a commit.  ``dist/`` is now
    ignored rather than tracked, so the build no longer dirties anything and no
    exemption is needed: every tracked, staged, renamed, or untracked path is a
    hard refusal, because it may influence the package or make the claimed
    commit ambiguous.
    """
    return bool(status.strip())


def build_info_bytes(revision: str) -> bytes:
    """Encode deterministic archive-local provenance with no workstation data."""
    if revision not in {"uncommitted", "unavailable"} and not REVISION_RE.fullmatch(revision):
        raise ValueError("build revision is invalid")
    return json.dumps(
        {"schema_version": 1, "version": PACKAGE_VERSION, "revision": revision},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def main(argv: Sequence[str] = ()) -> int:
    argparse.ArgumentParser(
        prog="build_plugin.py",
        description=(
            "Package the built plugin and reserve its version. Takes no arguments; "
            "every invocation performs a real build and consumes a reservation."
        ),
    ).parse_args(argv)
    manifest = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))
    if manifest.get("flags") != ["root"]:
        raise SystemExit("Refusing to package a manifest without the root delivery flag")
    files = included_files()
    build_info = build_info_bytes(source_revision())
    missing = [path.relative_to(ROOT).as_posix() for path in files if not path.is_file()]
    if missing:
        message = "Missing package inputs: " + ", ".join(missing)
        # dist/ is generated, ignored, and absent from a fresh clone, so this is
        # the expected first failure for anyone who packages before building.
        # Name the command instead of leaving them to infer it from a path.
        if any(relative in GENERATED_BUILD_OUTPUTS for relative in missing):
            message += (
                "\nThe dist/ bundle is generated and is not in version control."
                "\nRun `pnpm build` first; this script packages what that produced."
            )
        raise SystemExit(message)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    from release_coordination import reserve
    if OUTPUT.exists():
        raise SystemExit("Refusing to overwrite existing ZIP: " + str(OUTPUT))
    reserve(PACKAGE_VERSION)
    with zipfile.ZipFile(OUTPUT, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            info = zipfile.ZipInfo(archive_name(path))
            info.date_time = (2026, 1, 1, 0, 0, 0)
            info.external_attr = archive_mode(path) << 16
            archive.writestr(info, archive_bytes(path), compress_type=zipfile.ZIP_DEFLATED)
        info = zipfile.ZipInfo(f"{PLUGIN_DIRECTORY}/{BUILD_INFO_FILENAME}")
        info.date_time = (2026, 1, 1, 0, 0, 0)
        info.external_attr = 0o100644 << 16
        archive.writestr(info, build_info, compress_type=zipfile.ZIP_DEFLATED)
    with zipfile.ZipFile(OUTPUT) as archive:
        names = archive.namelist()
        top_levels = {name.split("/", 1)[0] for name in names}
        if top_levels != {PLUGIN_DIRECTORY}:
            raise SystemExit("Decky archive must contain one top-level plugin directory")
        if f"{PLUGIN_DIRECTORY}/plugin.json" not in names:
            raise SystemExit("Decky archive is missing its nested plugin.json")
        if archive.read(f"{PLUGIN_DIRECTORY}/{BUILD_INFO_FILENAME}") != build_info:
            raise SystemExit("Decky archive build metadata did not round-trip")
        for launcher in ('gamescope', 'steam-launcher'):
            wrapper = archive.getinfo(f"{PLUGIN_DIRECTORY}/bin/{launcher}")
            validate_launcher_bytes(archive.read(wrapper))
            if (wrapper.external_attr >> 16) & 0o777 != 0o755:
                raise SystemExit("Session shim must be executable in the archive")
    print(OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
