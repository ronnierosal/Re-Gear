"""Supervised temporary AMD preparation fixture, never disconnect clearance.

Uses actual journal/preparation/recovery controllers against a disposable child.
Only this fixture allocates two small GPU buffers. No player services, mapping,
submission, import, audio or display changes. Recovery uncertainty retains the
private journal and cgroup. Journal is same-boot evidence under /run.
"""
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

if Path(__file__).name!='__main__.py':sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))

from hdm.delivery.device_filter_attachment import AttachmentObservation
from hdm.delivery.device_receive_layout_cache import DmaReceiveLayoutCache
from hdm.delivery.device_filter_journal import FilterJournal
from hdm.delivery.device_filter_lifecycle import LaunchBinding,Phase,PairedStage
from hdm.delivery.device_filter_preparation import FilterPreparation
from hdm.delivery.device_filter_recovery import FilterRecovery
from hdm.delivery.device_receive_attachment import DmaReceiveObservation,DmaReceiveAttachmentPolicy
from hdm.delivery.dma_receive_program import compile_dma_receive
from hdm.adapters.steamos.device_receive_symbols import read_receive_symbols
from scripts.probe_dma_receive_fixture import _accepted
from scripts.probe_killed_filter_controller import terminate_owned
from scripts.probe_paired_owner_death import boot_hash
from scripts.probe_paired_journal_fixture import create_journal_directory
from scripts.probe_receive_pin_fixture import _error_fields


def exercise(*,internal,external,identify,deliver,outside,prepare,recover,validate):
    """Resource owners live in caller; completion requires ordered restoration."""
    validate()
    first,second=identify(internal),identify(external)
    if first==second:raise ValueError('buffer identities overlap')
    if not _accepted(deliver(internal,1),first) or not _accepted(deliver(external,2),second):
        raise ValueError('baseline delivery unavailable')
    validate()
    result=prepare()
    if result.prepared is not True or result.launch_authorized or result.disconnect_clearance:
        raise ValueError('preparation not confirmed')
    denied=deliver(external,3)
    allowed=deliver(internal,4)
    unscoped=outside(external,16)
    validate()
    if (denied['received']!=0 or denied['truncated'] is not True or denied['identity'] is not None
            or not _accepted(allowed,first) or not _accepted(unscoped,second)):
        raise ValueError('prepared DMA controls mismatch')
    recover()
    if not _accepted(deliver(external,5),second):raise ValueError('DMA restoration unavailable')
    validate()
    return dict(state='fixture_passed',combined_preparation_verified=True,
        external_receive_denied=True,internal_receive_allowed=True,outside_cgroup_allowed=True,
        recovery_restored_receive=True,exporter_receive_verified=True,
        importer_isolation_verified=False,inherited_player_resources_verified=False,
        disconnect_clearance=False,launch_authorized=False,player_mutation=False,
        temporary_gpu_allocations=True,journal_retained=True)


def run_fixture(*,stage=lambda value:None):
    stage('preflight')
    if platform.system()!='Linux' or platform.machine()!='x86_64' or os.geteuid()!=0:
        raise ValueError('root Linux x86_64 required')
    from scripts.dma_fixture_identity import collect_identity
    from scripts.dma_fixture_transport import receiver,exchange,send_descriptor,receive_one
    from hdm.delivery.dma_fixture_buffer import DmaFixtureBuffer
    from hdm.delivery.device_filter_kernel import CgroupDeviceLink
    from hdm.delivery.device_filter_pin_directory import FilterPinDirectory
    raw_uid=os.environ.get('SUDO_UID','')
    if not raw_uid.isdecimal() or not 0<int(raw_uid)<2**32:raise ValueError('supervised UID required')
    identity=collect_identity()
    layout_cache=DmaReceiveLayoutCache()
    # Establish an authenticated pin directory before any owned attachment.
    pins=FilterPinDirectory(create=True);pins.close()
    root=directory=journal_fd=None
    first=second=None
    child=None
    journal=binding=None
    group=None
    buffers=[]
    created=False
    recovered=False
    errors=[]
    name='regear-dma-preparation-fixture-'+uuid.uuid4().hex
    def recover_owned():
        nonlocal recovered
        outcome=FilterRecovery(journal).recover(binding.operation,binding.unit,
            current_boot_hash=boot_hash())
        with journal.transaction() as tx:record=tx.read(binding.operation,binding.unit)
        if (outcome.outcome!='owned_pin_removed' or outcome.launch_authorized or outcome.disconnect_clearance
                or record.lifecycle.binding!=binding or record.lifecycle.phase is not Phase.CANCELLED
                or record.paired is None or record.paired.stage is not PairedStage.COMPLETE):
            raise ValueError('paired/direct recovery unresolved')
        with CgroupDeviceLink() as query:
            if query.query_program_ids(directory):raise ValueError('direct filter remains')
        recovered=True
    try:
        stage('cgroup_create')
        root=os.open('/sys/fs/cgroup',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        info=os.fstat(root)
        if info.st_uid!=0 or info.st_mode&0o022:raise ValueError('unsafe cgroup root')
        control=os.open('cgroup.controllers',os.O_RDONLY|os.O_NOFOLLOW,dir_fd=root);os.close(control)
        os.mkdir(name,0o700,dir_fd=root);created=True
        directory=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=root)
        group=os.fstat(directory)
        if group.st_uid!=0 or group.st_dev!=info.st_dev:raise ValueError('cgroup identity unavailable')
        stage('receiver_start')
        first,second=socket.socketpair(socket.AF_UNIX,socket.SOCK_SEQPACKET)
        parent=os.getpid();child=os.fork()
        if child==0:receiver(second,directory,parent,idle_timeout=60)
        second.close();second=None
        first.settimeout(5)
        if first.recv(32)!=b'ready':raise ValueError('receiver unavailable')
        with open(f'/proc/{child}/stat') as source:starttime=int(source.read(4096).rsplit(')',1)[1].split()[19])
        binding=LaunchBinding(boot_hash(),uuid.uuid4().hex,'gamescope-session.service',
            uuid.uuid4().hex,int(raw_uid),child,starttime,group.st_dev,group.st_ino,identity.context_digest,time.monotonic()+60)
        stage('journal_create')
        journal_path,journal_fd=create_journal_directory()
        journal=FilterJournal(journal_path,owner_uid=0,trusted_directory_fd=journal_fd)
        journal.create(binding)
        denied=((os.major(identity.external.device),os.minor(identity.external.device)),)
        def validate():
            if time.monotonic()>=binding.deadline or boot_hash()!=binding.boot_hash or collect_identity()!=identity:
                raise ValueError('fresh DMA context changed')
            member=os.open('cgroup.procs',os.O_RDONLY|os.O_NOFOLLOW,dir_fd=directory)
            try:
                if os.read(member,128).decode().split()!=[str(child)]:raise ValueError('receiver membership changed')
            finally:os.close(member)
            current=os.stat(name,dir_fd=root,follow_symlinks=False)
            if not stat.S_ISDIR(current.st_mode) or (current.st_dev,current.st_ino)!=(group.st_dev,group.st_ino):
                raise ValueError('cgroup changed')
        def observe():
            validate()
            return AttachmentObservation(binding,denied,True,True)
        def observe_dma():
            started=time.monotonic()
            with open('/sys/kernel/btf/vmlinux','rb') as source:raw=source.read(64*1024*1024+1)
            cached=layout_cache.parse(raw,pointer_size=8)
            layout=cached.layout
            symbols=read_receive_symbols()
            validate()
            return DmaReceiveObservation(binding,layout,symbols.dma_buf_fops,symbols.amdgpu_dmabuf_ops,
                identity.internal.primary_minor,cached.btf_sha256,started)
        stage('buffer_allocate')
        for target in (identity.internal,identity.external):
            validate()
            buffer=DmaFixtureBuffer();buffers.append(buffer);buffer.allocate(target.path,target.device)
        stage('policy_observe')
        evidence=observe_dma()
        code=compile_dma_receive((group.st_ino,),denied,layout=evidence.layout,dma_buf_fops=evidence.dma_buf_fops,
            amdgpu_dmabuf_ops=evidence.amdgpu_dmabuf_ops,allowed_internal_primary_minor=evidence.internal_primary_minor)
        policy=DmaReceiveAttachmentPolicy(binding,evidence,hashlib.sha256(code).hexdigest())
        del code
        with CgroupDeviceLink() as query:
            if query.query_program_ids(directory):raise ValueError('preexisting direct filters')
        def outside(fd,sequence):
            left,right=socket.socketpair(socket.AF_UNIX,socket.SOCK_SEQPACKET)
            try:send_descriptor(left,fd,sequence);return receive_one(right,sequence)
            finally:
                try:left.close()
                finally:right.close()
        def identify(fd):
            item=os.fstat(fd);return item.st_dev,item.st_ino
        def prepare():
            stage('prepare')
            return FilterPreparation(journal,observe,observe_dma=observe_dma).prepare(
                binding.operation,binding.unit,directory,policy=policy)
        def recover():
            stage('recover')
            recover_owned()
        stage('controls')
        report=exercise(internal=buffers[0].export_fd,external=buffers[1].export_fd,identify=identify,
            deliver=lambda fd,seq:exchange(first,fd,seq),outside=outside,validate=validate,
            prepare=prepare,recover=recover)
    finally:
        def attempt(action):
            try:action()
            except BaseException:errors.append(True)
        if journal is not None and binding is not None and not recovered:attempt(recover_owned)
        for buffer in reversed(buffers):attempt(buffer.close)
        for sock in (first,second):
            if sock is not None:attempt(sock.close)
        if child is not None and child>0:attempt(lambda:terminate_owned(child))
        if created:
            def remove():
                if group is None or (journal is not None and not recovered):raise ValueError('retain unresolved cgroup')
                current=os.stat(name,dir_fd=root,follow_symlinks=False)
                if not stat.S_ISDIR(current.st_mode) or (current.st_dev,current.st_ino)!=(group.st_dev,group.st_ino):
                    raise ValueError('cgroup replaced')
                os.rmdir(name,dir_fd=root)
            attempt(remove)
        for fd in (directory,journal_fd,root):
            if fd is not None:attempt(lambda fd=fd:os.close(fd))
        if errors:
            stage('cleanup_unresolved')
            raise RuntimeError('DMA preparation cleanup unresolved')
    return report


def main():
    if sys.argv[1:]==['--tests']:
        import unittest
        result=unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromName('tests.test_dma_preparation_fixture'))
        return 0 if result.wasSuccessful() else 1
    if sys.argv[1:]!=['--supervised-dma-preparation']:raise SystemExit('Explicit supervised DMA preparation required')
    previous={}
    current=['startup']
    def interrupted(*_):raise RuntimeError('fixture interrupted')
    try:
        if platform.system()=='Linux':
            for number in (signal.SIGINT,signal.SIGTERM,signal.SIGALRM):previous[number]=signal.signal(number,interrupted)
            signal.alarm(90)
        report=run_fixture(stage=lambda value:current.__setitem__(0,value))
    except Exception as error:
        report=dict(state='fixture_failed',code='test_or_cleanup_unconfirmed',stage=current[0],
                    **_error_fields(error),disconnect_clearance=False)
    finally:
        if previous:
            signal.alarm(0)
            for number,handler in previous.items():signal.signal(number,handler)
    print(json.dumps(report,sort_keys=True))
    return 0 if report['state']=='fixture_passed' else 1


if __name__=='__main__':raise SystemExit(main())
