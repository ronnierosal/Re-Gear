"""Generic, inert Linux process-supervision verification seam.

Unchanged helpers retain their historical equivalence checks. The identity-pin
correction intentionally changes reaping/group cleanup; private-wrapper parity
is not claimed for those helpers. No private wrapper or route is changed.
The launch seam substitutes an injected process API, trusted argv/cwd/environment and a result
validator; owned-resource cleanup substitutes an explicit trusted parent/prefix.
These are library/test seams, never a general remote operation. No consumer,
device identity, registration, source delivery, manifest or device I/O is wired.
Each supervisor must own a dedicated worker and no unrelated children.
"""
import ctypes
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import stat
import time

LAUNCH_SECONDS = 6.0
STDOUT_CAP = 4096
STDERR_CAP = 2048
TOTAL_CAP = 6144
TERM_SECONDS = .2
REAP_SECONDS = 1.0


class Reject(Exception):
    pass


def group_alive(group):
    try:
        os.killpg(group, 0)
        return True
    except ProcessLookupError:
        return False


def reap_adopted(exclude_pid=None):
    if exclude_pid is not None:
        for pid in adopted_children():
            if pid == exclude_pid:
                continue
            try:
                os.waitpid(pid, os.WNOHANG)
            except ChildProcessError as error:
                raise Reject('child_identity') from error
        return
    while True:
        try:
            pid, _ = os.waitpid(-1, os.WNOHANG)
            if pid == 0:
                return
        except ChildProcessError:
            return


def adopted_children():
    """Dedicated supervisor owns no unrelated children; read only its kernel child list."""
    raw = Path('/proc/self/task/' + str(os.getpid()) + '/children').read_bytes()
    if len(raw) > 4096:
        raise Reject('children_bounds')
    children = [int(x) for x in raw.split()]
    if len(children) > 64 or any(p <= 1 for p in children):
        raise Reject('children_bounds')
    return children


def kill_adopted(exclude_pid=None):
    for pid in adopted_children():
        if pid == exclude_pid:
            continue
        try:
            fd = os.pidfd_open(pid)
        except ProcessLookupError:
            continue
        try:
            # pidfd binds the signal target; PPid qualification excludes unrelated PID reuse.
            with open('/proc/' + str(pid) + '/status', 'rb') as stream:
                status = stream.read(8193)
            if len(status) > 8192 or b'PPid:\t' + str(os.getpid()).encode() + b'\n' not in status:
                raise Reject('child_identity')
            signal.pidfd_send_signal(fd, signal.SIGKILL)
        except FileNotFoundError:
            pass
        finally:
            os.close(fd)


def observe_exit(process):
    """Observe this still-owned child without releasing its PID/group identity."""
    if process.returncode is not None:
        raise Reject('launcher_identity')
    try:
        result = os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
    except (AttributeError, ChildProcessError) as error:
        raise Reject('launcher_identity') from error
    if result is None:
        return None
    if result.si_pid != process.pid:
        raise Reject('launcher_identity')
    if result.si_code == os.CLD_EXITED:
        return result.si_status
    if result.si_code in (os.CLD_KILLED, os.CLD_DUMPED):
        return -result.si_status
    raise Reject('launcher_identity')


def close_group(process):
    """Keep the child unreaped until all group signals are finished."""
    for sig, seconds in ((signal.SIGTERM, TERM_SECONDS), (signal.SIGKILL, REAP_SECONDS)):
        try:
            observe_exit(process)  # refuse numeric signaling after identity loss
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass
        except (OSError, Reject):
            return False
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                exit_code = observe_exit(process)
                if sig == signal.SIGKILL:
                    kill_adopted(exclude_pid=process.pid)
                reap_adopted(exclude_pid=process.pid)
                remaining = [pid for pid in adopted_children() if pid != process.pid]
                # Once the leader exits, its surviving descendants are adopted
                # by this dedicated subreaper. The leader itself stays pinned.
                if exit_code is not None and not remaining:
                    return process.wait(timeout=.1) == exit_code
            except (OSError, Reject):
                return False
            time.sleep(.01)
    return False


def supervise(argv, *, cwd, environment, validator, process_api):
    # Become subreaper for this one ephemeral supervisor, never a system setting.
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
        raise Reject('subreaper_unavailable')
    deadline = time.monotonic() + LAUNCH_SECONDS
    p = None; sel = selectors.DefaultSelector(); out = bytearray(); err = bytearray()
    code = 'bridge.failed'; capture = None; cleanup = False
    try:
        if time.monotonic() >= deadline:
            raise Reject('timeout_before_spawn')
        p = process_api.Popen(argv,
                             stdin=process_api.DEVNULL, stdout=process_api.PIPE, stderr=process_api.PIPE,
                             cwd=cwd, env=environment,
                             start_new_session=True, shell=False)
        for pipe, name in ((p.stdout, 'out'), (p.stderr, 'err')):
            sel.register(pipe, selectors.EVENT_READ, name)
        while sel.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise Reject('timeout')
            for key, _ in sel.select(min(.05, remaining)):
                b = os.read(key.fileobj.fileno(), 1024)
                if not b:
                    sel.unregister(key.fileobj)
                    continue
                (out if key.data == 'out' else err).extend(b)
                if len(out) > STDOUT_CAP or len(err) > STDERR_CAP or len(out) + len(err) > TOTAL_CAP:
                    raise Reject('output_bounds')
        exit_code = observe_exit(p)
        while exit_code is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise Reject('timeout')
            time.sleep(min(.01, remaining))
            exit_code = observe_exit(p)
        capture = validator(bytes(out), exit_code)
        code = 'bridge.completed'
    except (Reject, OSError, process_api.TimeoutExpired, InterruptedError, KeyboardInterrupt):
        code = 'bridge.rejected'
        capture = None
    finally:
        for sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, signal.SIG_IGN)
        if p is not None:
            try:
                cleanup = close_group(p)
            except (OSError, Reject, process_api.TimeoutExpired):
                cleanup = False
            for pipe in (p.stdout, p.stderr):
                pipe.close()
        else:
            cleanup = True
        sel.close()
    if not cleanup:
        return 'bridge.cleanup_unconfirmed', None, False
    return code, capture, True


def owned_root(path, *, parent, prefix):
    if parent.is_symlink() or path.parent != parent or re.fullmatch(re.escape(prefix) + r'[A-Za-z0-9]{8}', path.name) is None:
        raise Reject('temporary_root')
    s = path.lstat()
    if not stat.S_ISDIR(s.st_mode) or s.st_uid != os.getuid() or s.st_mode & 0o077:
        raise Reject('temporary_root')
    return s


def remove_owned_root(root, before, *, parent, prefix):
    """Delete only this exact owned temporary directory, with fd-relative traversal."""
    if not shutil.rmtree.avoids_symlink_attacks:
        return False
    try:
        now = owned_root(root, parent=parent, prefix=prefix)
        if (now.st_dev, now.st_ino) != (before.st_dev, before.st_ino):
            return False
        fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            shutil.rmtree(root.name, dir_fd=fd)
            try:
                os.stat(root.name, dir_fd=fd, follow_symlinks=False)
                return False
            except FileNotFoundError:
                return True
        finally:
            os.close(fd)
    except OSError:
        return False
