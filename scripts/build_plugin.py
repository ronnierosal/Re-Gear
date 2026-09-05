"""Create a deterministic Decky plugin archive from verified build outputs."""

from __future__ import annotations

import json
import re
import subprocess
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_VERSION = str(
    json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"]
)
OUTPUT = ROOT / "out" / f"Re-Gear-{PACKAGE_VERSION}.zip"
PLUGIN_DIRECTORY = "HandheldDockMode"
BUILD_INFO_FILENAME = "build_info.json"
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
GENERATED_BUILD_OUTPUTS = frozenset(("dist/index.js", "dist/index.js.map"))
TOP_LEVEL_FILES = (
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "main.py",
    "package.json",
    "plugin.json",
)


def included_files() -> tuple[Path, ...]:
    paths = [ROOT / relative for relative in TOP_LEVEL_FILES]
    paths.append(ROOT / "dist" / "index.js")
    paths.append(ROOT / "dist" / "index.js.map")
    paths.append(ROOT / "bin" / "gamescope")
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
    return 0o100755 if path == ROOT / "bin" / "gamescope" else 0o100644


def archive_bytes(path: Path) -> bytes:
    """Canonicalize the Linux launcher even in an older Windows checkout.

    Git attributes protect new checkouts, but do not rewrite existing CRLF
    files. Normalize only CRLF pairs, leaving all other source bytes intact;
    invalid shebangs or remaining bare CR bytes must fail closed.
    """
    content = path.read_bytes()
    if path == ROOT / "bin" / "gamescope":
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
    """Accept only the two tracked UI outputs produced immediately before packaging.

    The archive is built after ``pnpm build``.  That build deterministically
    refreshes these tracked outputs in CI, so treating those exact unstaged
    changes as source dirtiness would make every CI archive unverifiable.
    Every other tracked, staged, renamed, or untracked path remains a hard
    refusal: it may influence the package or make the claimed commit ambiguous.
    """
    for line in status.splitlines():
        if not line.startswith(" M ") or line[3:] not in GENERATED_BUILD_OUTPUTS:
            return True
    return False


def build_info_bytes(revision: str) -> bytes:
    """Encode deterministic archive-local provenance with no workstation data."""
    if revision not in {"uncommitted", "unavailable"} and not REVISION_RE.fullmatch(revision):
        raise ValueError("build revision is invalid")
    return json.dumps(
        {"schema_version": 1, "version": PACKAGE_VERSION, "revision": revision},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def main() -> int:
    manifest = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))
    if manifest.get("flags") != ["root"]:
        raise SystemExit("Refusing to package a manifest without the root delivery flag")
    files = included_files()
    build_info = build_info_bytes(source_revision())
    missing = [str(path.relative_to(ROOT)) for path in files if not path.is_file()]
    if missing:
        raise SystemExit("Missing package inputs: " + ", ".join(missing))
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
        wrapper = archive.getinfo(f"{PLUGIN_DIRECTORY}/bin/gamescope")
        validate_launcher_bytes(archive.read(wrapper))
        if (wrapper.external_attr >> 16) & 0o777 != 0o755:
            raise SystemExit("Gamescope shim must be executable in the archive")
    print(OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
