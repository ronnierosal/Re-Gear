"""Happy-path disposable paired BPF recovery through the actual durable journal.

No player service is accessed: the required unit label is synthetic fixture
binding data. Only a fresh dummy cgroup and null/zero receipt are exercised.
Failed ownership remains pinned/journaled and the cgroup is retained.
"""
import hashlib
import json
import os
from pathlib import Path
import platform
import socket
import stat
import sys
import time
import uuid

if Path(__file__).name!='__main__.py':
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))

from hdm.delivery.device_filter_journal import FilterJournal
from hdm.delivery.device_filter_lifecycle import LaunchBinding,Phase,PairedStage,PairedReceiveIdentity,paired_token
from hdm.delivery.device_filter_recovery import FilterRecovery
from hdm.delivery.device_filter_pin_directory import FilterPinDirectory,_root_directory
from hdm.delivery.cgroup_retention_map import CgroupRetentionMap,MapIdentity
from hdm.delivery.device_receive_kernel import FileReceiveLink,ReceiveIdentity
from hdm.delivery.device_receive_program import compile_device_receive
from hdm.delivery.device_filter_btf import parse_file_receive_btf
from scripts.probe_paired_owner_death import boot_hash,close_all
from scripts.probe_killed_filter_controller import _child_setup
from scripts.probe_device_receive_fixture import receiver,exchange,cleanup_fixture
from scripts.probe_receive_pin_fixture import _received,_denied,_error_fields


def create_journal_directory():
    flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC
    parent=os.open('/',flags)
    child=directory=None
    try:
        _root_directory(parent)
        child=os.open('run',flags,dir_fd=parent);_root_directory(child)
        name='regear-paired-journal-'+uuid.uuid4().hex
        os.mkdir(name,0o700,dir_fd=child)
        directory=os.open(name,flags,dir_fd=child);_root_directory(directory,private=True)
        os.fsync(directory);os.fsync(child)
        result=Path('/run')/name,directory
        directory=None
        return result
    finally:
        pending=sys.exc_info()[0] is not None
        errors=[]
        for fd in (directory,child,parent):
            if fd is not None:
                try:os.close(fd)
                except OSError as error:errors.append(error)
        if errors and not pending:raise errors[0]


def publish_journal_pair(journal,binding,directory,layout,null_device,*,
                         map_factory=CgroupRetentionMap,receive_factory=FileReceiveLink,
                         pins_factory=FilterPinDirectory,compiler=compile_device_receive,
                         observe_denial,stage=lambda value:None,before_receive_pin_checkpoint=None):
    if before_receive_pin_checkpoint is not None and not callable(before_receive_pin_checkpoint):
        raise ValueError('explicit checkpoint callback required')
    retained=receive=pins=None
    try:
        with journal.transaction() as tx:
            record=tx.read(binding.operation,binding.unit)
            if record.lifecycle.binding!=binding or record.lifecycle.phase is not Phase.REQUESTED or record.paired is not None:
                raise ValueError('fresh journal request required')
            def change(action,**evidence):
                nonlocal record
                record=tx.change(binding.operation,binding.unit,record.revision,action,**evidence)
            stage('map_create');retained=map_factory();expected_map=retained.create(directory)
            if type(expected_map) is not MapIdentity or retained.identity()!=expected_map:
                raise ValueError('map identity mismatch')
            stage('retention_intent');change('retention_intent',map_id=expected_map.map_id)
            pins=pins_factory(create=True)
            stage('map_pin');retained.pin(pins.fd,paired_token(binding,'retention'),expected_map)
            change('retention_confirmed')
            stage('receive_load')
            program=compiler((binding.cgroup_inode,),((os.major(null_device),os.minor(null_device)),),
                file_inode_offset=layout.file_inode_offset,inode_mode_offset=layout.inode_mode_offset,
                inode_rdev_offset=layout.inode_rdev_offset)
            receive=receive_factory();receive.load_attach(program,hook_btf_id=layout.hook_btf_id)
            expected=receive.link_identity()
            if type(expected) is not ReceiveIdentity:raise ValueError('receive identity unavailable')
            stage('receive_intent');change('receive_intent',receive=PairedReceiveIdentity(
                expected.link_id,expected.program_id,expected.hook_btf_id,expected.target_obj_id))
            if before_receive_pin_checkpoint is None:
                stage('receive_pin');receive.pin(pins.fd,paired_token(binding,'receive'),expected)
                change('receive_confirmed')
        if before_receive_pin_checkpoint is not None:
            before_receive_pin_checkpoint()
            raise ValueError('before-pin checkpoint returned without owner death')
        # No journal lock is held during the receiver round trip.
        stage('initial_denial')
        if observe_denial() is not True:raise ValueError('dummy denial unavailable')
    finally:
        close_all(receive,retained,pins)


def recover_journal_pair(journal_factory,binding,*,current_boot_hash,observe_denial,
                         observe_restored,recovery_factory=FilterRecovery):
    """Construct a new reader; require persisted cancellation and completion."""
    journal=journal_factory()
    with journal.transaction() as tx:before=tx.read(binding.operation,binding.unit)
    if (before.lifecycle.binding!=binding or before.lifecycle.phase is not Phase.REQUESTED
            or before.paired is None or before.paired.stage is not PairedStage.RECEIVE_CONFIRMED
            or before.delivery_granted):raise ValueError('durable paired publication unavailable')
    if observe_denial() is not True:raise ValueError('pinned denial absent')
    result=recovery_factory(journal).recover(binding.operation,binding.unit,current_boot_hash=current_boot_hash)
    with journal.transaction() as tx:after=tx.read(binding.operation,binding.unit)
    if (result.outcome!='cancelled_without_owned_identity' or result.launch_authorized or result.disconnect_clearance
            or after.lifecycle.binding!=binding or after.lifecycle.phase is not Phase.CANCELLED
            or after.paired is None or after.paired.stage is not PairedStage.COMPLETE
            or after.paired.receive!=before.paired.receive or after.paired.map_id!=before.paired.map_id
            or after.delivery_granted or after.revision<=before.revision):
        raise ValueError('durable paired recovery incomplete')
    if observe_restored() is not True:raise ValueError('dummy receipt not restored')
    return dict(durable_cancellation_observed=True,paired_complete_observed=True,
                null_zero_restored=True,launch_authorized=False,disconnect_clearance=False)


def run_fixture(*,publisher=publish_journal_pair,recoverer=recover_journal_pair,
                receiver_factory=receiver,extra_probe=None):
    report=dict(state='unverified',stage='platform',journal_retained=False,cgroup_retained=False,
                launch_authorized=False,disconnect_clearance=False,player_mutation=False,synthetic_binding=True)
    root=directory=journal_fd=null=zero=None
    first=second=None
    child=identity=None
    created=complete=False
    name='regear-journal-receive-fixture-'+uuid.uuid4().hex
    def stage(value):report['stage']=value
    try:
        if platform.system()!='Linux' or platform.machine()!='x86_64' or getattr(os,'geteuid',lambda:-1)()!=0:
            raise ValueError('root Linux x86_64 required')
        uid=os.environ.get('SUDO_UID','')
        if not uid.isdecimal() or not 0<int(uid)<2**32:raise ValueError('supervised UID required')
        stage('btf')
        with open('/sys/kernel/btf/vmlinux','rb') as source:raw=source.read(64*1024*1024+1)
        layout=parse_file_receive_btf(raw,pointer_size=8)
        stage('cgroup')
        root=os.open('/sys/fs/cgroup',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW);_root_directory(root)
        control=os.open('cgroup.controllers',os.O_RDONLY|os.O_NOFOLLOW,dir_fd=root);os.close(control)
        os.mkdir(name,0o700,dir_fd=root);created=True
        directory=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=root)
        _root_directory(directory,private=True);identity=os.fstat(directory)
        if identity.st_dev!=os.fstat(root).st_dev or not identity.st_ino:raise ValueError('cgroup identity invalid')
        stage('receiver')
        first,second=socket.socketpair(socket.AF_UNIX,socket.SOCK_SEQPACKET);first.settimeout(4)
        parent=os.getpid();child=os.fork()
        if child==0:
            try:
                _child_setup(parent,{second.fileno(),directory});receiver_factory(second,directory,parent)
            except BaseException:os._exit(2)
        second.close();second=None
        if first.recv(32)!=b'ready':raise ValueError('receiver unavailable')
        def validate_group():
            current=os.stat(name,dir_fd=root,follow_symlinks=False)
            if not stat.S_ISDIR(current.st_mode) or (current.st_dev,current.st_ino)!=(identity.st_dev,identity.st_ino):
                raise ValueError('cgroup identity changed')
            member=os.open('cgroup.procs',os.O_RDONLY|os.O_NOFOLLOW,dir_fd=directory)
            try:
                if os.read(member,128).decode().split()!=[str(child)]:raise ValueError('receiver membership changed')
            finally:os.close(member)
        validate_group()
        with open('/proc/'+str(child)+'/stat','r') as source:raw_stat=source.read(4097)
        if len(raw_stat)>4096:raise ValueError('receiver identity unbounded')
        starttime=int(raw_stat.rsplit(')',1)[1].split()[19])
        binding=LaunchBinding(boot_hash(),uuid.uuid4().hex,'gamescope-session.service',uuid.uuid4().hex,
            int(uid),child,starttime,identity.st_dev,identity.st_ino,
            hashlib.sha256(b'disposable-null-zero-journal-fixture').hexdigest(),time.monotonic()+30)
        stage('journal_create');journal_path,journal_fd=create_journal_directory();report['journal_retained']=True
        def journal_factory():return FilterJournal(journal_path,owner_uid=0,trusted_directory_fd=journal_fd)
        journal=journal_factory();journal.create(binding)
        null=os.open('/dev/null',os.O_RDONLY|os.O_NOFOLLOW);zero=os.open('/dev/zero',os.O_RDONLY|os.O_NOFOLLOW)
        ns,zs=os.fstat(null),os.fstat(zero)
        if (not stat.S_ISCHR(ns.st_mode) or not stat.S_ISCHR(zs.st_mode)
                or ns.st_rdev!=os.makedev(1,3) or zs.st_rdev!=os.makedev(1,5)):
            raise ValueError('dummy device mismatch')
        def denial():
            validate_group()
            result=_denied(exchange(first,null)) and _received(exchange(first,zero),zs.st_rdev)
            return result and (extra_probe is None or extra_probe(first,denied=True) is True)
        def restored():
            validate_group()
            result=_received(exchange(first,null),ns.st_rdev) and _received(exchange(first,zero),zs.st_rdev)
            return result and (extra_probe is None or extra_probe(first,denied=False) is True)
        if not restored():raise ValueError('baseline unavailable')
        publisher(journal,binding,directory,layout,ns.st_rdev,observe_denial=denial,stage=stage)
        stage('journal_recovery')
        report.update(recoverer(journal_factory,binding,current_boot_hash=boot_hash(),
            observe_denial=denial,observe_restored=restored))
        complete=True;report['state']='fixture_passed'
    except Exception as error:report.update(state='fixture_failed',**_error_fields(error))
    finally:
        report['cgroup_retained']=created and not complete
        if root is not None:
            try:cleanup_fixture(None,(null,zero),first,second,child,directory,root,name,identity,created and complete)
            except Exception as error:
                report.update(state='fixture_failed',cgroup_retained=created,cleanup_error=_error_fields(error))
        if journal_fd is not None:
            try:os.close(journal_fd)
            except Exception as error:report.update(state='fixture_failed',journal_cleanup_error=_error_fields(error))
    return report


def main():
    if sys.argv[1:]!=['--disposable-fixture']:raise SystemExit('Explicit --disposable-fixture required')
    report=run_fixture();print(json.dumps(report,sort_keys=True))
    return 0 if report['state']=='fixture_passed' else 1


if __name__=='__main__':raise SystemExit(main())
