"""Disposable paired-pin recovery after SIGKILL with live owner BPF FDs.

Only a new dummy cgroup and /dev/null,/dev/zero SCM_RIGHTS are exercised.
Ambiguous ownership retains pins, receipts and the cgroup. No player authority.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import signal
import socket
import stat
import sys
import time
import uuid

if Path(__file__).name != '__main__.py':
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))

from hdm.delivery.cgroup_retention_map import CgroupRetentionMap, MapIdentity
from hdm.delivery.device_receive_kernel import FileReceiveLink, ReceiveIdentity, ReceivePinAbsent
from hdm.delivery.device_receive_program import compile_device_receive
from hdm.delivery.device_filter_btf import parse_file_receive_btf
from hdm.delivery.device_filter_pin_directory import FilterPinDirectory
from scripts.probe_device_receive_fixture import receiver, exchange, cleanup_fixture
from scripts.probe_receive_pin_fixture import _received, _denied, _error_fields
from scripts.probe_killed_filter_controller import _child_setup, _send, _recv, _wait, terminate_owned

CONTROLLER_STAGES=frozenset(('setup','receipt_open','pin_directory','map_create','map_receipt',
    'map_pin','compile','receive_load','receive_identity','receive_receipt','receive_pin','live_fds','wait'))


def close_all(*owners):
    """Attempt every owned close; preserve the first operational exception."""
    pending=sys.exc_info()[0] is not None
    errors=[]
    for owner in owners:
        if owner is not None:
            try:owner.close()
            except Exception as error:errors.append(error)
    if errors and not pending:raise errors[0]


def controller_failure(packet):
    if type(packet) is not bytes or len(packet)>128 or not packet.startswith(b'failed:'):
        raise ValueError('unknown controller packet')
    def pairs(items):
        value={}
        for key,item in items:
            if key in value:raise ValueError('duplicate controller field')
            value[key]=item
        return value
    value=json.loads(packet[7:],object_pairs_hook=pairs)
    if (type(value) is not dict or set(value)!={'stage','error_type','errno'}
            or value['stage'] not in CONTROLLER_STAGES
            or value['error_type'] not in ('OSError','ValueError','RuntimeError','PermissionError',
                'FileNotFoundError','FileExistsError','TimeoutError','TypeError','AttributeError','Exception')
            or (value['errno'] is not None and (type(value['errno']) is not int or not 0<=value['errno']<=4095))):
        raise ValueError('invalid controller failure packet')
    return value


def boot_hash():
    with open('/proc/sys/kernel/random/boot_id','rb') as source:raw=source.read(65)
    if re.fullmatch(rb'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\n',raw) is None:
        raise ValueError('boot identity unavailable')
    return hashlib.sha256(raw).hexdigest()


def publish_pair(directory,layout,null_device,receipt,*,map_factory=CgroupRetentionMap,
                 link_factory=FileReceiveLink,pins_factory=FilterPinDirectory,
                 compiler=compile_device_receive,send_ready,wait_for_death,fstat=os.fstat,
                 stage=lambda value:None,before_receive_pin=False):
    """Controller only: durable identities precede pins; hold live FDs at ready."""
    if type(before_receive_pin) is not bool:raise ValueError("explicit checkpoint required")
    retained=link=pins=None
    try:
        stage('pin_directory');pins=pins_factory(create=True)
        stage('map_create')
        retained=map_factory()
        expected_map=retained.create(directory)
        if type(expected_map) is not MapIdentity or retained.identity()!=expected_map:
            raise ValueError('map identity mismatch')
        map_token=uuid.uuid4().hex+uuid.uuid4().hex
        stage('map_receipt');receipt.write_map(map_token,expected_map)
        stage('map_pin')
        retained.pin(pins.fd,map_token,expected_map)
        group=fstat(directory)
        stage('compile')
        program=compiler((group.st_ino,),((os.major(null_device),os.minor(null_device)),),
            file_inode_offset=layout.file_inode_offset,inode_mode_offset=layout.inode_mode_offset,
            inode_rdev_offset=layout.inode_rdev_offset)
        link=link_factory()
        stage('receive_load');link.load_attach(program,hook_btf_id=layout.hook_btf_id)
        stage('receive_identity')
        expected_receive=link.link_identity()
        if type(expected_receive) is not ReceiveIdentity:raise ValueError('receive identity unavailable')
        receive_token=uuid.uuid4().hex+uuid.uuid4().hex
        stage('receive_receipt');receipt.write_receive(receive_token,expected_receive)
        if not before_receive_pin:
            stage('receive_pin')
            link.pin(pins.fd,receive_token,expected_receive)
        stage('live_fds')
        for fd in (retained.map_fd,link.program_fd,link.link_fd):
            if type(fd) is not int or fd<0:raise ValueError('live owner descriptor absent')
            fstat(fd)
        if retained.identity()!=expected_map or link.link_identity()!=expected_receive:
            raise ValueError('live owner identity changed')
        send_ready(b'before-receive-pin' if before_receive_pin else b'paired-live')
        stage('wait');wait_for_death()
        raise ValueError('controller survived expected SIGKILL')
    finally:
        close_all(link,retained,pins)


def recover_pair(record,*,pin_fd,map_factory=CgroupRetentionMap,link_factory=FileReceiveLink,
                 null_exchange,zero_exchange,null_device,zero_device,unlink=os.unlink,
                 clock=time.monotonic,sleep=time.sleep,stage=lambda value:None,before_receive_pin=False):
    """Caller supplies a newly read receipt only after exact controller reap."""
    if type(before_receive_pin) is not bool:raise ValueError("explicit checkpoint required")
    if (type(record.map_identity) is not MapIdentity or type(record.receive_identity) is not ReceiveIdentity
            or type(record.map_token) is not str or type(record.receive_token) is not str
            or any(re.fullmatch(r'[0-9a-f]{64}',token) is None for token in (record.map_token,record.receive_token))
            or record.map_token==record.receive_token):
        raise ValueError('complete distinct paired ownership required')
    retained=link=None
    try:
        stage('recover_map')
        retained=map_factory();retained.recover(pin_fd,record.map_token,record.map_identity)
        if retained.identity()!=record.map_identity:raise ValueError('map recovery changed')
        stage('recover_receive')
        link=link_factory()
        missing_pin=False
        try:link.recover(pin_fd,record.receive_token,record.receive_identity)
        except ReceivePinAbsent:
            if not before_receive_pin:raise
            missing_pin=True
        if before_receive_pin and not missing_pin:
            raise ValueError('unexpected receive pin at before-pin checkpoint')
        if not missing_pin:
            if link.link_identity()!=record.receive_identity:raise ValueError('receive recovery changed')
            stage('post_death_denial')
            if not _denied(null_exchange()) or not _received(zero_exchange(),zero_device):
                raise ValueError('recovered receive policy not observed')
            stage('receive_unpin')
            check=link_factory()
            try:
                check.recover(pin_fd,record.receive_token,record.receive_identity)
                if check.link_identity()!=record.receive_identity:raise ValueError('receive pin changed')
                unlink(record.receive_token,dir_fd=pin_fd)
            finally:check.close()
        link.close()
        stage('receive_absence')
        previous=clock()
        if type(previous) not in (int,float) or not math.isfinite(previous):raise ValueError('invalid clock')
        deadline=previous+2
        for _ in range(102):
            current=clock()
            if type(current) not in (int,float) or not math.isfinite(current) or current<previous:
                raise ValueError('invalid clock')
            previous=current
            if current>=deadline:raise TimeoutError('receive program absence unresolved')
            present=link.probe_program_present(record.receive_identity.program_id)
            if present is False:break
            if present is not True:raise ValueError('receive presence unknown')
            sleep(.02)
        else:raise TimeoutError('receive program absence unresolved')
        if not _received(null_exchange(),null_device):raise ValueError('null receipt not restored')
        if missing_pin and not _received(zero_exchange(),zero_device):
            raise ValueError('zero control not restored')
        stage('retention_release')
        if retained.identity()!=record.map_identity:raise ValueError('retention identity changed')
        if retained.release_entry(record.map_identity) is not True:raise ValueError('retention entry absent')
        if retained.release_entry(record.map_identity) is not False:raise ValueError('retention entry remains')
        check_map=map_factory()
        try:
            check_map.recover(pin_fd,record.map_token,record.map_identity)
            if check_map.identity()!=record.map_identity:raise ValueError('map pin changed')
            unlink(record.map_token,dir_fd=pin_fd)
        finally:check_map.close()
        retained.close()
        return dict(post_death_denial_observed=not missing_pin,receive_pin_absent_observed=missing_pin,
                    pin_not_published_checkpoint=before_receive_pin,
                    receive_absence_observed=True,
                    null_receipt_restored=True,retention_entry_released=True)
    finally:
        close_all(link,retained)


def verify_owner_death(*,ready,deny,kill_controller,read_receipt,recover,before_receive_pin=False):
    if type(before_receive_pin) is not bool:raise ValueError('explicit checkpoint required')
    marker=b'before-receive-pin' if before_receive_pin else b'paired-live'
    if ready()!=marker:raise ValueError('paired live readiness missing')
    if deny() is not True:raise ValueError('initial denial missing')
    kill_controller()
    # Identities are first read from the durable directory after owner death.
    record=read_receipt()
    result=recover(record)
    return dict(result,controller_sigkill_verified=True,live_bpf_fd_crash_verified=True)


def run_fixture(*,before_receive_pin=False):
    if type(before_receive_pin) is not bool:raise ValueError("explicit checkpoint required")
    from scripts.paired_receive_receipt import PairedReceiptDirectory, ReceiptBinding
    report=dict(state='unverified',stage='platform',disconnect_clearance=False,player_mutation=False,
                cgroup_retained=False,receipt_retained=False,id_nonreuse_certified=False,
                before_receive_pin_checkpoint=before_receive_pin)
    root=directory=null=zero=None
    rs=rc=cs=cc=None
    child=controller=None
    identity=None
    created=recovered=False
    name='regear-paired-receive-fixture-'+uuid.uuid4().hex
    def stage(value):report['stage']=value
    try:
        if platform.system()!='Linux' or platform.machine()!='x86_64' or getattr(os,'geteuid',lambda:-1)()!=0:
            raise ValueError('root Linux x86_64 required')
        stage('btf')
        with open('/sys/kernel/btf/vmlinux','rb') as source:raw=source.read(64*1024*1024+1)
        layout=parse_file_receive_btf(raw,pointer_size=8)
        stage('cgroup')
        root=os.open('/sys/fs/cgroup',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        rootstat=os.fstat(root)
        if not stat.S_ISDIR(rootstat.st_mode) or rootstat.st_uid!=0 or rootstat.st_mode&0o022:
            raise ValueError('unsafe cgroup root')
        control=os.open('cgroup.controllers',os.O_RDONLY|os.O_NOFOLLOW,dir_fd=root);os.close(control)
        os.mkdir(name,0o700,dir_fd=root);created=True
        directory=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=root)
        identity=os.fstat(directory)
        if (not stat.S_ISDIR(identity.st_mode) or identity.st_uid!=0 or identity.st_mode&0o077
                or identity.st_dev!=rootstat.st_dev or not identity.st_ino):
            raise ValueError('unsafe fixture cgroup')
        def current_binding():
            current=os.stat(name,dir_fd=root,follow_symlinks=False)
            if (not stat.S_ISDIR(current.st_mode) or current.st_uid!=0 or current.st_mode&0o077
                    or (current.st_dev,current.st_ino)!=(identity.st_dev,identity.st_ino)):
                raise ValueError('cgroup identity changed')
            return ReceiptBinding(boot_hash(),name,current.st_dev,current.st_ino)
        binding=current_binding()
        stage('receipt_directory')
        with PairedReceiptDirectory.create(binding) as receipt:
            receipt_path=receipt.path
        report['receipt_retained']=True
        stage('receiver')
        rs,rc=socket.socketpair(socket.AF_UNIX,socket.SOCK_SEQPACKET)
        rs.settimeout(4)
        parent=os.getpid()
        child=os.fork()
        if child==0:
            try:
                _child_setup(parent,{rc.fileno(),directory})
                receiver(rc,directory,parent)
            except BaseException:os._exit(2)
        rc.close();rc=None
        if rs.recv(32)!=b'ready':raise ValueError('receiver unavailable')
        members=os.open('cgroup.procs',os.O_RDONLY|os.O_NOFOLLOW,dir_fd=directory)
        try:
            if os.read(members,128).decode().split()!=[str(child)]:raise ValueError('receiver membership changed')
        finally:os.close(members)
        stage('dummy_devices')
        null=os.open('/dev/null',os.O_RDONLY|os.O_NOFOLLOW)
        zero=os.open('/dev/zero',os.O_RDONLY|os.O_NOFOLLOW)
        ns,zs=os.fstat(null),os.fstat(zero)
        if (not stat.S_ISCHR(ns.st_mode) or not stat.S_ISCHR(zs.st_mode)
                or ns.st_rdev!=os.makedev(1,3) or zs.st_rdev!=os.makedev(1,5)):
            raise ValueError('dummy devices changed')
        if not _received(exchange(rs,null),ns.st_rdev):raise ValueError('baseline unavailable')
        stage('controller')
        cs,cc=socket.socketpair(socket.AF_UNIX,socket.SOCK_SEQPACKET)
        # No BPF owner has been constructed in supervisor before this fork.
        controller=os.fork()
        if controller==0:
            child_stage='setup'
            def set_child_stage(value):
                nonlocal child_stage
                child_stage=value
            try:
                _child_setup(parent,{cc.fileno(),directory})
                set_child_stage('receipt_open')
                with PairedReceiptDirectory.open(receipt_path,binding) as receipt:
                    def wait_for_death():
                        cc.settimeout(30);cc.recv(1)
                    publish_pair(directory,layout,ns.st_rdev,receipt,
                                 send_ready=lambda packet:_send(cc,packet),wait_for_death=wait_for_death,
                                 stage=set_child_stage,before_receive_pin=before_receive_pin)
                os._exit(4)
            except BaseException as error:
                try:
                    packet=b'failed:'+json.dumps(dict(stage=child_stage,**_error_fields(error)),separators=(',',':')).encode('ascii')
                    controller_failure(packet)
                    _send(cc,packet)
                except BaseException:pass
                os._exit(2)
        cc.close();cc=None
        def kill_controller():
            nonlocal controller
            stage('kill_controller')
            pid=controller
            os.kill(pid,signal.SIGKILL)
            status=_wait(pid)
            controller=None
            if not os.WIFSIGNALED(status) or os.WTERMSIG(status)!=signal.SIGKILL:
                raise ValueError('controller SIGKILL unconfirmed')
        def read_receipt():
            stage('read_after_death')
            fresh=current_binding()
            if fresh!=binding:raise ValueError('receipt context changed')
            with PairedReceiptDirectory.open(receipt_path,fresh) as receipt:return receipt.read(fresh)
        def recover(record):
            nonlocal recovered
            with FilterPinDirectory() as pins:
                result=recover_pair(record,pin_fd=pins.fd,null_exchange=lambda:exchange(rs,null),
                    zero_exchange=lambda:exchange(rs,zero),null_device=ns.st_rdev,zero_device=zs.st_rdev,stage=stage,before_receive_pin=before_receive_pin)
            recovered=True
            return result
        def ready():
            packet=_recv(cs)
            if packet!=(b'before-receive-pin' if before_receive_pin else b'paired-live'):
                report['controller_failure']=controller_failure(packet)
                raise ValueError('controller preparation failed')
            return packet
        report.update(verify_owner_death(ready=ready,deny=lambda:_denied(exchange(rs,null)),
            kill_controller=kill_controller,read_receipt=read_receipt,recover=recover,before_receive_pin=before_receive_pin),state='fixture_passed')
    except Exception as error:
        report.update(state='fixture_failed',**_error_fields(error))
    finally:
        errors=[]
        if controller is not None and controller>0:
            try:terminate_owned(controller)
            except Exception as error:errors.append(_error_fields(error))
        for sock in (cs,cc):
            if sock is not None:
                try:sock.close()
                except Exception as error:errors.append(_error_fields(error))
        removable=created and recovered and not errors
        report['cgroup_retained']=created and not removable
        if root is not None:
            try:cleanup_fixture(None,(null,zero),rs,rc,child,directory,root,name,identity,removable)
            except Exception as error:
                report['cgroup_retained']=created
                errors.append(_error_fields(error))
        if errors:
            report['cleanup_errors']=errors
            if report['state']!='fixture_failed':report.update(state='fixture_failed',stage='cleanup')
    return report


def main():
    if sys.argv[1:] not in (['--disposable-fixture'],['--disposable-fixture','--before-receive-pin']):
        raise SystemExit('Explicit --disposable-fixture and optional --before-receive-pin required')
    report=run_fixture(before_receive_pin='--before-receive-pin' in sys.argv[1:])
    print(json.dumps(report,sort_keys=True))
    return 0 if report['state']=='fixture_passed' else 1


if __name__=='__main__':raise SystemExit(main())
