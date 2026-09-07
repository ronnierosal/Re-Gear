"""Operator-only disposable user-service BPF handshake; no player integration.

The controller is root, the fixed child is the invoking non-root user. Only
dummy null/zero devices are opened. An unpinned link cannot outlive its owner;
this is deliberately NOT a crash-surviving runtime ownership implementation.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import selectors
import stat
import subprocess
import sys
import tempfile
import time
import uuid


CHILD = r'''
import errno, json, os, pathlib, sys, time
root = pathlib.Path(sys.argv[1])
def opened(path, zero=False):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
        try:
            return "opened" if not zero or os.read(fd, 1) == b"\0" else "bad_data"
        finally:
            os.close(fd)
    except OSError as error:
        return "denied" if error.errno in (errno.EACCES, errno.EPERM) else "unknown"
def context():
    fields = dict(line.split(":", 1) for line in pathlib.Path("/proc/self/status").read_text().splitlines() if ":" in line)
    return (os.geteuid(), str(pathlib.Path("/proc/self/ns/user").readlink()), fields["NoNewPrivs"], fields["CapBnd"])
def wait(name):
    end = time.monotonic() + 8
    while time.monotonic() < end:
        if (root / name).is_file():
            return
        time.sleep(.02)
    raise SystemExit(2)
initial = context()
held = os.open("/dev/null", os.O_RDONLY | os.O_CLOEXEC)
baseline = (opened("/dev/null") == "opened" and opened("/dev/zero", True) == "opened"
    and opened("/proc/self/root/dev/null") == "opened")
print(json.dumps(dict(stage="ready", pid=os.getpid(), baseline=baseline)), flush=True)
wait("attached")
pid = os.fork()
if pid == 0:
    os._exit(0 if opened("/dev/null") == "denied" else 1)
_, descendant = os.waitpid(pid, 0)
checks = dict(null_denied=opened("/dev/null") == "denied",
    alias_denied=opened("/proc/self/root/dev/null") == "denied",
    zero_allowed=opened("/dev/zero", True) == "opened",
    descendant_denied=os.waitstatus_to_exitcode(descendant) == 0,
    retained_descriptor_readable=os.read(held, 1) == b"",
    launch_context_preserved=context() == initial)
print(json.dumps(dict(stage="filtered", checks=checks)), flush=True)
wait("detached")
os.close(held)
print(json.dumps(dict(stage="restored", null_restored=opened("/dev/null") == "opened",
    zero_allowed=opened("/dev/zero", True) == "opened")), flush=True)
'''

CHECKS = frozenset({"null_denied", "alias_denied", "zero_allowed",
    "descendant_denied", "retained_descriptor_readable", "launch_context_preserved"})


def valid_filtered(value):
    return (isinstance(value, dict) and value.get("stage") == "filtered"
            and isinstance(value.get("checks"), dict) and set(value["checks"]) == CHECKS
            and all(item is True for item in value["checks"].values()))


class Lines:
    def __init__(self, stream):
        self.stream = stream
        self.pending = b""

    def read(self):
        end = time.monotonic() + 8
        with selectors.DefaultSelector() as selector:
            selector.register(self.stream, selectors.EVENT_READ)
            while b"\n" not in self.pending:
                remaining = end - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise ValueError("child_timeout")
                data = os.read(self.stream.fileno(), 4096)
                if not data or len(self.pending) + len(data) > 8192:
                    raise ValueError("child_output_invalid")
                self.pending += data
        line, self.pending = self.pending.split(b"\n", 1)
        result = json.loads(line)
        if not isinstance(result, dict):
            raise ValueError("child_report_invalid")
        return result


def open_cgroup(path, uid, unit):
    prefix = f"/user.slice/user-{uid}.slice/user@{uid}.service/"
    if (not path.startswith(prefix) or not path.endswith("/" + unit)
            or any(part in ("", ".", "..") for part in path[1:].split("/"))):
        raise ValueError("unexpected_fixture_cgroup")
    fd = os.open("/sys/fs/cgroup", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path[1:].split("/"):
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def cleanup_fixture(control, child, unit):
    """A dead systemd-run client does not establish that its service is gone."""
    try:
        state = control("show", unit, "--property=LoadState", "--value")
        if state.stdout.strip() != "not-found":
            control("stop", unit)
        if child.poll() is None:
            child.wait(timeout=5)
        for _ in range(10):
            state = control("show", unit, "--property=LoadState", "--value")
            if state.stdout.strip() == "not-found":
                return True
            time.sleep(.1)
    except (OSError, subprocess.SubprocessError):
        pass
    return False


def close_filter(owner, cgroup_fd, prior, *, detach_verified):
    """Preserve exact detach readback taken before systemd collects the cgroup.

    A post-collection query can fail because the cgroup no longer exists. Only
    an already-closed owned link with prior successful readback may skip it.
    """
    link_already_closed = owner.link_fd is None
    try:
        owner.close()
        if detach_verified is True and link_already_closed:
            return True
        if cgroup_fd is None or prior is None:
            return False
        return set(owner.query_program_ids(cgroup_fd)) == set(prior)
    except (OSError, ValueError, RuntimeError):
        return False


def run_probe(*, pinned=False):
    report = {"status": "inconclusive", "disconnect_clearance": False, "pinned_fixture": pinned}
    if sys.platform != "linux":
        return dict(report, reason="linux_required")
    import pwd
    from hdm.delivery.device_filter_program import compile_device_filter
    from scripts.probe_cgroup_filter_link import CgroupDeviceLink
    if pinned:
        from scripts.probe_pinned_filter_owner import PinnedFixtureOwner

    try:
        uid = int(os.environ["SUDO_UID"])
        if os.geteuid() != 0 or not 0 < uid < 2**32 - 1:
            raise ValueError("operator_sudo_required")
        account = pwd.getpwuid(uid)
    except (KeyError, ValueError):
        return dict(report, reason="operator_sudo_required")
    user_options = dict(user=uid, group=account.pw_gid,
        extra_groups=os.getgrouplist(account.pw_name, account.pw_gid),
        env={"HOME": account.pw_dir, "USER": account.pw_name,
             "PATH": "/usr/bin:/bin", "XDG_RUNTIME_DIR": f"/run/user/{uid}",
             "DBUS_SESSION_BUS_ADDRESS": f"unix:path=/run/user/{uid}/bus"})
    unit = "regear-link-fixture-" + uuid.uuid4().hex + ".service"

    def control(*args):
        return subprocess.run(["/usr/bin/systemctl", "--user", *args],
            **user_options, capture_output=True, text=True, timeout=3, check=False)

    def binding(pid):
        observation = control("show", unit, "--property=InvocationID", "--property=ControlGroup",
            "--property=MainPID", "--property=ActiveState")
        if observation.returncode != 0 or len(observation.stdout) > 2048:
            raise ValueError("unit_observation_failed")
        fields = dict(line.split("=", 1) for line in observation.stdout.splitlines())
        invocation = fields.get("InvocationID", "")
        if (fields.get("MainPID") != str(pid) or fields.get("ActiveState") != "active"
                or len(invocation) != 32 or any(c not in "0123456789abcdef" for c in invocation)):
            raise ValueError("unit_binding_changed")
        process = Path("/proc") / str(pid)
        process_status = (process / "status").read_text()
        uid_line = next(line for line in process_status.splitlines() if line.startswith("Uid:"))
        if tuple(int(value) for value in uid_line.split()[1:]) != (uid,) * 4:
            raise ValueError("fixture_user_changed")
        process_stat = (process / "stat").read_text().rsplit(")", 1)[1].split()
        path = fields.get("ControlGroup", "")
        if (process / "cgroup").read_text().strip() != "0::" + path:
            raise ValueError("fixture_membership_changed")
        return invocation, int(process_stat[19]), path

    owner = None
    cgroup_fd = None
    child = None
    prior = None
    step = "prepare"
    with tempfile.TemporaryDirectory(prefix="regear-link-fixture-") as directory:
        root = Path(directory)
        root.chmod(0o755)  # Child can read root-owned gates, never create them.
        try:
            node = os.stat("/dev/null")
            if not stat.S_ISCHR(node.st_mode):
                raise ValueError("dummy_identity_unavailable")
            owner = PinnedFixtureOwner() if pinned else CgroupDeviceLink()
            step = "load_program"
            owner.load(compile_device_filter(((os.major(node.st_rdev), os.minor(node.st_rdev)),)))
            step = "start_fixture"
            child = subprocess.Popen([
                "/usr/bin/systemd-run", "--user", "--quiet", "--wait", "--pipe", "--collect",
                "--service-type=exec", "--unit=" + unit, "--property=RuntimeMaxSec=25",
                "--property=TimeoutStopSec=2", "--", "/usr/bin/python3", "-I", "-u", "-c", CHILD, directory,
            ], **user_options, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            lines = Lines(child.stdout)
            ready = lines.read()
            if ready.get("stage") != "ready" or ready.get("baseline") is not True or type(ready.get("pid")) is not int or ready["pid"] <= 1:
                raise ValueError("baseline_unverified")
            step = "authenticate_fixture"
            initial = binding(ready["pid"])
            cgroup_fd = open_cgroup(initial[2], uid, unit)
            cgroup_identity = os.fstat(cgroup_fd)

            def revalidate():
                if binding(ready["pid"]) != initial:
                    raise ValueError("fixture_binding_changed")
                current_fd = open_cgroup(initial[2], uid, unit)
                try:
                    current = os.fstat(current_fd)
                    if (current.st_dev, current.st_ino) != (cgroup_identity.st_dev, cgroup_identity.st_ino):
                        raise ValueError("fixture_cgroup_replaced")
                finally:
                    os.close(current_fd)

            revalidate()
            step = "query_prior_filters"
            prior = owner.query_program_ids(cgroup_fd)
            step = "attach_filter"
            owner.attach(cgroup_fd)
            step = "verify_attachment"
            program_id = owner.program_id()
            if set(owner.query_program_ids(cgroup_fd)) != set(prior) | {program_id}:
                raise ValueError("attachment_readback_failed")
            revalidate()
            (root / "attached").write_text("fixture only\n")
            step = "filtered_checks"
            filtered = lines.read()
            if not valid_filtered(filtered):
                raise ValueError("filter_checks_failed")
            report.update(filtered["checks"])
            step = "detach_filter"
            owner.close_link()
            if set(owner.query_program_ids(cgroup_fd)) != set(prior):
                raise ValueError("detach_readback_failed")
            report["owned_filter_removed"] = True
            report["detach_verified_before_exit"] = True
            (root / "detached").write_text("fixture only\n")
            step = "restored_checks"
            restored = lines.read()
            if restored.get("stage") != "restored" or restored.get("null_restored") is not True or restored.get("zero_allowed") is not True:
                raise ValueError("restoration_unverified")
            if child.wait(timeout=5) != 0:
                raise ValueError("child_exit_failed")
            report["fresh_access_restored"] = True
            if pinned:
                report["ownership_survived_fd_close"] = owner.ownership_survived_fd_close
                report["pin_removed"] = owner.pin_removed
                if not owner.ownership_survived_fd_close or not owner.pin_removed:
                    raise ValueError("persistent_owner_checks_failed")
            report["status"] = "fixture_passed"
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, StopIteration) as error:
            report["status"] = "inconclusive"
            report["reason"] = "fixture_step_failed"
            report["failed_step"] = step
            if isinstance(error, OSError):
                report["error_number"] = error.errno
        finally:
            if owner is not None:
                report["owned_filter_removed"] = close_filter(owner, cgroup_fd, prior,
                    detach_verified=report.get("detach_verified_before_exit") is True)
            if cgroup_fd is not None:
                os.close(cgroup_fd)
            if child is not None:
                report["transient_unit_removed"] = cleanup_fixture(control, child, unit)
                if child.stdout is not None:
                    child.stdout.close()
            if report.get("owned_filter_removed") is not True or report.get("transient_unit_removed") is not True:
                report["status"] = "inconclusive"
    report["temporary_fixture_removed"] = not root.exists()
    if not report["temporary_fixture_removed"]:
        report["status"] = "inconclusive"
    return report


if __name__ == "__main__":
    if sys.argv[1:] not in ([], ["--pinned"]):
        raise SystemExit("Only --pinned is accepted")
    result = run_probe(pinned=bool(sys.argv[1:]))
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(0 if result["status"] == "fixture_passed" else 1)
