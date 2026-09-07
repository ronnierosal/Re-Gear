"""Explicit disposable SCM_RIGHTS pin-lifetime fixture; no player devices."""
from dataclasses import asdict
from enum import Enum
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import socket
import stat
import sys
import time
import uuid

if Path(__file__).name != '__main__.py':
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))

from scripts.probe_device_receive_fixture import exchange, receiver, cleanup_fixture
from hdm.delivery.device_receive_kernel import FileReceiveLink, ReceiveIdentity
from hdm.delivery.device_receive_program import compile_device_receive
from hdm.delivery.device_filter_btf import parse_file_receive_btf
from hdm.delivery.device_filter_pin_directory import FilterPinDirectory


class Stage(str,Enum):
    PLATFORM='platform'
    BTF_READ='btf_read'
    BTF_PARSE='btf_parse'
    CGROUP_ROOT='cgroup_root'
    CGROUP_CREATE='cgroup_create'
    RECEIVER='receiver'
    DEVICES='devices'
    BASELINE='baseline'
    PIN_DIRECTORY='pin_directory'
    OWNER='owner'
    COMPILE='compile'
    LOAD_ATTACH='load_attach'
    LINK_IDENTITY='link_identity'
    JOURNAL='journal'
    PIN='pin'
    INITIAL_DENY='initial_deny'
    RECOVER='recover'
    CONTROL='control'
    EXTRA_HOLDER='extra_holder'
    UNLINK='unlink'
    EXTRA_DENY='extra_deny'
    RELEASE='release'
    RESTORED='restored'
    CLEANUP='cleanup'
    RETENTION_PREPARE='retention_prepare'
    RETENTION_RELEASE='retention_release'


def _error_fields(error):
    allowed={'OSError','PermissionError','FileNotFoundError','FileExistsError',
             'ValueError','RuntimeError','TimeoutError','TypeError','AttributeError'}
    kind=type(error).__name__
    number=getattr(error,'errno',None)
    return dict(error_type=kind if kind in allowed else 'UnexpectedError',
                errno=number if type(number) is int and 0<=number<=4095 else None)


class DiagnosticReceiveLink(FileReceiveLink):
    """Retain only categorical operation and bounded public link-shape fields."""
    def __init__(self,report):
        self.report=report
        super().__init__()
    def _call(self,command,attr):
        requested_length=getattr(attr,'info_len',0)
        self.report['kernel_operation']={5:'program_load',28:'link_create',15:'object_info',
            6:'object_pin',7:'object_get',13:'program_lookup'}.get(command,'other')
        result=super()._call(command,attr)
        if command==15 and requested_length==32 and 28<=attr.info_len<=64:
            words=(ctypes.c_uint32*7).from_address(attr.info)
            self.report['link_shape']=dict(info_length=int(attr.info_len),
                link_type=int(words[0]),attach_type=int(words[4]),target_object_present=words[5]!=0,
                hook_present=words[6]!=0)
        return result


def _received(result, device):
    return (type(result) is dict and set(result)=={'received','truncated','device'}
            and type(result['received']) is int and result['received']==1
            and result['truncated'] is False and type(result['device']) is int
            and result['device']==device)


def _denied(result):
    return (type(result) is dict and set(result)=={'received','truncated','device'}
            and type(result['received']) is int and result['received']==0
            and result['truncated'] is True and result['device'] is None)


def exercise_pin_lifetime(owner, *, directory_fd, token, expected, journal,
                          null_exchange, zero_exchange, zero_device, null_device,
                          unlink_exact, link_factory=FileReceiveLink,
                          clock=time.monotonic, wait=time.sleep, on_stage=lambda stage:None):
    """No cleanup inference from unlink: an extra link holder must keep denial."""
    if type(expected) is not ReceiveIdentity or owner.link_identity()!=expected:
        raise ValueError('initial receive identity mismatch')
    extra=None
    try:
        on_stage(Stage.JOURNAL)
        journal(expected)  # Must durably succeed before any pin syscall.
        on_stage(Stage.PIN)
        owner.pin(directory_fd,token,expected)
        on_stage(Stage.INITIAL_DENY)
        if not _denied(null_exchange()):raise ValueError('initial deny not observed')
        owner.close()
        on_stage(Stage.RECOVER)
        owner.recover(directory_fd,token,expected)
        if owner.link_identity()!=expected or not _denied(null_exchange()):
            raise ValueError('pin recovery enforcement mismatch')
        on_stage(Stage.CONTROL)
        if not _received(zero_exchange(),zero_device):raise ValueError('other device not allowed')
        on_stage(Stage.EXTRA_HOLDER)
        extra=link_factory()
        extra.recover(directory_fd,token,expected)
        if extra.link_identity()!=expected or owner.link_identity()!=expected:
            raise ValueError('extra holder identity mismatch')
        on_stage(Stage.UNLINK)
        unlink_exact(token,expected)
        owner.close()
        on_stage(Stage.EXTRA_DENY)
        if extra.probe_program_present(expected.program_id) is not True or not _denied(null_exchange()):
            raise ValueError('extra holder failed to retain enforcement')
        extra.close()
        on_stage(Stage.RELEASE)
        started=clock()
        if type(started) not in (int,float) or not math.isfinite(started) or started<0:
            raise ValueError('invalid release observation clock')
        deadline=started+2
        previous=started
        while True:
            now=clock()
            if type(now) not in (int,float) or not math.isfinite(now) or now<previous:
                raise ValueError('release observation clock changed')
            previous=now
            present=owner.probe_program_present(expected.program_id)
            if present is False:break
            if present is not True or now>=deadline:
                raise ValueError('program release unresolved')
            wait(0.02)
        on_stage(Stage.RESTORED)
        if not _received(null_exchange(),null_device):raise ValueError('null receipt not restored')
        return dict(pin_recovery_denied=True,extra_reference_retained_deny=True,
                    program_absence_observed=True,null_receipt_restored=True)
    finally:
        try:
            if extra is not None:extra.close()
        finally:owner.close()


class ReceiptJournal:
    """One exclusive root-private receipt, retained for crash diagnosis."""
    def __init__(self, token, cgroup_name, cgroup_identity):
        if (type(token) is not str or re.fullmatch(r'[0-9a-f]{64}',token) is None
                or type(cgroup_name) is not str
                or re.fullmatch(r'regear-receive-pin-fixture-[0-9a-f]{32}',cgroup_name) is None):
            raise ValueError('invalid disposable receipt identity')
        self.token,self.cgroup_name,self.cgroup_identity=token,cgroup_name,cgroup_identity
        self.path='/var/lib/regear-receive-pin-fixture/'+token+'.json'

    def __call__(self, expected):
        if type(expected) is not ReceiveIdentity:raise ValueError('typed receive identity required')
        flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC
        parent=_receipt_parent()
        directory=None
        try:
            status=os.fstat(parent)
            if status.st_uid!=0 or status.st_mode&0o022:raise ValueError('unsafe receipt parent')
            try:os.mkdir('regear-receive-pin-fixture',0o700,dir_fd=parent)
            except FileExistsError:pass
            directory=os.open('regear-receive-pin-fixture',flags,dir_fd=parent)
            status=os.fstat(directory)
            if status.st_uid!=0 or status.st_mode&0o077:raise ValueError('unsafe receipt directory')
            with open('/proc/sys/kernel/random/boot_id','r',encoding='ascii') as source:
                boot=source.read(65).strip()
            if re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}',boot) is None:
                raise ValueError('receipt boot identity unavailable')
            payload=json.dumps(dict(schema_version=1,pin_token=self.token,
                boot_sha256=hashlib.sha256(boot.encode()).hexdigest(),
                receive_identity=asdict(expected),cgroup_name=self.cgroup_name,
                cgroup_dev=self.cgroup_identity.st_dev,cgroup_inode=self.cgroup_identity.st_ino),sort_keys=True).encode()
            fd=os.open(self.token+'.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,
                       0o600,dir_fd=directory)
            try:
                offset=0
                while offset<len(payload):
                    written=os.write(fd,payload[offset:])
                    if written<=0:raise OSError('short receipt write')
                    offset+=written
                os.fsync(fd)
            finally:os.close(fd)
            os.fsync(directory)
            os.fsync(parent)
        finally:
            if directory is not None:os.close(directory)
            os.close(parent)


def _receipt_parent():
    """Authenticate every fixed ancestor while holding directory descriptors."""
    flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC
    descriptor=os.open('/',flags)
    try:
        for name in (None,'var','lib'):
            if name is not None:
                child=os.open(name,flags,dir_fd=descriptor)
                previous,descriptor=descriptor,child
                os.close(previous)
            observed=os.fstat(descriptor)
            if (not stat.S_ISDIR(observed.st_mode) or observed.st_uid!=0
                    or observed.st_mode&0o022):
                raise ValueError('unsafe receipt ancestor')
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def release_proven(owner,expected):
    """A surviving pin/reference or an observation error retains the cgroup."""
    if owner is None:return expected is None
    try:
        owner.close()
        return type(expected) is ReceiveIdentity and owner.probe_program_present(expected.program_id) is False
    except Exception:
        return False


def _run_fixture(report,retention=None):
    def stage(value):report['stage']=value.value
    stage(Stage.PLATFORM)
    if getattr(os,'geteuid',lambda:-1)()!=0 or platform.system()!='Linux' or platform.machine()!='x86_64':
        raise ValueError('root Linux x86_64 fixture required')
    stage(Stage.BTF_READ)
    with open('/sys/kernel/btf/vmlinux','rb') as source:raw=source.read(64*1024*1024+1)
    stage(Stage.BTF_PARSE)
    layout=parse_file_receive_btf(raw,pointer_size=8)
    stage(Stage.CGROUP_ROOT)
    root=os.open('/sys/fs/cgroup',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    name='regear-receive-pin-fixture-'+uuid.uuid4().hex
    token=uuid.uuid4().hex+uuid.uuid4().hex
    directory=child=first=second=owner=pins=null=zero=identity=None
    created=False
    expected=None
    retention_released=False
    report['btf_sha256']=hashlib.sha256(raw).hexdigest()
    try:
        status=os.fstat(root)
        if status.st_uid!=0 or status.st_mode&0o022:raise ValueError('unsafe cgroup root')
        controller=os.open('cgroup.controllers',os.O_RDONLY|os.O_NOFOLLOW,dir_fd=root)
        os.close(controller)
        stage(Stage.CGROUP_CREATE)
        os.mkdir(name,0o700,dir_fd=root);created=True
        directory=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=root)
        identity=os.fstat(directory)
        if identity.st_uid!=0 or not identity.st_ino or identity.st_dev!=status.st_dev:
            raise ValueError('invalid fixture cgroup')
        stage(Stage.RECEIVER)
        first,second=socket.socketpair(socket.AF_UNIX,socket.SOCK_SEQPACKET)
        first.settimeout(4)
        parent=os.getpid()
        child=os.fork()
        if child==0:
            first.close()
            receiver(second,directory,parent)
        second.close();second=None
        if first.recv(32)!=b'ready':raise ValueError('receiver unavailable')
        members=os.open('cgroup.procs',os.O_RDONLY|os.O_NOFOLLOW,dir_fd=directory)
        try:occupants=os.read(members,128).decode().split()
        finally:os.close(members)
        if occupants!=[str(child)]:raise ValueError('fixture cgroup not exclusive')
        stage(Stage.DEVICES)
        null=os.open('/dev/null',os.O_RDONLY|os.O_NOFOLLOW)
        zero=os.open('/dev/zero',os.O_RDONLY|os.O_NOFOLLOW)
        ns,zs=os.fstat(null),os.fstat(zero)
        if not stat.S_ISCHR(ns.st_mode) or not stat.S_ISCHR(zs.st_mode) or ns.st_rdev==zs.st_rdev:
            raise ValueError('fixture device identities invalid')
        stage(Stage.BASELINE)
        if not _received(exchange(first,null),ns.st_rdev):raise ValueError('baseline unavailable')
        stage(Stage.PIN_DIRECTORY)
        pins=FilterPinDirectory(create=True)
        if retention is not None:
            stage(Stage.RETENTION_PREPARE)
            retention.prepare(directory,name,identity)
            report['retention_prepared']=True
        stage(Stage.OWNER)
        owner=DiagnosticReceiveLink(report)
        stage(Stage.COMPILE)
        program=compile_device_receive((identity.st_ino,),((os.major(ns.st_rdev),os.minor(ns.st_rdev)),),
            file_inode_offset=layout.file_inode_offset,inode_mode_offset=layout.inode_mode_offset,
            inode_rdev_offset=layout.inode_rdev_offset)
        stage(Stage.LOAD_ATTACH)
        owner.load_attach(program,hook_btf_id=layout.hook_btf_id)
        stage(Stage.LINK_IDENTITY)
        expected=owner.link_identity()
        journal=ReceiptJournal(token,name,identity)
        def prepare(value):
            report['journal_retained']=True
            journal(value)
        def unlink_exact(pin,expected_identity):
            if pin!=token or owner.link_identity()!=expected_identity:
                raise ValueError('pin owner changed before unlink')
            check=FileReceiveLink()
            try:
                check.recover(pins.fd,pin,expected_identity)
                os.unlink(pin,dir_fd=pins.fd)
            finally:check.close()
        result=exercise_pin_lifetime(owner,directory_fd=pins.fd,token=token,expected=expected,
            journal=prepare,null_exchange=lambda:exchange(first,null),zero_exchange=lambda:exchange(first,zero),
            zero_device=zs.st_rdev,null_device=ns.st_rdev,unlink_exact=unlink_exact,on_stage=stage)
        if retention is not None:
            stage(Stage.RETENTION_RELEASE)
            if retention.release(owner,expected) is not True:
                raise ValueError('retention release unresolved')
            retention_released=True
            report['retention_released']=True
        report.update(result,state='fixture_passed')
    except Exception as error:
        report.update(state='fixture_failed',**_error_fields(error))
        if 'kernel_operation' in report:
            report['failure_kernel_operation']=report['kernel_operation']
        raise
    finally:
        # Closing every local reference is necessary but never sufficient proof
        # to remove a cgroup whose ID a pinned/global LSM program may retain.
        failed=report['state']=='fixture_failed'
        if not failed:stage(Stage.CLEANUP)
        removable=release_proven(owner,expected)
        if retention is not None and not retention_released:removable=False
        try:
            if pins is not None:pins.close()
        finally:
            if retention is not None:
                try:retention.close()
                except Exception as error:
                    removable=False
                    report['retention_cleanup_error']=_error_fields(error)
                    if report['state']!='fixture_failed':
                        report.update(state='fixture_failed',stage=Stage.CLEANUP.value,**_error_fields(error))
            report['cgroup_retained']=created and not removable
            try:
                cleanup_fixture(None,(null,zero),first,second,child,directory,root,name,identity,
                                created and removable)
            except Exception as cleanup_error:
                report['cgroup_retained']=created
                report['cleanup_error']=_error_fields(cleanup_error)
                raise
    return report


def run_fixture(*,retention=None):
    report=dict(state='unverified',stage=Stage.PLATFORM.value,disconnect_clearance=False,
                player_mutation=False,journal_retained=False,cgroup_retained=False)
    try:
        if retention is None:_run_fixture(report)
        else:_run_fixture(report,retention)
    except Exception as error:
        if report['state']!='fixture_failed':
            report.update(state='fixture_failed',**_error_fields(error))
    return report


def main():
    if sys.argv[1:]!=['--disposable-fixture']:
        raise SystemExit('Explicit --disposable-fixture required')
    report=run_fixture()
    print(json.dumps(report,sort_keys=True))
    return 0 if report['state']=='fixture_passed' else 1


if __name__=='__main__':raise SystemExit(main())
