"""Developer-only, unprivileged previous-boot shutdown evidence over SSH stdin.

Only aggregate evidence leaves the remote process. A previous boot, journal
EOF, or an unload checkpoint never proves physical power-off completed.
"""

from __future__ import annotations

import json
import os
import re
import selectors
import subprocess
import time


MAX_ROWS = 2000
MAX_BYTES = 4 * 1024 * 1024
MAX_REPORT_BYTES = 16 * 1024
MAX_ELAPSED_MS = 24 * 60 * 60 * 1000
JOURNAL_TIMEOUT_SECONDS = 10
JOURNAL_ARGV = (
    "/usr/bin/journalctl", "--boot=-1", "--lines=2000", "--output=json",
    "--output-fields=MESSAGE,__MONOTONIC_TIMESTAMP,_TRANSPORT,_COMM,_SYSTEMD_UNIT",
    "--no-pager", "--quiet",
)
CATEGORIES = (
    "kernel_blocked_task", "amdgpu_blocked_task", "pciehp_blocked_task",
    "amdgpu_shutdown_stack", "pciehp_shutdown_stack", "aer_error",
    "xhci_error", "systemd_stop_timeout", "session_exit_126",
)
STAGES = (
    "unload_started", "observers_stopped", "sleep_guard_release_started",
    "sleep_guard_released", "unload_complete", "observer_stop_failed",
    "sleep_guard_release_failed",
)
STATUSES = (
    "observed", "no_previous_journal", "permission_denied", "journal_unavailable",
    "timed_out", "size_limit", "malformed_journal",
)
CHECKPOINT_RE = re.compile(
    r"HDM shutdown checkpoint: stage=(" + "|".join(STAGES)
    + r") elapsed_ms=([0-9]{1,9})(?:$|\s)"
)


def empty_report(status: str) -> dict:
    return {
        "schema_version": 1,
        "collector": {
            "read_only": True, "remote_files_written": False,
            "transport": "ssh_stdin", "execution_privilege": "unprivileged",
            "source": "previous_boot_journal", "selection": "bounded_tail",
            "installed_revision": "unknown", "event_scope": "plugin_unload_not_poweroff",
        },
        "status": status,
        "physical_poweroff": "unknown",
        "coverage": {
            "rows_examined": 0, "tail_limit_reached": False,
            "malformed_rows": 0, "span_ms": None,
        },
        "symptoms": {name: 0 for name in CATEGORIES},
        "checkpoints": {
            stage: {"count": 0, "last_elapsed_ms": None} for stage in STAGES
        },
    }


def classify_journal(data: bytes) -> dict:
    if len(data) > MAX_BYTES:
        return empty_report("size_limit")
    if not data.strip():
        return empty_report("no_previous_journal")
    lines = data.splitlines()
    if len(lines) > MAX_ROWS:
        return empty_report("size_limit")
    report = empty_report("observed")
    coverage = report["coverage"]
    coverage["tail_limit_reached"] = len(lines) == MAX_ROWS
    timestamps = []
    for line in lines:
        coverage["rows_examined"] += 1
        try:
            row = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            coverage["malformed_rows"] += 1
            continue
        if not isinstance(row, dict) or not isinstance(row.get("MESSAGE"), str):
            coverage["malformed_rows"] += 1
            continue
        stamp = row.get("__MONOTONIC_TIMESTAMP")
        if isinstance(stamp, str) and re.fullmatch(r"[0-9]{1,18}", stamp):
            timestamps.append(int(stamp))
        message = row["MESSAGE"]
        lower = message.lower()
        matched = set()
        if row.get("_TRANSPORT") == "kernel":
            blocked = "blocked for more than" in lower
            if blocked:
                matched.add("kernel_blocked_task")
                for component in ("amdgpu", "pciehp"):
                    if component in lower:
                        matched.add(component + "_blocked_task")
            if any(term in lower for term in ("amdgpu_device_fini", "amdgpu_device_ip_fini")):
                matched.add("amdgpu_shutdown_stack")
            if any(term in lower for term in ("pciehp_disable_slot", "pciehp_unconfigure_device")):
                matched.add("pciehp_shutdown_stack")
            if "aer:" in lower and any(term in lower for term in ("error", "failed", "failure")):
                matched.add("aer_error")
            if "xhci" in lower and any(term in lower for term in ("error", "failed", "timeout", "not responding", "dead")):
                matched.add("xhci_error")
        if row.get("_COMM") == "systemd":
            if (re.search(r"stop-sig(?:term|kill)'? timed out", lower)
                    or "stop job timed out" in lower or "timed out stopping" in lower):
                matched.add("systemd_stop_timeout")
            if ("gamescope" in lower or "session" in lower) and re.search(r"status=126(?:/|\b)", lower):
                matched.add("session_exit_126")
        for category in matched:
            report["symptoms"][category] += 1
        if row.get("_SYSTEMD_UNIT") == "plugin_loader.service":
            checkpoint = CHECKPOINT_RE.search(message)
            if checkpoint and int(checkpoint[2]) <= MAX_ELAPSED_MS:
                entry = report["checkpoints"][checkpoint[1]]
                entry["count"] += 1
                entry["last_elapsed_ms"] = int(checkpoint[2])
    if timestamps:
        coverage["span_ms"] = min(MAX_ELAPSED_MS, (max(timestamps) - min(timestamps)) // 1000)
    if coverage["malformed_rows"]:
        report["status"] = "malformed_journal"
    return report


def read_journal() -> tuple[int, bytes, bytes, str]:
    """Bound both pipes in remote memory; terminate only our own journal reader."""
    try:
        process = subprocess.Popen(
            JOURNAL_ARGV, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            shell=False, env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
        )
    except OSError:
        return 1, b"", b"", "journal_unavailable"
    chunks = {"stdout": bytearray(), "stderr": bytearray()}
    deadline = time.monotonic() + JOURNAL_TIMEOUT_SECONDS
    status = ""
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ, "stdout")
            selector.register(process.stderr, selectors.EVENT_READ, "stderr")
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    status = "timed_out"
                    break
                for key, _ in selector.select(remaining):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    if sum(map(len, chunks.values())) + len(chunk) > MAX_BYTES:
                        status = "size_limit"
                        break
                    chunks[key.data].extend(chunk)
                if status:
                    break
            if not status:
                try:
                    process.wait(timeout=max(0.01, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    status = "timed_out"
    finally:
        if process.poll() is None:
            process.kill()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            status = "timed_out"
        process.stdout.close()
        process.stderr.close()
    return (process.returncode if process.returncode is not None else 1,
            bytes(chunks["stdout"]), bytes(chunks["stderr"]), status)


def collect_previous_boot() -> dict:
    # No sudo/root fallback: unavailable journal access remains explicit.
    if os.geteuid() == 0:
        return empty_report("permission_denied")
    code, stdout, stderr, status = read_journal()
    if status:
        return empty_report(status)
    error = stderr.lower()
    if any(term in error for term in (b"permission denied", b"not seeing messages", b"insufficient permissions")):
        return empty_report("permission_denied")
    if code != 0:
        if any(term in error for term in (b"no journal files", b"no such boot", b"no persistent journal", b"failed to look up boot")):
            return empty_report("no_previous_journal")
        return empty_report("journal_unavailable")
    return classify_journal(stdout)


# LOCAL SSH CLIENT
import argparse
import hashlib
import sys
from pathlib import Path

if __package__:
    from .remote_capture import build_ssh_argv, ssh_failure_code
else:
    from remote_capture import build_ssh_argv, ssh_failure_code


def remote_payload() -> str:
    source = Path(__file__).read_text(encoding="utf-8")
    remote, separator, _ = source.partition("\n# LOCAL SSH CLIENT\n")
    if not separator:
        raise ValueError("fixed remote payload boundary is missing")
    return remote + "\nprint(json.dumps(collect_previous_boot(), sort_keys=True))\n"


def validate_report(stdout: str) -> dict:
    if len(stdout.encode("utf-8")) > MAX_REPORT_BYTES:
        raise ValueError("shutdown report exceeds size bound")
    try:
        value = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise ValueError("shutdown report is malformed") from error
    template = empty_report("observed")
    if not isinstance(value, dict) or set(value) != set(template):
        raise ValueError("shutdown report schema is unsupported")
    if (type(value["schema_version"]) is not int or value["schema_version"] != 1
            or value["collector"] != template["collector"]
            or value["physical_poweroff"] != "unknown"
            or value["status"] not in STATUSES):
        raise ValueError("shutdown report provenance or status is invalid")
    def bounded_count(item):
        return type(item) is int and 0 <= item <= MAX_ROWS
    symptoms = value["symptoms"]
    if not isinstance(symptoms, dict) or set(symptoms) != set(CATEGORIES) or not all(map(bounded_count, symptoms.values())):
        raise ValueError("shutdown symptom counts are invalid")
    coverage = value["coverage"]
    if not isinstance(coverage, dict) or set(coverage) != set(template["coverage"]):
        raise ValueError("shutdown coverage is invalid")
    if (not bounded_count(coverage["rows_examined"])
            or not bounded_count(coverage["malformed_rows"])
            or coverage["malformed_rows"] > coverage["rows_examined"]
            or type(coverage["tail_limit_reached"]) is not bool):
        raise ValueError("shutdown coverage counts are invalid")
    def elapsed(item):
        return item is None or (type(item) is int and 0 <= item <= MAX_ELAPSED_MS)
    if not elapsed(coverage["span_ms"]):
        raise ValueError("shutdown coverage duration is invalid")
    checkpoints = value["checkpoints"]
    if not isinstance(checkpoints, dict) or set(checkpoints) != set(STAGES):
        raise ValueError("shutdown checkpoint stages are invalid")
    for entry in checkpoints.values():
        if (not isinstance(entry, dict) or set(entry) != {"count", "last_elapsed_ms"}
                or not bounded_count(entry["count"]) or not elapsed(entry["last_elapsed_ms"])):
            raise ValueError("shutdown checkpoint evidence is invalid")
    return value


def collect_remote(*, host: str, user: str = "deck", port: int = 22,
                   timeout_seconds: int = 10, identity_file: Path | None = None) -> dict:
    if user == "root":
        raise ValueError("shutdown capture requires an unprivileged SSH user")
    argv = build_ssh_argv(host=host, user=user, port=port,
                         timeout_seconds=timeout_seconds, identity_file=identity_file)
    payload = remote_payload()
    result = subprocess.run(argv, input=payload, text=True, capture_output=True,
                            timeout=timeout_seconds + JOURNAL_TIMEOUT_SECONDS + 5, check=False)
    if result.returncode:
        raise RuntimeError(ssh_failure_code(result.returncode, result.stderr))
    value = validate_report(result.stdout)
    value["collector"]["payload_sha256"] = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--user", default="deck")
    parser.add_argument("--port", type=int, default=22)
    parser.add_argument("--timeout", type=int, default=10)
    parser.add_argument("--identity-file", type=Path)
    args = parser.parse_args()
    try:
        report = collect_remote(host=args.host, user=args.user, port=args.port,
                                timeout_seconds=args.timeout, identity_file=args.identity_file)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        # Exceptions may contain command lines or destinations; do not print them.
        print("Shutdown evidence capture unavailable; no remote changes made.", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
