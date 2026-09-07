"""Disposable regular-file visibility experiment; never opens GPU devices.

Not imported by the plugin or an executable session-isolation implementation.
The hard-link case intentionally demonstrates why hiding names is not access
revocation. No services, system configuration, or real device mounts are changed.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


CHILD = r'''
import json, pathlib, sys
root = pathlib.Path(sys.argv[1])
status = dict(line.split(":", 1) for line in pathlib.Path("/proc/self/status").read_text().splitlines() if ":" in line)
print(json.dumps({
    "allowed_visible": (root / "visible" / "internal").read_text() == "internal fixture",
    "external_name_hidden": not (root / "visible" / "external").exists(),
    "symlink_to_hidden_name_blocked": not (root / "external-symlink").exists(),
    "outside_hardlink_still_readable": (root / "external-hardlink").read_text() == "external fixture",
    "mount_namespace_changed": pathlib.Path("/proc/self/ns/mnt").readlink().as_posix() != sys.argv[2],
    "no_new_privileges": status.get("NoNewPrivs", "").strip() == "1",
}))
'''

EXPECTED_CHECKS = frozenset({
    "allowed_visible", "external_name_hidden", "symlink_to_hidden_name_blocked",
    "outside_hardlink_still_readable", "mount_namespace_changed", "no_new_privileges",
})


def fixture_checks_pass(checks: object) -> bool:
    return (
        isinstance(checks, dict) and set(checks) == EXPECTED_CHECKS
        and all(value is True for value in checks.values())
    )


def run_probe() -> dict:
    if sys.platform != "linux":
        return {"status": "unsupported_platform", "disconnect_clearance": False}
    result = {"status": "failed", "disconnect_clearance": False}
    with tempfile.TemporaryDirectory(prefix="regear-namespace-fixture-") as directory:
        root = Path(directory)
        visible = root / "visible"
        visible.mkdir()
        internal = visible / "internal"
        external = visible / "external"
        internal.write_text("internal fixture")
        external.write_text("external fixture")
        (root / "internal-source").write_text("internal fixture")
        (root / "external-symlink").symlink_to(external)
        os.link(external, root / "external-hardlink")
        namespace = str(Path("/proc/self/ns/mnt").readlink())
        try:
            child = subprocess.run(
                ["/usr/bin/bwrap", "--die-with-parent", "--unshare-user",
                 "--ro-bind", "/", "/", "--proc", "/proc",
                 "--tmpfs", str(visible),
                 "--ro-bind", str(root / "internal-source"), str(internal),
                 "--", "/usr/bin/python3", "-I", "-c", CHILD, str(root), namespace],
                capture_output=True, text=True, timeout=10, check=False,
                close_fds=True,
            )
            if child.returncode != 0:
                result["reason"] = "namespace_child_failed"
                result["child_exit_code"] = child.returncode
            else:
                checks = json.loads(child.stdout)
                result["checks"] = checks
                result["status"] = "fixture_passed" if fixture_checks_pass(checks) else "failed"
        except (OSError, subprocess.TimeoutExpired, ValueError):
            result["reason"] = "namespace_probe_unavailable"
        result["host_fixture_unchanged"] = (
            internal.read_text() == "internal fixture"
            and external.read_text() == "external fixture"
            and (root / "external-symlink").read_text() == "external fixture"
            and str(Path("/proc/self/ns/mnt").readlink()) == namespace
        )
        if not result["host_fixture_unchanged"]:
            result["status"] = "failed"
    result["temporary_fixture_removed"] = not root.exists()
    if not result["temporary_fixture_removed"]:
        result["status"] = "failed"
    return result


if __name__ == "__main__":
    report = run_probe()
    print(json.dumps(report, sort_keys=True))
    raise SystemExit(0 if report["status"] == "fixture_passed" else 1)
