"""Supervised temporary AMD buffer receive test; never a disconnect clearance.

Explicit invocation opens two authenticated render nodes and allocates temporary
buffers. No mapping, import, submission, player service or display operation.
Only the newly forked receiver is targeted by the transient LSM link.
"""
import json
import math
import os
from pathlib import Path
import platform
import signal
import socket
import stat
import sys
import time
import uuid

if Path(__file__).name != '__main__.py':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

from hdm.delivery.device_filter_btf import parse_dma_buf_receive_btf
from hdm.adapters.steamos.device_receive_symbols import read_receive_symbols
from hdm.delivery.dma_receive_program import compile_dma_receive
from hdm.delivery.device_receive_kernel import FileReceiveLink
from scripts.probe_device_receive_fixture import cleanup_fixture


def _accepted(result, expected):
    return (result['received'] == 1 and result['truncated'] is False
            and result['identity'] == list(expected))


def exercise(identity, *, observe, allocate, owner, compile_program, membership,
             deliver, outside, identify, clock=time.monotonic):
    """Owned allocations are registered by caller immediately on acquisition."""
    started = clock()
    previous = started
    def within_deadline():
        nonlocal previous
        now = clock()
        if (type(started) not in (int, float) or not math.isfinite(started) or started < 0
                or type(now) not in (int, float) or not math.isfinite(now)
                or now < previous or now - started >= 30):
            raise ValueError('fixture deadline unavailable')
        previous = now
    def fresh():
        within_deadline()
        if observe() != identity:
            raise ValueError('fixture context changed or expired')
        within_deadline()
        membership()

    fresh()
    internal = allocate(identity.internal)
    fresh()
    external = allocate(identity.external)
    internal_id, external_id = identify(internal.export_fd), identify(external.export_fd)
    if internal_id == external_id:
        raise ValueError('buffer identities not distinct')
    if (not _accepted(deliver(internal.export_fd, 1), internal_id)
            or not _accepted(deliver(external.export_fd, 2), external_id)):
        raise ValueError('unfiltered buffer delivery unavailable')
    fresh()
    program, hook = compile_program()
    fresh()
    owner.load_attach(program, hook_btf_id=hook)
    denied = deliver(external.export_fd, 3)
    allowed = deliver(internal.export_fd, 4)
    unscoped = outside(external.export_fd, 16)
    owner.close()
    restored = deliver(external.export_fd, 5)
    fresh()
    if (denied['received'] != 0 or denied['truncated'] is not True
            or denied['identity'] is not None or not _accepted(allowed, internal_id)
            or not _accepted(unscoped, external_id) or not _accepted(restored, external_id)):
        raise ValueError('DMA receive enforcement or restoration mismatch')
    return dict(state='fixture_passed', external_receive_denied=True,
                internal_receive_allowed=True, outside_cgroup_allowed=True,
                link_close_restored_receive=True, exporter_receive_verified=True,
                importer_isolation_verified=False, inherited_player_resources_verified=False,
                resources_released=False, disconnect_clearance=False, player_mutation=False,
                temporary_gpu_allocations=True)


class _OwnedResources:
    def __init__(self):
        self.link = None
        self.buffers = []

    def close(self):
        failed = False
        for resource in [self.link, *reversed(self.buffers)]:
            if resource is not None:
                try:
                    resource.close()
                except Exception:
                    failed = True
        if failed:
            raise RuntimeError('GPU fixture cleanup unconfirmed')


def run_fixture():
    if platform.system() != 'Linux' or platform.machine() != 'x86_64' or os.geteuid() != 0:
        raise ValueError('root Linux x86_64 required')
    from hdm.delivery.dma_fixture_buffer import DmaFixtureBuffer
    from scripts.dma_fixture_identity import collect_identity
    from scripts.dma_fixture_transport import receiver, exchange, receive_one, send_descriptor

    identity = collect_identity()
    root = os.open('/sys/fs/cgroup', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    directory = child = first = second = None
    group_identity = None
    created = False
    resources = _OwnedResources()
    name = 'regear-dma-fixture-' + uuid.uuid4().hex
    try:
        rootstat = os.fstat(root)
        if rootstat.st_uid != 0 or rootstat.st_mode & 0o022:
            raise ValueError('unsafe cgroup root')
        control = os.open('cgroup.controllers', os.O_RDONLY | os.O_NOFOLLOW, dir_fd=root)
        os.close(control)
        os.mkdir(name, mode=0o700, dir_fd=root)
        created = True
        directory = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
        group_identity = os.fstat(directory)
        if (group_identity.st_uid != 0 or not group_identity.st_ino
                or group_identity.st_dev != rootstat.st_dev):
            raise ValueError('invalid test cgroup')
        first, second = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        first.settimeout(4)
        parent = os.getpid()
        child = os.fork()
        if child == 0:
            first.close()
            receiver(second, directory, parent)
            os._exit(3)
        second.close()
        second = None
        if first.recv(32) != b'ready':
            raise ValueError('receiver unavailable')

        def membership():
            descriptor = os.open('cgroup.procs', os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
            try:
                occupants = os.read(descriptor, 128).decode().split()
            finally:
                os.close(descriptor)
            current = os.stat(name, dir_fd=root, follow_symlinks=False)
            if (occupants != [str(child)] or not stat.S_ISDIR(current.st_mode)
                    or (current.st_dev, current.st_ino) != (group_identity.st_dev, group_identity.st_ino)):
                raise ValueError('test cgroup changed')

        def allocate(target):
            buffer = DmaFixtureBuffer()
            resources.buffers.append(buffer)
            buffer.allocate(target.path, target.device)
            return buffer

        def compile_program():
            with open('/sys/kernel/btf/vmlinux', 'rb') as source:
                raw = source.read(64 * 1024 * 1024 + 1)
            layout = parse_dma_buf_receive_btf(raw, pointer_size=8)
            symbols = read_receive_symbols()
            program = compile_dma_receive((group_identity.st_ino,),
                ((os.major(identity.external.device), os.minor(identity.external.device)),),
                layout=layout, dma_buf_fops=symbols.dma_buf_fops,
                amdgpu_dmabuf_ops=symbols.amdgpu_dmabuf_ops,
                allowed_internal_primary_minor=identity.internal.primary_minor)
            return program, layout.receive.hook_btf_id

        def outside(fd, sequence):
            left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
            try:
                left.settimeout(2)
                right.settimeout(2)
                send_descriptor(left, fd, sequence)
                return receive_one(right, sequence)
            finally:
                try:
                    left.close()
                finally:
                    right.close()

        def identify(fd):
            info = os.fstat(fd)
            return info.st_dev, info.st_ino

        resources.link = FileReceiveLink()
        report = exercise(identity, observe=collect_identity, allocate=allocate,
            owner=resources.link, compile_program=compile_program, membership=membership,
            deliver=lambda fd, sequence: exchange(first, fd, sequence), outside=outside,
            identify=identify)
    finally:
        cleanup_fixture(resources, (), first, second, child, directory, root,
                        name, group_identity, created)
    return report


def main():
    if sys.argv[1:] != ['--supervised-dma-fixture']:
        raise SystemExit('Explicit --supervised-dma-fixture required')
    previous = {}
    def interrupted(signum, frame):
        raise RuntimeError('fixture interrupted')
    try:
        if platform.system() == 'Linux':
            for number in (signal.SIGINT, signal.SIGTERM, signal.SIGALRM):
                previous[number] = signal.signal(number, interrupted)
            signal.alarm(45)
        report = run_fixture()
    except Exception:
        report = dict(state='fixture_failed', code='test_or_cleanup_unconfirmed',
                      disconnect_clearance=False, resources_released=False)
    finally:
        if previous:
            signal.alarm(0)
            for number, handler in previous.items():
                signal.signal(number, handler)
    print(json.dumps(report, sort_keys=True))
    return 0 if report['state'] == 'fixture_passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
