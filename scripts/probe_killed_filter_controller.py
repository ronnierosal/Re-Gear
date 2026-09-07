"""Explicit disposable controller-SIGKILL experiment; no player authorization.

The binding uses a schema-required unit label as synthetic fixture data only.
No service is queried or changed. Private journal evidence is always retained.
Only the dummy receiver enters the new cgroup; only null/zero are opened.
Attachment contexts close their BPF descriptors before readiness. This tests
durable pin recovery after controller death, not a crash with live BPF FDs.
The separate pin-pending scenario kills inside pin(), before either live BPF
descriptor or the transaction lock is released; parent reads only after death.
"""
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
import platform
import signal
import socket
import stat
import sys
import tempfile
import time
import uuid

if Path(__file__).name != '__main__.py':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

from hdm.delivery.device_filter_attachment import AttachmentObservation, FilterAttachmentController
from hdm.delivery.device_filter_journal import FilterJournal
from hdm.delivery.device_filter_kernel import CgroupDeviceLink
from hdm.delivery.device_filter_lifecycle import LaunchBinding, Phase
from hdm.delivery.device_filter_pin_directory import FilterPinDirectory
from hdm.delivery.device_filter_recovery import FilterRecovery


def _send(sock, packet):
    sock.settimeout(3)
    if sock.send(packet) != len(packet):
        raise ValueError('short fixture packet')


def _recv(sock):
    sock.settimeout(3)
    packet, ancillary, flags, _ = sock.recvmsg(129)
    if not packet or len(packet) > 128 or ancillary or flags:
        raise ValueError('invalid fixture packet')
    return packet


def _child_setup(parent, keep):
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0 or os.getppid() != parent:
        raise ValueError('child lifetime unavailable')
    names = os.listdir('/proc/self/fd')
    if len(names) > 4096:
        raise ValueError('descriptor inventory unbounded')
    for name in names:
        fd = int(name)
        if fd not in keep:
            try:
                os.close(fd)
            except OSError as error:
                if error.errno != errno.EBADF:
                    raise


def _receiver(sock, directory, parent):
    try:
        _child_setup(parent, {sock.fileno(), directory})
        member = os.open('cgroup.procs', os.O_WRONLY | os.O_NOFOLLOW, dir_fd=directory)
        try:
            packet = str(os.getpid()).encode('ascii')
            if os.write(member, packet) != len(packet):
                raise ValueError('short cgroup write')
        finally:
            os.close(member)
        os.close(directory)
        _send(sock, b'ready')
        for _ in range(8):
            # Allow parent time to compile, commit and recover between probes.
            sock.settimeout(30)
            command = sock.recv(16)
            if command == b'stop':
                break
            if command != b'probe':
                raise ValueError('unknown control command')
            result = []
            for path in ('/dev/null', '/dev/zero'):
                try:
                    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
                except OSError as error:
                    if error.errno != errno.EPERM:
                        raise
                    result.append(False)
                else:
                    os.close(fd)
                    result.append(True)
            _send(sock, json.dumps(result).encode('ascii'))
        os._exit(0)
    except BaseException:
        os._exit(2)


def _probe(sock, expected):
    _send(sock, b'probe')
    if _recv(sock) != json.dumps(expected).encode('ascii'):
        raise ValueError('dummy open result mismatch')


def _wait(pid, *, timeout=3, waitpid=os.waitpid, clock=time.monotonic, sleep=time.sleep):
    deadline = clock() + timeout
    while True:
        done, status = waitpid(pid, os.WNOHANG)
        if done == pid:
            return status
        if done != 0 or clock() >= deadline:
            raise TimeoutError('owned child exit unconfirmed')
        sleep(0.02)


def _kill(pid, *, kill=os.kill, wait=_wait):
    kill(pid, signal.SIGKILL)
    status = wait(pid)
    if not os.WIFSIGNALED(status) or os.WTERMSIG(status) != signal.SIGKILL:
        raise ValueError('controller SIGKILL not confirmed')


def terminate_owned(pid, *, waitpid=os.waitpid, kill=os.kill, wait=_wait):
    """Cleanup only: accept any reaped status of this still-owned child.

Never signal after a successful reap. A child exiting between WNOHANG and
SIGKILL remains ours until wait completes; ESRCH still requires that reap.
"""
    done, status = waitpid(pid, os.WNOHANG)
    if done == pid:
        return status
    if done != 0:
        raise ValueError('unexpected child identity')
    try:
        kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    return wait(pid)


def _record(journal, binding):
    with journal.transaction() as tx:
        record = tx.read(binding.operation, binding.unit)
    if record.lifecycle.binding != binding or record.delivery_granted:
        raise ValueError('fixture record identity mismatch')
    return record


def verify_killed_owner(binding, journal, *, ready, probe, kill_controller,
                        query, recover):
    """Testable ordering; caller owns unconditional independent cleanup."""
    if ready() != b'attached':
        raise ValueError('controller readiness absent')
    record = _record(journal, binding)
    if record.lifecycle.phase is not Phase.ATTACHED:
        raise ValueError('durable attachment absent')
    owned = record.lifecycle.owned
    if set(query()) != {owned.program_id}:
        raise ValueError('fixture attachment set mismatch')
    probe([False, True])
    kill_controller()
    if _record(journal, binding) != record or set(query()) != {owned.program_id}:
        raise ValueError('ownership did not survive controller death')
    probe([False, True])
    result = recover()
    if result.outcome != 'owned_pin_removed' or result.launch_authorized or result.disconnect_clearance:
        raise ValueError('owned recovery unconfirmed')
    if _record(journal, binding).lifecycle.phase is not Phase.CANCELLED or query():
        raise ValueError('durable cancellation or detach unconfirmed')
    probe([True, True])
    return dict(state='fixture_passed', controller_sigkill_verified=True,
                durable_pin_recovery_verified=True, synthetic_binding=True,
                live_bpf_fd_crash_verified=False,
                journal_retained=True, player_mutation=False, disconnect_clearance=False)


def verify_pending_owner(binding, journal, *, ready, probe, kill_controller, query, recover):
    """Do not acquire the child's held journal lock until SIGKILL is reaped."""
    if ready() != b'pin-pending':
        raise ValueError('pending readiness absent')
    before = tuple(query())
    if len(before) != 1 or type(before[0]) is not int or before[0] <= 0:
        raise ValueError('exact pending program absent')
    probe([False, True])
    kill_controller()
    record = _record(journal, binding)
    state = record.lifecycle
    if (state.phase is not Phase.PIN_PENDING or state.owned is None
            or state.owned.program_id != before[0]
            or state.owned.survives_owner_exit is not False
            or tuple(query()) != before):
        raise ValueError('durable pending ownership mismatch')
    probe([False, True])
    result = recover()
    if (result.outcome != 'owned_pin_removed' or result.launch_authorized or result.disconnect_clearance
            or _record(journal, binding).lifecycle.phase is not Phase.CANCELLED or query()):
        raise ValueError('pending recovery unconfirmed')
    probe([True, True])
    return dict(state='fixture_passed', controller_sigkill_verified=True,
                durable_pin_recovery_verified=True, pin_pending_recovery_verified=True,
                live_bpf_fd_crash_verified=True, synthetic_binding=True,
                journal_retained=True, player_mutation=False, disconnect_clearance=False)


def pending_kernel_factory(sock):
    """Fixture-only interception: never returned to a production caller."""
    class PendingLink(CgroupDeviceLink):
        def pin(self, directory_fd, token, expected):
            super().pin(directory_fd, token, expected)
            if (self.program_fd is None or self.link_fd is None
                    or self.program_id() != expected.program_id or self.link_identity() != expected):
                raise ValueError('live pending descriptors unconfirmed')
            _send(sock, b'pin-pending')
            sock.settimeout(30)
            sock.recv(1)
            raise ValueError('pending controller was not killed')
    return PendingLink


def run_fixture(*, pin_pending=False):
    if type(pin_pending) is not bool:
        raise ValueError('explicit fixture mode required')
    if platform.system() != 'Linux' or platform.machine() != 'x86_64' or os.geteuid() != 0:
        raise ValueError('root Linux x86_64 required')
    raw_uid = os.environ.get('SUDO_UID', '')
    if not raw_uid.isdecimal() or not 0 < int(raw_uid) < 2**32:
        raise ValueError('supervised nonroot UID required')
    import pwd
    pwd.getpwuid(int(raw_uid))
    for path, minor in (('/dev/null', 3), ('/dev/zero', 5)):
        node = os.stat(path, follow_symlinks=False)
        if not stat.S_ISCHR(node.st_mode) or node.st_rdev != os.makedev(1, minor):
            raise ValueError('dummy character device identity unavailable')
    with open('/proc/sys/kernel/random/boot_id', 'rb') as source:
        boot = source.read(128)
    if len(boot) != 37:
        raise ValueError('boot identity unavailable')
    boot_hash = hashlib.sha256(boot).hexdigest()
    root = directory = journal_fd = None
    receiver = controller = None
    rs = rc = cs = cc = None
    journal = binding = None
    created = False
    identity = None
    cleanup_errors = []
    name = 'regear-killed-fixture-' + uuid.uuid4().hex
    recovered = False
    try:
        root = os.open('/sys/fs/cgroup', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        info = os.fstat(root)
        if info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError('unsafe cgroup root')
        control = os.open('cgroup.controllers', os.O_RDONLY | os.O_NOFOLLOW, dir_fd=root)
        os.close(control)
        os.mkdir(name, 0o700, dir_fd=root)
        created = True
        directory = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
        identity = os.fstat(directory)
        if identity.st_uid != 0 or identity.st_mode & 0o077 or identity.st_dev != info.st_dev:
            raise ValueError('unsafe fixture cgroup')
        journal_path = tempfile.mkdtemp(prefix='regear-killed-journal-')
        journal_fd = os.open(journal_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        journal = FilterJournal(journal_path, owner_uid=0, trusted_directory_fd=journal_fd)
        rs, rc = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        parent = os.getpid()
        receiver = os.fork()
        if receiver == 0:
            _receiver(rc, directory, parent)
        rc.close(); rc = None
        if _recv(rs) != b'ready':
            raise ValueError('receiver unavailable')
        _probe(rs, [True, True])
        with open(f'/proc/{receiver}/stat', 'r') as source:
            starttime = int(source.read(4096).rsplit(')', 1)[1].split()[19])
        binding = LaunchBinding(boot_hash, uuid.uuid4().hex, 'gamescope-session.service',
            uuid.uuid4().hex, int(raw_uid), receiver, starttime, identity.st_dev,
            identity.st_ino, hashlib.sha256(b'synthetic-null-only-fixture').hexdigest(), time.monotonic()+30)
        journal.create(binding)
        def observe():
            member = os.open('cgroup.procs', os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
            try:
                if os.read(member, 128).decode().split() != [str(receiver)]:
                    raise ValueError('fixture membership changed')
            finally:
                os.close(member)
            with open(f'/proc/{receiver}/stat', 'r') as source:
                current = int(source.read(4096).rsplit(')', 1)[1].split()[19])
            if current != starttime:
                raise ValueError('receiver identity changed')
            return AttachmentObservation(binding, ((1, 3),), True, True)
        with CgroupDeviceLink() as query_owner:
            if query_owner.query_program_ids(directory):
                raise ValueError('new cgroup has existing filters')
        cs, cc = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        controller = os.fork()
        if controller == 0:
            try:
                _child_setup(parent, {cc.fileno(), directory, journal_fd})
                FilterAttachmentController(journal, observe,
                    kernel_factory=pending_kernel_factory(cc) if pin_pending else CgroupDeviceLink,
                    pin_factory=lambda: FilterPinDirectory(create=True)).attach(binding.operation, binding.unit, directory)
                _send(cc, b'attached')
                cc.settimeout(30)
                cc.recv(1)
                os._exit(4)
            except BaseException:
                os._exit(2)
        cc.close(); cc = None
        def kill_controller():
            nonlocal controller
            pid = controller
            # Mark reaped even on unexpected status, preventing PID reuse kills.
            os.kill(pid, signal.SIGKILL)
            status = _wait(pid)
            controller = None
            if not os.WIFSIGNALED(status) or os.WTERMSIG(status) != signal.SIGKILL:
                raise ValueError('controller SIGKILL unconfirmed')
        def recover():
            nonlocal recovered
            result = FilterRecovery(journal).recover(binding.operation, binding.unit, current_boot_hash=boot_hash)
            recovered = result.outcome == 'owned_pin_removed'
            return result
        with CgroupDeviceLink() as query_owner:
            verify = verify_pending_owner if pin_pending else verify_killed_owner
            report = verify(binding, journal, ready=lambda:_recv(cs),
                probe=lambda expected:_probe(rs, expected), kill_controller=kill_controller,
                query=lambda:query_owner.query_program_ids(directory), recover=recover)
    finally:
        def attempt(action):
            try:
                action()
            except BaseException:
                cleanup_errors.append(True)
        if controller is not None and controller > 0:
            attempt(lambda:terminate_owned(controller))
        if journal is not None and binding is not None and not recovered:
            def recover_remaining():
                nonlocal recovered
                result = FilterRecovery(journal).recover(binding.operation, binding.unit, current_boot_hash=boot_hash)
                recovered = result.outcome in ('owned_pin_removed', 'cancelled_without_owned_identity')
                if not recovered:
                    raise ValueError('retaining unresolved ownership evidence')
            attempt(recover_remaining)
        for sock in (rs, rc, cs, cc):
            if sock is not None:
                attempt(sock.close)
        if receiver is not None and receiver > 0:
            attempt(lambda:terminate_owned(receiver))
        if created:
            def remove_group():
                if identity is None or (binding is not None and not recovered):
                    raise ValueError('retaining unresolved cgroup')
                current = os.stat(name, dir_fd=root, follow_symlinks=False)
                if not stat.S_ISDIR(current.st_mode) or (current.st_dev,current.st_ino)!=(identity.st_dev,identity.st_ino):
                    raise ValueError('cgroup identity changed')
                os.rmdir(name, dir_fd=root)
            attempt(remove_group)
        for fd in (directory, journal_fd, root):
            if fd is not None:
                attempt(lambda fd=fd:os.close(fd))
        if cleanup_errors:
            raise RuntimeError('fixture cleanup unconfirmed; journal retained')
    return report


def main():
    if sys.argv[1:] not in (['--disposable-killed-controller'], ['--disposable-pin-pending-crash']):
        raise SystemExit('Explicit disposable fixture scenario required')
    previous = {}
    def interrupted(*_):
        raise RuntimeError('fixture interrupted')
    try:
        if platform.system() == 'Linux':
            for number in (signal.SIGINT, signal.SIGTERM, signal.SIGALRM):
                previous[number] = signal.signal(number, interrupted)
            signal.alarm(45)
        report = run_fixture(pin_pending=sys.argv[1:] == ['--disposable-pin-pending-crash'])
    except Exception:
        report = dict(state='fixture_failed', code='test_or_cleanup_unconfirmed',
                      journal_retained=True, disconnect_clearance=False)
    finally:
        if previous:
            signal.alarm(0)
            for number, handler in previous.items():
                signal.signal(number, handler)
    print(json.dumps(report, sort_keys=True))
    return 0 if report['state'] == 'fixture_passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
