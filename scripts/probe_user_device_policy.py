"""Disposable device-filter fixture, never a GPU launch path.

Only opens /dev/zero and /dev/null read-only (including a proc-root alias).
Creates uniquely named, time-bounded transient services (one normally, two
with explicit --system-fixture under operator sudo); never changes
existing services, device permissions, namespaces, or plugin trial records.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid


CHILD = r'''
import errno, json, os, pathlib
def observe(path, read_zero=False):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
        try:
            if read_zero and os.read(fd, 1) != b"\0":
                return "unexpected_data"
        finally:
            os.close(fd)
        return "opened"
    except OSError as exc:
        return "denied" if exc.errno in (errno.EPERM, errno.EACCES) else "other_error"
status = dict(line.split(":", 1) for line in pathlib.Path("/proc/self/status").read_text().splitlines() if ":" in line)
print(json.dumps({
    "allowed_zero": observe("/dev/zero", True),
    "denied_null": observe("/dev/null"),
    "denied_null_alias": observe("/proc/self/root/dev/null"),
    "no_new_privileges": status["NoNewPrivs"].strip(),
    "capability_bound": status["CapBnd"].strip(),
    "user_namespace": str(pathlib.Path("/proc/self/ns/user").readlink()),
    "cgroup": pathlib.Path("/proc/self/cgroup").read_text().strip(),
    "effective_uid": os.geteuid(),
}))
'''

FIELDS = frozenset({"allowed_zero", "denied_null", "denied_null_alias",
                    "no_new_privileges", "capability_bound", "user_namespace", "cgroup", "effective_uid"})


def classify(baseline, restricted):
    """Observe actual open results; property acceptance is never enforcement."""
    if any(not isinstance(row, dict) or set(row) != FIELDS
           for row in (baseline, restricted)):
        return "inconclusive"
    if any(baseline[key] != "opened" for key in
           ("allowed_zero", "denied_null", "denied_null_alias")):
        return "inconclusive"
    if restricted["allowed_zero"] != "opened":
        return "inconclusive"
    if type(baseline["effective_uid"]) is not int or baseline["effective_uid"] <= 0 or type(restricted["effective_uid"]) is not int or baseline["effective_uid"] != restricted["effective_uid"]:
        return "inconclusive"
    if not isinstance(restricted["cgroup"], str) or not restricted["cgroup"] or restricted["cgroup"] == baseline["cgroup"]:
        return "inconclusive"
    denied = [restricted[key] for key in ("denied_null", "denied_null_alias")]
    if "opened" in denied:
        return "not_enforced"
    if denied != ["denied", "denied"]:
        return "inconclusive"
    context = ("no_new_privileges", "capability_bound", "user_namespace")
    if any(not isinstance(baseline[key], str) or not baseline[key]
           or baseline[key] != restricted[key] for key in context):
        return "context_changed"
    return "fixture_enforced"


def fixture_command(unit, *, restricted, system_uid=None):
    # No frontend paths, executable arguments, or existing unit names accepted.
    if not isinstance(unit, str) or not unit.startswith("regear-device-fixture-") or not unit.endswith(".service"):
        raise ValueError("invalid fixture unit")
    suffix = unit[len("regear-device-fixture-"):-len(".service")]
    if len(suffix) != 32 or any(c not in "0123456789abcdef" for c in suffix):
        raise ValueError("invalid fixture nonce")
    command = ["/usr/bin/systemd-run"]
    if system_uid is None:
        command.append("--user")
    else:
        if type(system_uid) is not int or not 0 < system_uid < 2**32 - 1:
            raise ValueError("non-root fixture user required")
        command.append("--property=User=" + str(system_uid))
    command += ["--quiet", "--wait", "--pipe", "--collect", "--service-type=exec",
        "--unit=" + unit, "--property=RuntimeMaxSec=5", "--property=TimeoutStopSec=2"]
    if restricted:
        command += ["--property=DevicePolicy=strict", "--property=DeviceAllow=/dev/zero r"]
    command += ["--", "/usr/bin/python3", "-I", "-c", CHILD]
    return command


def service_sample(*, restricted, system_uid=None):
    unit = "regear-device-fixture-" + uuid.uuid4().hex + ".service"
    command = fixture_command(unit, restricted=restricted, system_uid=system_uid)
    control = ["/usr/bin/systemctl"] + (["--user"] if system_uid is None else [])
    sample = None
    removed = False
    try:
        child = subprocess.run(command, capture_output=True, text=True, check=True, timeout=12)
        candidate = json.loads(child.stdout)
        if (isinstance(candidate, dict) and set(candidate) == FIELDS
                and isinstance(candidate.get("cgroup"), str)
                and candidate["cgroup"].endswith("/" + unit)
                and type(candidate.get("effective_uid")) is int
                and candidate["effective_uid"] == (os.geteuid() if system_uid is None else system_uid)):
            sample = candidate
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    finally:
        # Only our randomly named disposable service can be targeted here.
        # Existing session units and user@.service are never targeted.
        try:
            state = subprocess.run(control + ["show", unit, "--property=LoadState", "--value"],
                capture_output=True, text=True, timeout=3, check=False)
            if state.stdout.strip() != "not-found":
                subprocess.run(control + ["stop", unit], capture_output=True,
                    text=True, timeout=5, check=False)
            for _ in range(10):
                state = subprocess.run(control + ["show", unit, "--property=LoadState", "--value"],
                    capture_output=True, text=True, timeout=3, check=False)
                if state.stdout.strip() == "not-found":
                    removed = True
                    break
                time.sleep(0.1)
        except (OSError, subprocess.SubprocessError):
            pass
    return sample, removed


def run_probe(*, system_fixture=False):
    report = {"status": "inconclusive", "disconnect_clearance": False,
              "manager": "system" if system_fixture else "user"}
    if sys.platform != "linux":
        return dict(report, reason="unsupported_platform")
    system_uid = None
    if system_fixture:
        try:
            system_uid = int(os.environ["SUDO_UID"])
            if os.geteuid() != 0 or not 0 < system_uid < 2**32 - 1:
                raise ValueError("operator sudo session required")
        except (KeyError, ValueError):
            return dict(report, reason="operator_sudo_session_required")
    try:
        if system_fixture:
            before, removed = service_sample(restricted=False, system_uid=system_uid)
            if before is None or not removed:
                return dict(report, reason="baseline_unverified", transient_unit_removed=removed)
        else:
            baseline = subprocess.run(["/usr/bin/python3", "-I", "-c", CHILD],
                capture_output=True, text=True, check=True, timeout=5)
            before = json.loads(baseline.stdout)
        after, removed = service_sample(restricted=True, system_uid=system_uid)
        report["transient_unit_removed"] = removed
        report["status"] = classify(before, after) if removed else "inconclusive"
        if isinstance(after, dict) and isinstance(before, dict):
            # Keep identifiers and raw diagnostics local to the comparison.
            report["allowed_zero_readable"] = after.get("allowed_zero") == "opened"
            report["null_open_denied"] = after.get("denied_null") == "denied"
            report["null_alias_open_denied"] = after.get("denied_null_alias") == "denied"
            report["launch_context_preserved"] = all(before.get(key) == after.get(key)
                for key in ("no_new_privileges", "capability_bound", "user_namespace"))
    except (OSError, subprocess.SubprocessError, ValueError):
        report["reason"] = "fixture_probe_failed"
    return report


if __name__ == "__main__":
    if sys.argv[1:] not in ([], ["--system-fixture"]):
        raise SystemExit("Only --system-fixture is accepted")
    report = run_probe(system_fixture=bool(sys.argv[1:]))
    print(json.dumps(report, sort_keys=True))
    raise SystemExit(0 if report["status"] in ("fixture_enforced", "not_enforced", "context_changed") else 1)
