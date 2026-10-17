"""Generic, inert Linux process-supervision verification seam.

The five descendant cleanup helpers retain the reviewed algorithm unchanged.
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


def reap_adopted():
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


def kill_adopted():
    for pid in adopted_children():
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


def close_group(process):
    """Always terminate the entire launcher session, including on normal exit."""
    for sig, seconds in ((signal.SIGTERM, TERM_SECONDS), (signal.SIGKILL, REAP_SECONDS)):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            process.poll()
            if sig == signal.SIGKILL:
                kill_adopted()  # includes a descendant that escaped using setsid/double-fork
            reap_adopted()
            if not group_alive(process.pid) and not adopted_children():
                process.wait(timeout=.1)
                return True
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
        exit_code = p.wait(timeout=max(0, deadline - time.monotonic()))
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
            except (OSError, Reject):
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
