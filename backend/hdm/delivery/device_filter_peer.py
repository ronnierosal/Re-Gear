"""Live waiting-peer binding; fixed proc/cgroup reads, no service mutations.

The caller supplies an authenticated session UID and fixed-unit systemd
inspector. A socket peer alone is not authority. The returned held descriptors
must remain open through observation/attachment/delivery and be revalidated.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import os
import re
import select
import stat

from .device_filter_protocol import FilterRequest
from .device_filter_transport import PeerCredentials


@dataclass(frozen=True)
class WaitingPeerIdentity:
    pid: int
    uid: int
    starttime: int
    invocation: str
    unit: str
    cgroup_path: str
    cgroup_dev: int
    cgroup_inode: int


def validate_peer_text(pid, uid, request, properties, process_stat, process_status, process_cgroup):
    """Bounded parser; input text must come from authenticated live sources."""
    if (type(pid) is not int or pid <= 0 or type(uid) is not int or uid <= 0
            or type(request) is not FilterRequest):
        raise ValueError("invalid waiting peer")
    if (type(properties) is not dict or set(properties) != {"MainPID", "InvocationID", "ActiveState", "ControlGroup"}
            or any(type(v) is not str or len(v) > 512 for v in properties.values())
            or properties["MainPID"] != str(pid)
            or properties["InvocationID"] != request.invocation
            or properties["ActiveState"] not in ("active", "activating")):
        raise ValueError("waiting service generation mismatch")
    expected_slice = "session.slice" if request.unit == "gamescope-session.service" else "app.slice"
    expected_path = f"/user.slice/user-{uid}.slice/user@{uid}.service/{expected_slice}/{request.unit}"
    if properties["ControlGroup"] != expected_path:
        raise ValueError("unexpected service cgroup")
    for text, bound in ((process_stat, 8192), (process_status, 65536), (process_cgroup, 1024)):
        if type(text) is not str or not 0 < len(text) <= bound:
            raise ValueError("invalid process observation length")
    if process_cgroup.strip() != "0::" + expected_path:
        raise ValueError("peer cgroup mismatch")
    uid_lines = [line for line in process_status.splitlines() if line.startswith("Uid:")]
    if len(uid_lines) != 1 or uid_lines[0].split()[1:] != [str(uid)] * 4:
        raise ValueError("peer credentials changed")
    if not process_stat.startswith(str(pid) + " (") or ")" not in process_stat:
        raise ValueError("process stat identity mismatch")
    values = process_stat.rsplit(")", 1)[1].split()
    if len(values) < 20 or values[0] not in ("R", "S", "D", "T", "t", "I", "P", "W") or not re.fullmatch(r"[0-9]+", values[19]):
        raise ValueError("process lifetime unavailable")
    starttime = int(values[19])
    if starttime <= 0:
        raise ValueError("invalid process start time")
    return starttime, expected_path


def _read_at(directory, name, bound):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    try:
        data = bytearray()
        while len(data) <= bound:
            part = os.read(fd, bound + 1 - len(data))
            if not part:
                break
            data.extend(part)
        if len(data) > bound:
            raise ValueError("process observation exceeds bound")
        return data.decode("ascii")
    finally:
        os.close(fd)


def _open_cgroup(path):
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open("/sys/fs/cgroup", flags)
    try:
        for part in path.strip("/").split("/"):
            if part in ("", ".", ".."):
                raise ValueError("invalid cgroup path")
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


class HeldWaitingPeer:
    def __init__(self, pid, uid, request, inspect_unit, pid_fd, proc_fd, cgroup_fd, identity):
        self.pid, self.uid, self.request = pid, uid, request
        self.inspect_unit = inspect_unit
        self.pid_fd, self.proc_fd, self.cgroup_fd = pid_fd, proc_fd, cgroup_fd
        self.identity = identity

    def revalidate(self):
        if self.pid_fd is None:
            raise ValueError("waiting peer handle expired")
        poller = select.poll()
        poller.register(self.pid_fd, select.POLLIN)
        if poller.poll(0):
            raise ValueError("waiting peer exited")
        starttime, path = validate_peer_text(self.pid, self.uid, self.request,
            self.inspect_unit(self.request.unit), _read_at(self.proc_fd, "stat", 8192),
            _read_at(self.proc_fd, "status", 65536), _read_at(self.proc_fd, "cgroup", 1024))
        current_fd = _open_cgroup(path)
        try:
            current, held = os.fstat(current_fd), os.fstat(self.cgroup_fd)
            if (not stat.S_ISDIR(held.st_mode)
                    or (current.st_dev, current.st_ino) != (held.st_dev, held.st_ino)):
                raise ValueError("service cgroup replaced")
            observed = WaitingPeerIdentity(self.pid, self.uid, starttime,
                self.request.invocation, self.request.unit, path, held.st_dev, held.st_ino)
            if observed != self.identity or poller.poll(0):
                raise ValueError("waiting peer identity changed")
            return observed
        finally:
            os.close(current_fd)


@contextmanager
def hold_waiting_peer(peer, request, *, expected_uid, inspect_unit):
    # pidfd_open failing (including unsupported platform) must not fall back to
    # a PID-only lifetime check. Socket credentials must already be verified.
    if (type(peer) is not PeerCredentials or type(expected_uid) is not int or expected_uid <= 0 or peer.uid != expected_uid
            or type(peer.pid) is not int or peer.pid <= 0 or type(request) is not FilterRequest):
        raise ValueError("unexpected socket peer")
    descriptors = []
    held = None
    try:
        pid_fd = os.pidfd_open(peer.pid, 0)
        descriptors.append(pid_fd)
        proc_fd = os.open(f"/proc/{peer.pid}", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descriptors.append(proc_fd)
        starttime, path = validate_peer_text(peer.pid, expected_uid, request,
            inspect_unit(request.unit), _read_at(proc_fd, "stat", 8192),
            _read_at(proc_fd, "status", 65536), _read_at(proc_fd, "cgroup", 1024))
        cgroup_fd = _open_cgroup(path)
        descriptors.append(cgroup_fd)
        info = os.fstat(cgroup_fd)
        identity = WaitingPeerIdentity(peer.pid, expected_uid, starttime, request.invocation,
            request.unit, path, info.st_dev, info.st_ino)
        held = HeldWaitingPeer(peer.pid, expected_uid, request, inspect_unit,
            pid_fd, proc_fd, cgroup_fd, identity)
        held.revalidate()
        yield held
    finally:
        if held is not None:
            held.pid_fd = None
        for fd in reversed(descriptors):
            os.close(fd)
