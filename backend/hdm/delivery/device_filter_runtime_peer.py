"""Observe the immutable runtime of an already held service peer.

This is source/lifetime evidence, not broker isolation or grant authority.
The caller must also authenticate the effective service launch configuration.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import os
import stat

from .device_filter_peer import HeldWaitingPeer, _read_at
from .device_filter_runtime_store import RuntimeStore


@dataclass(frozen=True)
class RuntimePeerObservation:
    identity: object
    runtime_digest: str
    interpreter_device: int
    interpreter_inode: int


@dataclass(frozen=True)
class SessionEntryRuntimeObservation:
    identity: object
    runtime_digest: str
    interpreter_device: int
    interpreter_inode: int
    purpose: str = 'prepare_and_withhold_session_entry'


def validate_session_entry_cmdline(raw,bundle,unit):
    if (unit!='gamescope-session.service' or type(raw) is not str or not raw.endswith('\0')
            or not 0<len(raw)<=65536 or tuple(raw[:-1].split('\0'))!=bundle.session_argv
            or bundle.session_argv!=('/usr/bin/python3','-I',bundle.path,'session')):
        raise ValueError('exact prepare-and-withhold session entry required')


def validate_runtime_cmdline(raw, bundle, unit):
    if type(raw) is not str or not raw.endswith("\0") or not 0 < len(raw) <= 65536:
        raise ValueError("runtime command line unavailable")
    arguments = raw[:-1].split("\0")
    if unit == "steam-launcher.service":
        expected = bundle.steam_argv
        if tuple(arguments) != expected:
            raise ValueError("unexpected Steam runtime command")
    elif unit == "gamescope-session.service":
        expected = ("/usr/bin/python3", "-I", bundle.path, "gamescope")
        if tuple(arguments[:4]) != expected:
            raise ValueError("unexpected Gamescope runtime command")
    else:
        raise ValueError("unapproved runtime service")


@contextmanager
def _python_executable():
    # Resolve the distribution's Python symlink, then hold/check every actual
    # ancestor. A mutable user path is never accepted as the interpreter.
    path = os.path.realpath("/usr/bin/python3", strict=True)
    parts = path.split("/")
    if parts[0] != "" or any(p in ("", ".", "..") for p in parts[1:]):
        raise ValueError("invalid interpreter path")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directory = os.open("/", flags)
    executable = None
    try:
        for index, part in enumerate(parts[1:], 1):
            info = os.fstat(directory)
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
                raise ValueError("unsafe interpreter ancestor")
            if index == len(parts) - 1:
                executable = os.open(part, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
                break
            child = os.open(part, flags, dir_fd=directory)
            os.close(directory)
            directory = child
        info = os.fstat(executable)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
                or info.st_mode & 0o022 or info.st_mode & 0o005 != 0o005):
            raise ValueError("unsafe interpreter executable")
        yield info
    finally:
        if executable is not None:
            os.close(executable)
        os.close(directory)


def observe_runtime_peer(held, bundle, *, store=None):
    if type(held) is not HeldWaitingPeer:
        raise ValueError("held service peer required")
    identity = held.revalidate()
    publication = (RuntimeStore() if store is None else store).verify(bundle)
    with _python_executable() as expected:
        def inspect():
            validate_runtime_cmdline(_read_at(held.proc_fd, "cmdline", 65536), bundle, identity.unit)
            actual = os.stat("exe", dir_fd=held.proc_fd, follow_symlinks=True)
            if (not stat.S_ISREG(actual.st_mode)
                    or (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino)):
                raise ValueError("peer left the approved interpreter")
        inspect()
        if held.revalidate() != identity:
            raise ValueError("runtime peer lifetime changed")
        inspect()
        return RuntimePeerObservation(identity, publication.digest, expected.st_dev, expected.st_ino)


def observe_session_entry_runtime_peer(held,bundle,*,store=None):
    """Separate role authentication; never accepted by the ordinary observer."""
    if type(held) is not HeldWaitingPeer:raise ValueError('held session-entry peer required')
    identity=held.revalidate()
    if identity.unit!='gamescope-session.service':raise ValueError('Gamescope session-entry unit required')
    publication=(RuntimeStore() if store is None else store).verify(bundle)
    with _python_executable() as expected:
        def inspect():
            validate_session_entry_cmdline(_read_at(held.proc_fd,'cmdline',65536),bundle,identity.unit)
            actual=os.stat('exe',dir_fd=held.proc_fd,follow_symlinks=True)
            if (not stat.S_ISREG(actual.st_mode)
                    or (actual.st_dev,actual.st_ino)!=(expected.st_dev,expected.st_ino)):
                raise ValueError('session-entry interpreter changed')
        inspect()
        if held.revalidate()!=identity:raise ValueError('session-entry lifetime changed')
        inspect()
        return SessionEntryRuntimeObservation(identity,publication.digest,expected.st_dev,expected.st_ino)
