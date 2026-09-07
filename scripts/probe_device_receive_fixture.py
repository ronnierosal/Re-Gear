"""Disposable root-only SCM_RIGHTS fixture. Never opens graphics/audio devices.

Creates one empty cgroup containing only a forked test receiver. An unpinned
LSM link denies receipt of /dev/null in that exact cgroup. /dev/zero and the
parent are controls; after link close /dev/null must be receivable again.
No player service operations, hardware claims, inherited or DMA-buffer coverage.
"""
import array
import ctypes
import hashlib
import json
import os
from pathlib import Path
import platform
import signal
import socket
import stat
import sys
import time
import uuid

if __name__ == '__main__' and Path(__file__).name != '__main__.py':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

from hdm.delivery.device_filter_btf import parse_file_receive_btf
from hdm.delivery.device_receive_program import compile_device_receive
from hdm.delivery.device_receive_kernel import FileReceiveLink


def receive_one(sock):
    data, ancillary, flags, _ = sock.recvmsg(16, socket.CMSG_SPACE(array.array('i').itemsize))
    descriptors = []
    try:
        for level, kind, raw in ancillary:
            if level != socket.SOL_SOCKET or kind != socket.SCM_RIGHTS:
                raise ValueError('unexpected ancillary data')
            values = array.array('i')
            values.frombytes(raw[:len(raw) - len(raw) % values.itemsize])
            descriptors.extend(values)
        if data == b'stop':
            return None
        if data != b'fd' or len(descriptors) > 1:
            raise ValueError('unexpected fixture packet')
        return dict(received=len(descriptors), truncated=bool(flags & socket.MSG_CTRUNC),
                    device=os.fstat(descriptors[0]).st_rdev if descriptors else None)
    finally:
        for descriptor in descriptors:
            os.close(descriptor)


def exchange(sock, fd):
    if sock.sendmsg([b'fd'], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array('i',[fd]))]) != 2:
        raise ValueError('short fixture descriptor send')
    raw = sock.recv(512)
    result = json.loads(raw)
    if type(result) is not dict or set(result) != {'received','truncated','device'}:
        raise ValueError('invalid fixture response')
    return result


def receiver(sock, directory, parent):
    try:
        # Exit if controller dies; the child never inherits a loaded BPF link.
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0 or os.getppid() != parent:
            os._exit(3)
        descriptor=os.open('cgroup.procs',os.O_WRONLY|os.O_NOFOLLOW,dir_fd=directory)
        try: os.write(descriptor,str(os.getpid()).encode())
        finally: os.close(descriptor)
        sock.settimeout(8)
        if sock.send(b'ready') != 5:os._exit(2)
        for _ in range(8):
            result=receive_one(sock)
            if result is None: break
            payload=json.dumps(result).encode()
            if sock.send(payload)!=len(payload):os._exit(2)
    except BaseException:
        os._exit(2)
    os._exit(0)


def cleanup_fixture(owner, descriptors, first, second, child, directory, root, name, identity, created):
    errors=[]
    def attempt(operation):
        try:operation()
        except Exception as exc:errors.append(type(exc).__name__)
    if owner is not None:attempt(owner.close)
    for descriptor in descriptors:
        if descriptor is not None:attempt(lambda fd=descriptor:os.close(fd))
    if first is not None:
        # A closed peer is ordinary after a failed child, but close is mandatory.
        try:first.send(b'stop')
        except OSError:pass
        attempt(first.close)
    if second is not None:attempt(second.close)
    def reap():
        deadline=time.monotonic()+2
        while True:
            done,_=os.waitpid(child,os.WNOHANG)
            if done:return
            if time.monotonic()>=deadline:
                os.kill(child,signal.SIGKILL)
                os.waitpid(child,0)
                return
            time.sleep(0.02)
    if child is not None and child>0:attempt(reap)
    if directory is not None:attempt(lambda:os.close(directory))
    def remove_owned():
        if identity is None:
            raise ValueError('cgroup identity unavailable; retaining directory')
        current=os.stat(name,dir_fd=root,follow_symlinks=False)
        if (current.st_dev,current.st_ino)!=(identity.st_dev,identity.st_ino) or not stat.S_ISDIR(current.st_mode):
            raise ValueError('cgroup identity changed; retaining directory')
        os.rmdir(name,dir_fd=root)
    if created:attempt(remove_owned)
    attempt(lambda:os.close(root))
    if errors:raise RuntimeError('fixture cleanup incomplete: '+','.join(errors))


def run_fixture():
    report=dict(state='unverified', disconnect_clearance=False, player_mutation=False,
                dma_buf_verified=False, inherited_resources_verified=False)
    if os.geteuid()!=0 or platform.system()!='Linux' or platform.machine()!='x86_64':
        raise ValueError('fixture requires root Linux x86_64')
    # Resolve metadata now; no saved kernel offset or hook ID is used.
    with open('/sys/kernel/btf/vmlinux','rb') as source: raw=source.read(64*1024*1024+1)
    layout=parse_file_receive_btf(raw,pointer_size=8)
    report['btf_sha256']=hashlib.sha256(raw).hexdigest()
    root=os.open('/sys/fs/cgroup',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    name='regear-receive-fixture-'+uuid.uuid4().hex
    directory=None; child=None; first=second=None; owner=None
    null=zero=None; created=False; identity=None
    try:
        rootstat=os.fstat(root)
        if rootstat.st_uid!=0 or rootstat.st_mode & 0o022:
            raise ValueError('unsafe cgroup root')
        # Presence of the v2 control file is required before making the child.
        control=os.open('cgroup.controllers',os.O_RDONLY|os.O_NOFOLLOW,dir_fd=root)
        os.close(control)
        os.mkdir(name,mode=0o700,dir_fd=root);created=True
        directory=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=root)
        identity=os.fstat(directory)
        if identity.st_uid!=0 or not identity.st_ino or identity.st_dev!=rootstat.st_dev:
            raise ValueError('invalid disposable cgroup')
        first,second=socket.socketpair(socket.AF_UNIX,socket.SOCK_SEQPACKET)
        first.settimeout(4)
        parent=os.getpid()
        child=os.fork()
        if child==0:
            first.close()
            receiver(second,directory,parent)
        second.close();second=None
        if first.recv(32)!=b'ready':raise ValueError('receiver failed to enter cgroup')
        members=os.open('cgroup.procs',os.O_RDONLY|os.O_NOFOLLOW,dir_fd=directory)
        try: occupants=os.read(members,128).decode().split()
        finally:os.close(members)
        if occupants != [str(child)]:raise ValueError('fixture cgroup not exclusive')
        null=os.open('/dev/null',os.O_RDONLY|os.O_NOFOLLOW)
        zero=os.open('/dev/zero',os.O_RDONLY|os.O_NOFOLLOW)
        ns,zs=os.fstat(null),os.fstat(zero)
        if not stat.S_ISCHR(ns.st_mode) or not stat.S_ISCHR(zs.st_mode) or ns.st_rdev==zs.st_rdev:
            raise ValueError('fixture control devices unavailable')
        baseline=exchange(first,null)
        if baseline['received']!=1 or baseline['truncated'] or baseline['device']!=ns.st_rdev:
            raise ValueError('baseline descriptor delivery unavailable')
        program=compile_device_receive((identity.st_ino,),((os.major(ns.st_rdev),os.minor(ns.st_rdev)),),
            file_inode_offset=layout.file_inode_offset,inode_mode_offset=layout.inode_mode_offset,
            inode_rdev_offset=layout.inode_rdev_offset)
        owner=FileReceiveLink()
        owner.load_attach(program,hook_btf_id=layout.hook_btf_id)
        denied=exchange(first,null)
        allowed=exchange(first,zero)
        # Same denied device delivered outside target cgroup must remain usable.
        left,right=socket.socketpair(socket.AF_UNIX,socket.SOCK_SEQPACKET)
        try:
            right.settimeout(2)
            if left.sendmsg([b'fd'],[(socket.SOL_SOCKET,socket.SCM_RIGHTS,array.array('i',[null]))])!=2:
                raise ValueError('short outside control send')
            outside=receive_one(right)
        finally:
            try:left.close()
            finally:right.close()
        owner.close()
        restored=exchange(first,null)
        if (denied['received']!=0 or not denied['truncated']
                or allowed['received']!=1 or allowed['truncated'] or allowed['device']!=zs.st_rdev
                or outside['received']!=1 or outside['truncated'] or outside['device']!=ns.st_rdev
                or restored['received']!=1 or restored['truncated'] or restored['device']!=ns.st_rdev):
            raise ValueError('receive fixture enforcement or restoration mismatch')
        report.update(state='fixture_passed', target_receive_denied=True, other_device_allowed=True,
                      outside_cgroup_allowed=True, link_close_restored_receive=True)
    finally:
        cleanup_fixture(owner, (null,zero), first, second, child, directory,
                        root, name, identity, created)
    return report


def main():
    if sys.argv[1:]!=['--disposable-fixture']:
        raise SystemExit('Explicit --disposable-fixture required')
    try:report=run_fixture()
    except (OSError,ValueError,RuntimeError) as exc:
        print(json.dumps(dict(state='fixture_failed',error=type(exc).__name__+': '+str(exc),
                             disconnect_clearance=False,player_mutation=False)))
        return 1
    print(json.dumps(report,sort_keys=True));return 0


if __name__=='__main__':raise SystemExit(main())
