"""Read-only SteamOS collector sent to the Ally over SSH stdin.

This file is not installed as an HDM production command.  The local capture
wrapper streams it to ``python3 -`` and it writes no remote files.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


SCHEMA_VERSION = 1
PLUGIN_ROOT = Path("/home/deck/homebrew/plugins/Re-Gear")
BUILD_INFO_FILENAME = "build_info.json"
REVISION_RE = frozenset("0123456789abcdef")
CRITICAL_FILES = (
    Path("plugin.json"),
    Path("package.json"),
    Path("main.py"),
    Path("dist/index.js"),
    Path("backend/hdm/domain/models.py"),
    Path("backend/hdm/profiles/gpd_g1.py"),
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(64 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _read_text(path: Path, limit: int = 256) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit].strip()
    except OSError:
        return ""


def _plugin_version() -> str:
    try:
        value = json.loads((PLUGIN_ROOT / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return "unknown"
    version = value.get("version", "unknown") if isinstance(value, dict) else "unknown"
    return str(version)[:32]


def _build_info() -> dict[str, object]:
    """Read only the archive-local public provenance label, never a Git checkout."""
    fallback = {"schema_version": 1, "version": _plugin_version(), "revision": "unavailable"}
    try:
        value = json.loads((PLUGIN_ROOT / BUILD_INFO_FILENAME).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return fallback
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        return fallback
    version = value.get("version")
    revision = value.get("revision")
    if (
        not isinstance(version, str)
        or not version
        or len(version) > 32
        or version != _plugin_version()
    ):
        return fallback
    if revision in {"uncommitted", "unavailable"}:
        public_revision = revision
    elif (
        isinstance(revision, str)
        and len(revision) == 40
        and set(revision) <= REVISION_RE
    ):
        public_revision = revision[:12]
    else:
        return fallback
    return {"schema_version": 1, "version": version, "revision": public_revision}


def _critical_hashes() -> dict[str, str]:
    rows: dict[str, str] = {}
    for relative in CRITICAL_FILES:
        path = PLUGIN_ROOT / relative
        try:
            rows[relative.as_posix()] = _sha256(path) if path.is_file() else "missing"
        except OSError:
            rows[relative.as_posix()] = "unreadable"
    return rows


def _process_health() -> dict[str, int]:
    counts = {"gamescope": 0, "steam": 0, "pluginloader": 0}
    proc = Path("/proc")
    try:
        rows = tuple(proc.iterdir())
    except OSError:
        return counts
    for row in rows:
        if not row.name.isdigit():
            continue
        name = _read_text(row / "comm", 64).casefold()
        if name.startswith("gamescope"):
            counts["gamescope"] += 1
        elif name == "steam":
            counts["steam"] += 1
        elif name == "pluginloader":
            counts["pluginloader"] += 1
    return counts


def _diagnostics() -> dict[str, Any]:
    backend = PLUGIN_ROOT / "backend"
    if not backend.is_dir():
        raise RuntimeError("plugin_backend_missing")
    sys.path.insert(0, str(backend))
    from hdm.adapters.steamos.version_info import SteamOsVersionDiscovery
    from hdm.api import DiagnosticsApi
    from hdm.application.support_bundle import SupportBundleService

    report = DiagnosticsApi().get_snapshot()
    snapshot = report.get("snapshot", {})
    if isinstance(snapshot, dict):
        guard = snapshot.get("sleep_guard", {})
        required = guard.get("required") is True if isinstance(guard, dict) else False
        snapshot["sleep_guard"] = {
            "required": required,
            "active": None,
            "confidence": "unknown",
            "reason": "Standalone capture does not observe the Decky-owned lease.",
            "error": "plugin_lifecycle_guard_not_observed",
        }
    versions = SteamOsVersionDiscovery().scan()
    bundle = SupportBundleService().build(
        report,
        (),
        {
            "hdm": _plugin_version(),
            "decky": "unknown",
            "steamos": versions.steamos,
            "kernel": versions.kernel,
        },
    )
    payload = dict(bundle.payload)
    checks = [dict(row) for row in payload.get("profile_checks", [])]
    for row in checks:
        if row.get("code") == "sleep_guard.active":
            row["result"] = "not_observed"
    payload["profile_checks"] = checks
    return payload


def _wake_diagnostics() -> dict[str, Any]:
    """Inspect exact G1 PCI wake-capability attributes without changing them."""
    backend = PLUGIN_ROOT / "backend"
    if not backend.is_dir():
        raise RuntimeError("plugin_backend_missing")
    sys.path.insert(0, str(backend))
    from hdm.adapters.steamos.drm import DrmDiscovery
    from hdm.adapters.steamos.pci import PciUsb4Discovery
    from hdm.adapters.steamos.wake_diagnostics import WakeDiagnosticsDiscovery
    from hdm.profiles.gpd_g1 import match_gpd_g1

    pci = PciUsb4Discovery()
    g1 = match_gpd_g1(DrmDiscovery().scan(), pci.scan_pci(), pci.scan_usb4())
    return WakeDiagnosticsDiscovery().observe(
        g1.root_bdf if g1.verified else "",
        g1.pci_functions if g1.verified else (),
    ).to_public_dict()


def _safe_value(code: str, operation: Callable[[], Any], errors: list[str]) -> Any:
    try:
        return operation()
    except Exception:
        errors.append(f"{code}_failed")
        return None


def collect() -> dict[str, Any]:
    errors: list[str] = []
    is_root = getattr(os, "geteuid", lambda: -1)() == 0
    boot_id = _read_text(Path("/proc/sys/kernel/random/boot_id"), 128)
    uptime_text = _read_text(Path("/proc/uptime"), 128).split()
    try:
        uptime_seconds = int(float(uptime_text[0])) if uptime_text else None
    except ValueError:
        uptime_seconds = None
        errors.append("uptime_parse_failed")

    return {
        "schema_version": SCHEMA_VERSION,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "collector": {
            "read_only": True,
            "remote_files_written": False,
            "transport": "ssh_stdin",
            "execution_privilege": (
                "root_read_only" if is_root else "unprivileged"
            ),
            "limitations": ["plugin_lifecycle_sleep_guard_not_observed"]
            + (
                []
                if is_root
                else ["unprivileged_gamescope_evidence_may_be_incomplete"]
            ),
        },
        "system": {
            "boot_id_sha256": (
                hashlib.sha256(boot_id.encode("utf-8")).hexdigest()[:16]
                if boot_id
                else "unknown"
            ),
            "uptime_seconds": uptime_seconds,
            "kernel": platform.release()[:120],
            "process_health": _process_health(),
        },
        "plugin": {
            "present": PLUGIN_ROOT.is_dir(),
            "version": _plugin_version(),
            "build": _build_info(),
            "critical_file_sha256": _critical_hashes(),
        },
        "diagnostics": _safe_value("diagnostics", _diagnostics, errors),
        "wake_diagnostics": _safe_value(
            "wake_diagnostics", _wake_diagnostics, errors
        ),
        "errors": errors,
    }


if __name__ == "__main__":
    print(json.dumps(collect(), sort_keys=True, ensure_ascii=True))
