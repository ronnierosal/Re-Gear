"""Bounded inherited-resource observations through an authenticated held procfd.

No target descriptor or mapping is opened. Caller authenticates the waiting
wrapper and owns broker policy; a complete observation is never clearance.
"""
from dataclasses import dataclass
import itertools
import os
import math
import re
import stat
import sys
import time

from .device_filter_peer import WaitingPeerIdentity


MAX_ENTRIES = 4096
MAX_FDINFO_BYTES = 16384
MAX_LINK_BYTES = 4096


@dataclass(frozen=True)
class InheritedResourceObservation:
    complete: bool
    target_character_seen: bool = False
    dma_buf_seen: bool = False
    unclassified_seen: bool = False
    code: str = ''


class HeldProcReader:
    """Only proc metadata opens; stat follows magic links without target opens."""
    def entries(self, proc_fd, directory):
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                             dir_fd=proc_fd)
        try:
            with os.scandir(descriptor) as entries:
                values = tuple(entry.name for entry in itertools.islice(entries, MAX_ENTRIES + 1))
            if len(values) > MAX_ENTRIES:
                raise ValueError('entry_bound')
            return tuple(values)
        finally:
            os.close(descriptor)

    def target_stat(self, proc_fd, relative):
        return os.stat(relative, dir_fd=proc_fd, follow_symlinks=True)

    def target_link(self, proc_fd, relative):
        return os.readlink(relative, dir_fd=proc_fd)

    def fdinfo(self, proc_fd, number):
        descriptor = os.open('fdinfo/' + number, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                             dir_fd=proc_fd)
        try:
            pieces = []
            remaining = MAX_FDINFO_BYTES + 1
            while remaining:
                part = os.read(descriptor, remaining)
                if not part:
                    break
                pieces.append(part)
                remaining -= len(part)
            raw = b''.join(pieces)
            if len(raw) > MAX_FDINFO_BYTES:
                raise ValueError('fdinfo_bound')
            return raw
        finally:
            os.close(descriptor)


def _dma_link(link):
    lower = link.lower()
    return any(name in lower for name in ('dmabuf', 'dma_buf', 'dma-buf'))


def _anonymous_link(link):
    return (not link.startswith('/') or link.startswith(('/memfd:', '/anon_inode:'))
            or 'anon_inode:' in link)


def scan_inherited_resources(peer, denied_devices, *, deadline, reader=None,
                             clock=time.monotonic, platform=None):
    """Two matching observations of descriptors and mappings; no release claim."""
    flags = [False, False, False]
    def result(complete, code):
        return InheritedResourceObservation(complete, *flags, code)
    if (sys.platform if platform is None else platform) != 'linux':
        return result(False, 'linux_required')
    if (type(denied_devices) is not tuple or not 1 <= len(denied_devices) <= 16
            or any(type(pair) is not tuple or len(pair) != 2
                   or type(pair[0]) is not int or not 0 <= pair[0] < 4096
                   or type(pair[1]) is not int or not 0 <= pair[1] < 1048576
                   for pair in denied_devices) or len(set(denied_devices)) != len(denied_devices)):
        return result(False, 'device_policy_invalid')
    reader = HeldProcReader() if reader is None else reader
    previous_time = None
    peer_identity = None
    held_proc_fd = None
    def check():
        nonlocal previous_time
        now = clock()
        if (type(now) not in (int, float) or not math.isfinite(now) or now < 0
                or type(deadline) not in (int, float) or not math.isfinite(deadline)
                or not 0 < deadline-now <= 30 or (previous_time is not None and now < previous_time)):
            raise TimeoutError('deadline')
        previous_time = now
    def revalidate():
        nonlocal peer_identity
        check()
        identity = peer.revalidate()
        if (type(identity) is not WaitingPeerIdentity or peer.proc_fd != held_proc_fd
                or (peer_identity is not None and identity != peer_identity)):
            raise ValueError('peer_changed')
        peer_identity = identity
        check()
    def snapshot():
        snapshot_rows = []
        for directory, pattern in (('fd', r'(0|[1-9][0-9]{0,9})'),
                                    ('map_files', r'[0-9a-f]{1,16}-[0-9a-f]{1,16}')):
            check()
            names = reader.entries(held_proc_fd, directory)
            if (type(names) is not tuple or len(names) > MAX_ENTRIES
                    or any(type(n) is not str or re.fullmatch(pattern,n) is None for n in names)
                    or len(set(names)) != len(names)):
                raise ValueError('inventory_invalid')
            for name in sorted(names):
                check()
                if directory == 'map_files':
                    start, end = (int(part,16) for part in name.split('-'))
                    if start >= end:
                        raise ValueError('mapping_range_invalid')
                relative = directory + '/' + name
                link = reader.target_link(held_proc_fd, relative)
                if (type(link) is not str or not link or len(link.encode('utf-8')) > MAX_LINK_BYTES
                        or '\x00' in link):
                    raise ValueError('link_invalid')
                observed = reader.target_stat(held_proc_fd, relative)
                identity = (observed.st_dev, observed.st_ino, observed.st_mode, observed.st_rdev)
                if any(type(v) is not int or v < 0 for v in identity):
                    raise ValueError('stat_invalid')
                if stat.S_ISCHR(observed.st_mode):
                    if (os.major(observed.st_rdev), os.minor(observed.st_rdev)) in denied_devices:
                        flags[0] = True
                if _dma_link(link):
                    flags[1] = True
                raw = b''
                if directory == 'fd':
                    raw = reader.fdinfo(held_proc_fd, name)
                    if type(raw) is not bytes or not 0 < len(raw) <= MAX_FDINFO_BYTES:
                        raise ValueError('fdinfo_invalid')
                    lines = raw.decode('utf-8').splitlines()
                    if len(lines) > 256:
                        raise ValueError('fdinfo_line_bound')
                    # DMA evidence survives a malformed unrelated core field.
                    if any(line.partition(':')[0].strip() == 'exp_name' for line in lines):
                        flags[1] = True
                    core = {}
                    for line in lines:
                        key, separator, value = line.partition(':')
                        if not separator or not key.strip():
                            raise ValueError('fdinfo_malformed')
                        if key.strip() not in ('pos', 'flags', 'mnt_id', 'ino'):
                            continue  # Resource-specific fields may repeat.
                        if key != key.strip() or key in core:
                            raise ValueError('fdinfo_core_duplicate_or_invalid')
                        value = value.strip()
                        # Linux v6.16 fs/proc/fd.c: %lli, 0%o, %i, %lu.
                        pattern = r'-?[0-9]{1,19}' if key == 'pos' else r'0[0-7]{0,21}' if key == 'flags' else r'[0-9]{1,20}'
                        if re.fullmatch(pattern, value) is None:
                            raise ValueError('fdinfo_core_numeric_invalid')
                        number = int(value, 8 if key == 'flags' else 10)
                        minimum, maximum = ((-(2**63), 2**63-1) if key == 'pos' else
                                            (1, 2**31-1) if key == 'mnt_id' else (0, 2**64-1))
                        if not minimum <= number <= maximum:
                            raise ValueError('fdinfo_core_numeric_range')
                        core[key] = number
                    if set(core) != {'pos', 'flags', 'mnt_id', 'ino'} or core['ino'] != observed.st_ino:
                        raise ValueError('fdinfo_core_missing_or_inode_changed')
                known_channel = directory == 'fd' and (stat.S_ISFIFO(observed.st_mode) or stat.S_ISSOCK(observed.st_mode))
                if (_anonymous_link(link) and not _dma_link(link) and not known_channel) or not (
                        stat.S_ISREG(observed.st_mode) or stat.S_ISCHR(observed.st_mode)
                        or (directory == 'fd' and (stat.S_ISFIFO(observed.st_mode) or stat.S_ISSOCK(observed.st_mode)))):
                    flags[2] = True
                snapshot_rows.append((directory,name,identity,link,raw))
                check()
        return tuple(snapshot_rows)
    try:
        check()
        if type(peer.proc_fd) is not int or peer.proc_fd < 0:
            return result(False, 'peer_invalid')
        held_proc_fd = peer.proc_fd
        revalidate()
        before = snapshot()
        revalidate()
        after = snapshot()
        revalidate()
        return result(before == after, 'observed' if before == after else 'resources_changed')
    except TimeoutError:
        return result(False, 'deadline_expired')
    except (OSError, ValueError, UnicodeError, AttributeError, TypeError, OverflowError):
        return result(False, 'observation_incomplete')
