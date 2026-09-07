"""Explicit empty-cgroup map-retention fixture, without any filter program."""
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import stat
import sys
import uuid

if Path(__file__).name != '__main__.py':
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))

from scripts.probe_receive_pin_fixture import _receipt_parent, _error_fields
from hdm.delivery.cgroup_retention_map import CgroupRetentionMap, MapIdentity
from hdm.delivery.device_filter_pin_directory import FilterPinDirectory


def exercise_retention(owner, *, cgroup_fd, pin_directory_fd, token, journal,
                       close_cgroup, remove_exact_cgroup, unlink_exact_pin,
                       on_stage=lambda value:None):
    """Deletion of slot zero proves only that an entry survived pin recovery."""
    try:
        on_stage('map_create')
        expected=owner.create(cgroup_fd)
        if type(expected) is not MapIdentity or owner.identity()!=expected:
            raise ValueError('created map identity mismatch')
        on_stage('journal')
        journal(expected)
        on_stage('pin')
        owner.pin(pin_directory_fd,token,expected)
        on_stage('close_holders')
        owner.close()
        close_cgroup()
        on_stage('remove_cgroup')
        remove_exact_cgroup()
        on_stage('recover')
        owner.recover(pin_directory_fd,token,expected)
        if owner.identity()!=expected:raise ValueError('recovered map identity mismatch')
        on_stage('release_entry')
        if owner.release_entry(expected) is not True:
            raise ValueError('retained slot was not present')
        if owner.release_entry(expected) is not False:
            raise ValueError('slot removal did not become absent')
        on_stage('unpin')
        if owner.identity()!=expected:raise ValueError('map identity changed before unpin')
        unlink_exact_pin(token,expected)
        on_stage('complete')
        return dict(entry_survived_cgroup_directory_removal=True,entry_release_observed=True,
                    second_release_absent=True,id_nonreuse_certified=False)
    finally:
        owner.close()


def write_receipt(expected,token,name,identity):
    if (type(expected) is not MapIdentity or type(token) is not str
            or re.fullmatch(r'[0-9a-f]{64}',token) is None or type(name) is not str
            or re.fullmatch(r'regear-cgroup-retention-fixture-[0-9a-f]{32}',name) is None):
        raise ValueError('receipt identity invalid')
    flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC
    parent=_receipt_parent()
    directory=None
    try:
        try:os.mkdir('regear-cgroup-retention-fixture',0o700,dir_fd=parent)
        except FileExistsError:pass
        directory=os.open('regear-cgroup-retention-fixture',flags,dir_fd=parent)
        observed=os.fstat(directory)
        if not stat.S_ISDIR(observed.st_mode) or observed.st_uid!=0 or observed.st_mode&0o077:
            raise ValueError('unsafe receipt directory')
        with open('/proc/sys/kernel/random/boot_id','r',encoding='ascii') as source:boot=source.read(65).strip()
        if re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}',boot) is None:
            raise ValueError('boot identity unavailable')
        payload=json.dumps(dict(schema_version=1,pin_token=token,map_identity=asdict(expected),
            boot_sha256=hashlib.sha256(boot.encode()).hexdigest(),cgroup_name=name,
            cgroup_dev=identity.st_dev,cgroup_inode=identity.st_ino),sort_keys=True).encode()
        descriptor=os.open(token+'.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,
                           0o600,dir_fd=directory)
        try:
            offset=0
            while offset<len(payload):
                written=os.write(descriptor,payload[offset:])
                if written<=0:raise OSError('short receipt write')
                offset+=written
            os.fsync(descriptor)
        finally:os.close(descriptor)
        os.fsync(directory)
        os.fsync(parent)
    finally:
        if directory is not None:os.close(directory)
        os.close(parent)


def _run(report):
    def stage(value):report['stage']=value
    stage('platform')
    if getattr(os,'geteuid',lambda:-1)()!=0 or platform.system()!='Linux' or platform.machine()!='x86_64':
        raise ValueError('root Linux x86_64 required')
    root=child=pins=owner=None
    created=removed=False
    name='regear-cgroup-retention-fixture-'+uuid.uuid4().hex
    token=uuid.uuid4().hex+uuid.uuid4().hex
    try:
        stage('cgroup_root')
        flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC
        root=os.open('/sys/fs/cgroup',flags)
        root_identity=os.fstat(root)
        if root_identity.st_uid!=0 or root_identity.st_mode&0o022:
            raise ValueError('unsafe cgroup root')
        controller=os.open('cgroup.controllers',os.O_RDONLY|os.O_NOFOLLOW,dir_fd=root)
        os.close(controller)
        stage('cgroup_create')
        os.mkdir(name,0o700,dir_fd=root);created=True
        child=os.open(name,flags,dir_fd=root)
        identity=os.fstat(child)
        if identity.st_uid!=0 or identity.st_dev!=root_identity.st_dev or not identity.st_ino:
            raise ValueError('unsafe fixture cgroup')
        members=os.open('cgroup.procs',os.O_RDONLY|os.O_NOFOLLOW,dir_fd=child)
        try:
            if os.read(members,128).strip():raise ValueError('fixture cgroup not empty')
        finally:os.close(members)
        stage('pin_directory')
        pins=FilterPinDirectory(create=True)
        owner=CgroupRetentionMap()
        def journal(expected):
            report['receipt_attempted']=True
            write_receipt(expected,token,name,identity)
            report['receipt_retained']=True
        def close_child():
            nonlocal child
            descriptor,child=child,None
            os.close(descriptor)
        def remove_child():
            nonlocal removed
            if child is not None:raise ValueError('child directory still held')
            current=os.stat(name,dir_fd=root,follow_symlinks=False)
            if (not stat.S_ISDIR(current.st_mode) or current.st_uid!=0
                    or (current.st_dev,current.st_ino)!=(identity.st_dev,identity.st_ino)):
                raise ValueError('fixture cgroup replaced')
            os.rmdir(name,dir_fd=root)
            removed=True
        def unpin(pin,expected):
            if pin!=token or owner.identity()!=expected:raise ValueError('wrong pin identity')
            check=CgroupRetentionMap()
            try:
                check.recover(pins.fd,pin,expected)
                os.unlink(pin,dir_fd=pins.fd)
                report['pin_removed']=True
            finally:check.close()
        result=exercise_retention(owner,cgroup_fd=child,pin_directory_fd=pins.fd,token=token,
            journal=journal,close_cgroup=close_child,remove_exact_cgroup=remove_child,
            unlink_exact_pin=unpin,on_stage=stage)
        report.update(result,state='fixture_passed')
    except Exception as error:
        report.update(state='fixture_failed',**_error_fields(error))
        raise
    finally:
        report['cgroup_retained']=created and not removed
        errors=[]
        for close in ((owner.close if owner is not None else None),
                      (pins.close if pins is not None else None),
                      (lambda:os.close(child)) if child is not None else None,
                      (lambda:os.close(root)) if root is not None else None):
            if close is not None:
                try:close()
                except Exception as error:errors.append(_error_fields(error))
        if errors:
            report['cleanup_errors']=errors
            if report['state']!='fixture_failed':report.update(state='fixture_failed',stage='cleanup')


def run_fixture():
    report=dict(state='unverified',stage='platform',disconnect_clearance=False,player_mutation=False,
                filters_loaded=False,id_nonreuse_certified=False,receipt_attempted=False,
                receipt_retained=False,cgroup_retained=False,pin_removed=False)
    try:_run(report)
    except Exception as error:
        if report['state']!='fixture_failed':report.update(state='fixture_failed',**_error_fields(error))
    return report


def main():
    if sys.argv[1:]!=['--disposable-fixture']:raise SystemExit('Explicit --disposable-fixture required')
    report=run_fixture()
    print(json.dumps(report,sort_keys=True))
    return 0 if report['state']=='fixture_passed' else 1


if __name__=='__main__':raise SystemExit(main())
