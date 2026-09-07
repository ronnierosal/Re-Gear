"""Disposable receive-pin fixture with a separately pinned cgroup reference."""
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import uuid

if Path(__file__).name != '__main__.py':
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))

from scripts.probe_receive_pin_fixture import run_fixture as receive_fixture, _receipt_parent
from hdm.delivery.cgroup_retention_map import CgroupRetentionMap, MapIdentity
from hdm.delivery.device_receive_kernel import ReceiveIdentity
from hdm.delivery.device_filter_pin_directory import FilterPinDirectory


def write_combined_receipt(expected,token,name,identity):
    if (type(expected) is not MapIdentity or type(token) is not str
            or re.fullmatch(r'[0-9a-f]{64}',token) is None or type(name) is not str
            or re.fullmatch(r'regear-receive-pin-fixture-[0-9a-f]{32}',name) is None):
        raise ValueError('combined receipt identity invalid')
    parent=_receipt_parent()
    directory=None
    flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC
    try:
        try:os.mkdir('regear-retained-receive-fixture',0o700,dir_fd=parent)
        except FileExistsError:pass
        directory=os.open('regear-retained-receive-fixture',flags,dir_fd=parent)
        observed=os.fstat(directory)
        if not stat.S_ISDIR(observed.st_mode) or observed.st_uid!=0 or observed.st_mode&0o077:
            raise ValueError('unsafe combined receipt directory')
        with open('/proc/sys/kernel/random/boot_id','r',encoding='ascii') as source:boot=source.read(65).strip()
        if re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}',boot) is None:
            raise ValueError('boot identity unavailable')
        data=json.dumps(dict(schema_version=1,pin_token=token,map_identity=asdict(expected),
            boot_sha256=hashlib.sha256(boot.encode()).hexdigest(),cgroup_name=name,
            cgroup_dev=identity.st_dev,cgroup_inode=identity.st_ino),sort_keys=True).encode()
        descriptor=os.open(token+'.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,
                           0o600,dir_fd=directory)
        try:
            offset=0
            while offset<len(data):
                count=os.write(descriptor,data[offset:])
                if count<=0:raise OSError('short receipt write')
                offset+=count
            os.fsync(descriptor)
        finally:os.close(descriptor)
        os.fsync(directory)
        os.fsync(parent)
    finally:
        if directory is not None:os.close(directory)
        os.close(parent)


class RetainedReceiveCoordinator:
    """Drop the retained cgroup reference only after receive-program absence."""
    def __init__(self,*,map_factory=CgroupRetentionMap,pins_factory=FilterPinDirectory,
                 journal=write_combined_receipt,unlink=None):
        self.map_factory,self.pins_factory,self.journal=map_factory,pins_factory,journal
        self.unlink=unlink
        self.owner=self.pins=self.expected=None
        self.token=uuid.uuid4().hex+uuid.uuid4().hex
        self.phase='new'
        self.receipt_attempted=False
        self.pin_may_remain=False

    def prepare(self,cgroup_fd,name,identity):
        if self.phase!='new':raise ValueError('retention preparation cannot replay')
        self.phase='preparing'
        self.pins=self.pins_factory(create=True)
        self.owner=self.map_factory()
        self.expected=self.owner.create(cgroup_fd)
        if type(self.expected) is not MapIdentity or self.owner.identity()!=self.expected:
            raise ValueError('retention map identity mismatch')
        self.receipt_attempted=True
        self.journal(self.expected,self.token,name,identity)
        self.pin_may_remain=True
        self.owner.pin(self.pins.fd,self.token,self.expected)
        self.owner.close()
        self.owner.recover(self.pins.fd,self.token,self.expected)
        if self.owner.identity()!=self.expected:raise ValueError('retention recovery mismatch')
        self.phase='prepared'

    def release(self,receive_owner,receive_identity):
        if (self.phase!='prepared' or type(receive_identity) is not ReceiveIdentity
                or receive_owner.probe_program_present(receive_identity.program_id) is not False):
            raise ValueError('receive program absence not proven')
        if type(self.expected) is not MapIdentity or self.owner.identity()!=self.expected:
            raise ValueError('retention map changed before release')
        self.phase='releasing'
        if self.owner.release_entry(self.expected) is not True:
            raise ValueError('retention entry missing')
        if self.owner.release_entry(self.expected) is not False:
            raise ValueError('retention entry remains')
        if self.owner.identity()!=self.expected:raise ValueError('retention pin changed')
        if self.unlink is not None:
            self.unlink(self.pins.fd,self.token,self.expected)
        else:
            check=self.map_factory()
            try:
                check.recover(self.pins.fd,self.token,self.expected)
                os.unlink(self.token,dir_fd=self.pins.fd)
            finally:check.close()
        self.pin_may_remain=False
        self.owner.close()
        self.phase='released'
        return True

    def close(self):
        try:
            if self.owner is not None:self.owner.close()
        finally:
            if self.pins is not None:self.pins.close()


def run_fixture():
    coordinator=RetainedReceiveCoordinator()
    report=receive_fixture(retention=coordinator)
    report.update(retention_phase=coordinator.phase,
                  retention_receipt_attempted=coordinator.receipt_attempted,
                  retention_pin_may_remain=coordinator.pin_may_remain,
                  id_nonreuse_certified=False)
    return report


def main():
    if sys.argv[1:]!=['--disposable-fixture']:raise SystemExit('Explicit --disposable-fixture required')
    report=run_fixture()
    print(json.dumps(report,sort_keys=True))
    return 0 if report['state']=='fixture_passed' else 1


if __name__=='__main__':raise SystemExit(main())
