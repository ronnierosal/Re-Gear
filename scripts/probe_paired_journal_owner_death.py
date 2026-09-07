"""Disposable SIGKILL with live BPF ownership and actual journal recovery.

The supervisor creates no BPF owner before forking the controller. Readiness
contains no kernel identity; fresh durable recovery begins only after reap.
No player service or hardware device is operated on.
"""
import hashlib
import json
import os
import signal
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
from hdm.delivery.device_filter_recovery import FilterRecovery
from hdm.delivery.device_filter_lifecycle import LaunchBinding,Phase,PairedStage
from hdm.delivery.device_filter_pin_directory import _root_directory
from hdm.delivery.cgroup_retention_map import CgroupRetentionMap,MapIdentity
from hdm.delivery.device_receive_kernel import FileReceiveLink,ReceiveIdentity,ReceivePinAbsent
from hdm.delivery.device_receive_recovery import ReceiveRecovery
from hdm.delivery.device_filter_btf import parse_file_receive_btf
from scripts.probe_paired_journal_fixture import create_journal_directory,publish_journal_pair,recover_journal_pair
from scripts.probe_paired_owner_death import boot_hash
from scripts.probe_killed_filter_controller import _child_setup,_send,_recv,_wait,terminate_owned
from scripts.probe_device_receive_fixture import receiver,exchange,cleanup_fixture
from scripts.probe_receive_pin_fixture import _received,_denied,_error_fields

READY=b'paired-journal-live'
BEFORE_READY=b'journal-before-receive-pin'
STAGES=frozenset(('setup','map_create','retention_intent','map_pin','receive_load','receive_intent',
                  'receive_pin','initial_denial','live_fds','wait'))


def failure_packet(stage,error):
    if stage not in STAGES:raise ValueError('invalid controller stage')
    packet=b'failed:'+json.dumps(dict(stage=stage,**_error_fields(error)),separators=(',',':')).encode('ascii')
    parse_failure(packet)
    return packet


def parse_failure(packet):
    if type(packet) is not bytes or len(packet)>128 or not packet.startswith(b'failed:'):
        raise ValueError('invalid failure packet')
    def pairs(items):
        value={}
        for key,item in items:
            if key in value:raise ValueError('duplicate field')
            value[key]=item
        return value
    value=json.loads(packet[7:],object_pairs_hook=pairs)
    if (type(value) is not dict or set(value)!={'stage','error_type','errno'} or value['stage'] not in STAGES
            or value['error_type'] not in ('OSError','ValueError','RuntimeError','PermissionError','FileNotFoundError',
                'FileExistsError','TimeoutError','TypeError','AttributeError','Exception')
            or (value['errno'] is not None and (type(value['errno']) is not int or not 0<=value['errno']<=4095))):
        raise ValueError('invalid failure fields')
    return value


def publish_live(journal,binding,directory,layout,null_device,*,send_ready,wait_for_death,
                 map_factory=CgroupRetentionMap,receive_factory=FileReceiveLink,
                 publisher=publish_journal_pair,fstat=os.fstat,stage=lambda value:None,before_receive_pin=False):
    """Hold publisher's live owner scope at callback, outside the journal lock."""
    if type(before_receive_pin) is not bool:raise ValueError("explicit checkpoint required")
    owners={}
    def create_map():
        owners['map']=map_factory();return owners['map']
    def create_receive():
        owners['receive']=receive_factory();return owners['receive']
    def checkpoint():
        stage('live_fds')
        retained,receive=owners['map'],owners['receive']
        with journal.transaction() as tx:record=tx.read(binding.operation,binding.unit)
        if (record.lifecycle.binding!=binding or record.lifecycle.phase is not Phase.REQUESTED
                or record.paired is None or record.paired.stage is not (PairedStage.RECEIVE_INTENT if before_receive_pin else PairedStage.RECEIVE_CONFIRMED)
                or record.delivery_granted):raise ValueError('durable live pair absent')
        saved=record.paired.receive
        if (retained.identity()!=MapIdentity(record.paired.map_id) or receive.link_identity()!=ReceiveIdentity(
                saved.link_id,saved.program_id,saved.hook_btf_id,saved.target_obj_id)):
            raise ValueError('live ownership differs from journal')
        for fd in (retained.map_fd,receive.program_fd,receive.link_fd):
            if type(fd) is not int or fd<0:raise ValueError('live descriptor absent')
            fstat(fd)
        send_ready(BEFORE_READY if before_receive_pin else READY)
        stage('wait');wait_for_death()
        raise ValueError('controller survived expected SIGKILL')
    publisher(journal,binding,directory,layout,null_device,map_factory=create_map,
        receive_factory=create_receive,observe_denial=checkpoint,stage=stage,
        before_receive_pin_checkpoint=checkpoint if before_receive_pin else None)


def verify_death(*,ready,deny,kill_controller,recover,before_receive_pin=False):
    if type(before_receive_pin) is not bool:raise ValueError("explicit checkpoint required")
    if ready()!=(BEFORE_READY if before_receive_pin else READY):raise ValueError('live owner readiness absent')
    if deny() is not True:raise ValueError('live owner denial absent')
    kill_controller()
    result=recover()
    return dict(result,controller_sigkill_verified=True,live_bpf_fd_crash_verified=True)


class BeforePinReceive(FileReceiveLink):
    """Fixture checkpoint rejects a published pin rather than cleaning it up."""
    def recover(self,*args):
        try:super().recover(*args)
        except ReceivePinAbsent:raise
        self.close()
        raise ValueError('receive pin unexpectedly published at checkpoint')


def recover_before_pin(journal_factory,binding,*,current_boot_hash,observe_restored,
                       prior_owner_quiesced=False,recovery_factory=None):
    if prior_owner_quiesced is not True:raise ValueError('confirmed owner death required')
    journal=journal_factory()
    with journal.transaction() as tx:before=tx.read(binding.operation,binding.unit)
    if (before.lifecycle.binding!=binding or before.lifecycle.phase is not Phase.REQUESTED
            or before.paired is None or before.paired.stage is not PairedStage.RECEIVE_INTENT
            or before.delivery_granted):raise ValueError('durable receive intent absent')
    if observe_restored() is not True:raise ValueError('post-death controls not restored')
    recovery=(recovery_factory(journal) if recovery_factory is not None else
              FilterRecovery(journal,receive_recovery=ReceiveRecovery(receive_factory=BeforePinReceive)))
    result=recovery.recover(binding.operation,binding.unit,current_boot_hash=current_boot_hash,
                            prior_owner_quiesced=True)
    with journal.transaction() as tx:after=tx.read(binding.operation,binding.unit)
    if (result.outcome!='cancelled_without_owned_identity' or result.launch_authorized or result.disconnect_clearance
            or after.lifecycle.binding!=binding or after.lifecycle.phase is not Phase.CANCELLED
            or after.paired is None or after.paired.stage is not PairedStage.COMPLETE
            or after.paired.receive!=before.paired.receive or after.paired.map_id!=before.paired.map_id
            or after.delivery_granted or after.revision<=before.revision):
        raise ValueError('before-pin recovery not durably complete')
    if observe_restored() is not True:raise ValueError('restored controls changed')
    return dict(durable_cancellation_observed=True,paired_complete_observed=True,
        before_receive_pin_checkpoint=True,post_death_denial_observed=False,
        null_zero_restored=True,launch_authorized=False,disconnect_clearance=False)


def run_fixture(*,before_receive_pin=False):
    if type(before_receive_pin) is not bool:raise ValueError("explicit checkpoint required")
    report=dict(state='unverified',stage='platform',journal_retained=False,cgroup_retained=False,
                launch_authorized=False,disconnect_clearance=False,player_mutation=False,synthetic_binding=True)
    root=directory=journal_fd=null=zero=None
    first=second=cs=cc=None
    controller=None
    child=identity=None
    created=complete=False
    name='regear-journal-death-fixture-'+uuid.uuid4().hex
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
                _child_setup(parent,{second.fileno(),directory});receiver(second,directory,parent)
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
            return _denied(exchange(first,null)) and _received(exchange(first,zero),zs.st_rdev)
        def restored():
            validate_group()
            return _received(exchange(first,null),ns.st_rdev) and _received(exchange(first,zero),zs.st_rdev)
        if not restored():raise ValueError('baseline unavailable')
        stage('controller')
        cs,cc=socket.socketpair(socket.AF_UNIX,socket.SOCK_SEQPACKET)
        controller=os.fork()
        if controller==0:
            child_stage='setup'
            def child_progress(value):
                nonlocal child_stage
                child_stage=value
            try:
                _child_setup(parent,{cc.fileno(),directory,journal_fd})
                def wait_for_death():
                    cc.settimeout(30);cc.recv(1)
                publish_live(journal_factory(),binding,directory,layout,ns.st_rdev,
                    send_ready=lambda packet:_send(cc,packet),wait_for_death=wait_for_death,stage=child_progress,
                    before_receive_pin=before_receive_pin)
                os._exit(4)
            except BaseException as error:
                try:_send(cc,failure_packet(child_stage,error))
                except BaseException:pass
                os._exit(2)
        cc.close();cc=None
        def ready():
            packet=_recv(cs)
            if packet!=(BEFORE_READY if before_receive_pin else READY):
                report['controller_failure']=parse_failure(packet)
                raise ValueError('controller publication failed')
            return packet
        def kill_controller():
            nonlocal controller
            stage('kill_controller')
            pid=controller
            os.kill(pid,signal.SIGKILL)
            status=_wait(pid)
            controller=None
            if not os.WIFSIGNALED(status) or os.WTERMSIG(status)!=signal.SIGKILL:
                raise ValueError('controller death unconfirmed')
        def recover():
            stage('journal_recovery')
            validate_group()
            if before_receive_pin:
                if controller is not None:raise ValueError('owner death not confirmed')
                return recover_before_pin(journal_factory,binding,current_boot_hash=boot_hash(),
                    observe_restored=restored,prior_owner_quiesced=True)
            return recover_journal_pair(journal_factory,binding,current_boot_hash=boot_hash(),
                observe_denial=denial,observe_restored=restored)
        report.update(verify_death(ready=ready,deny=denial,kill_controller=kill_controller,recover=recover,before_receive_pin=before_receive_pin))
        complete=True;report['state']='fixture_passed'
    except Exception as error:report.update(state='fixture_failed',**_error_fields(error))
    finally:
        cleanup_errors=[]
        if controller is not None and controller>0:
            try:terminate_owned(controller)
            except Exception as error:cleanup_errors.append(_error_fields(error))
        for sock in (cs,cc):
            if sock is not None:
                try:sock.close()
                except Exception as error:cleanup_errors.append(_error_fields(error))
        if cleanup_errors:
            complete=False
            report.update(state='fixture_failed',controller_cleanup_errors=cleanup_errors)
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
    if sys.argv[1:] not in (['--disposable-fixture'],['--disposable-fixture','--before-receive-pin']):
        raise SystemExit('Explicit --disposable-fixture and optional --before-receive-pin required')
    report=run_fixture(before_receive_pin='--before-receive-pin' in sys.argv[1:]);print(json.dumps(report,sort_keys=True))
    return 0 if report['state']=='fixture_passed' else 1


if __name__=='__main__':raise SystemExit(main())
