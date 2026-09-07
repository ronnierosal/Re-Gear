"""Fixture-only immutable ownership receipts; parsing never grants authority.

Missing receive-stage evidence does not prove that no receive filter was loaded.
Caller authenticates fresh boot/cgroup binding and proves controller death before
recovery. Failed publication is uncertain: retain directory and inspect again.
The sole writer must be reaped before recovery reads. /run is volatile: fsync
provides process-crash ordering for this same-boot fixture, not reboot recovery.
No pin, unlink, cgroup, service or runtime operation is performed here.
"""
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import stat
import sys
import uuid

from hdm.delivery.cgroup_retention_map import MapIdentity
from hdm.delivery.device_receive_kernel import ReceiveIdentity
from hdm.delivery.device_filter_pin_directory import _root_directory

MAX_BYTES = 2048


@dataclass(frozen=True)
class ReceiptBinding:
    boot_hash: str
    cgroup_name: str
    cgroup_dev: int
    cgroup_inode: int

    def __post_init__(self):
        if (type(self.boot_hash) is not str or re.fullmatch(r'[0-9a-f]{64}',self.boot_hash) is None
                or type(self.cgroup_name) is not str
                or re.fullmatch(r'regear-paired-receive-fixture-[0-9a-f]{32}',self.cgroup_name) is None
                or type(self.cgroup_dev) is not int or not 0 <= self.cgroup_dev < 2**64
                or type(self.cgroup_inode) is not int or not 0 < self.cgroup_inode < 2**64):
            raise ValueError('invalid fixture binding')


@dataclass(frozen=True)
class PairedReceipt:
    binding: ReceiptBinding
    map_token: str
    map_identity: MapIdentity
    receive_token: str | None = None
    receive_identity: ReceiveIdentity | None = None


def _token(value):
    if type(value) is not str or re.fullmatch(r'[0-9a-f]{64}',value) is None:
        raise ValueError('invalid ownership token')
    return value


def _decode(raw):
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_BYTES:
        raise ValueError('receipt bound exceeded')
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('duplicate receipt key')
            result[key]=value
        return result
    value=json.loads(raw.decode('utf-8'),object_pairs_hook=pairs,
        parse_constant=lambda _:(_ for _ in ()).throw(ValueError('nonfinite receipt')))
    if type(value) is not dict:raise ValueError('receipt object required')
    return value


def _binding(value, expected):
    if type(expected) is not ReceiptBinding or type(value) is not dict or set(value)!=set(asdict(expected)):
        raise ValueError('receipt binding schema mismatch')
    if ReceiptBinding(**value)!=expected:raise ValueError('fresh fixture binding mismatch')


def decode_pair(map_raw, receive_raw, expected):
    value=_decode(map_raw)
    if (set(value)!={'schema','stage','binding','token','map_id'} or type(value['schema']) is not int
            or value['schema']!=1 or value['stage']!='map'):
        raise ValueError('map receipt schema mismatch')
    _binding(value['binding'],expected)
    token=_token(value['token']); identity=MapIdentity(value['map_id'])
    if receive_raw is None:return PairedReceipt(expected,token,identity)
    second=_decode(receive_raw)
    if (set(second)!={'schema','stage','binding','token','identity','map_token','map_id'}
            or type(second['schema']) is not int or second['schema']!=1 or second['stage']!='receive'):
        raise ValueError('receive receipt schema mismatch')
    _binding(second['binding'],expected)
    if (second['map_token']!=token or type(second['map_id']) is not int or second['map_id']!=identity.map_id
            or type(second['identity']) is not dict
            or set(second['identity'])!={'link_id','program_id','hook_btf_id','target_obj_id'}):
        raise ValueError('paired identity mismatch')
    received_token=_token(second['token'])
    if received_token==token:raise ValueError('receipt tokens must differ')
    return PairedReceipt(expected,token,identity,received_token,ReceiveIdentity(**second['identity']))


class PairedReceiptDirectory:
    def __init__(self, path, binding, *, trusted_directory_fd=None, owner_uid=None):
        if sys.platform!='linux':raise ValueError('Linux receipt owner required')
        if type(binding) is not ReceiptBinding:raise ValueError('typed binding required')
        if (trusted_directory_fd is None)!=(owner_uid is None):raise ValueError('paired fixture authority required')
        self.path=str(path);self.binding=binding;self.fd=None
        self.owner_uid=0 if owner_uid is None else owner_uid
        if type(self.owner_uid) is not int or self.owner_uid<0 or os.geteuid()!=self.owner_uid:
            raise ValueError('receipt owner mismatch')
        if trusted_directory_fd is not None:
            if type(trusted_directory_fd) is not int or trusted_directory_fd<0:raise ValueError('invalid fixture fd')
            self.fd=os.dup(trusted_directory_fd)
            try:self._directory(self.fd)
            except BaseException:self.close();raise
            return
        target=Path(path)
        if (not target.is_absolute() or target.parent!=Path('/run')
                or re.fullmatch(r'regear-paired-receipt-[0-9a-f]{32}',target.name) is None):
            raise ValueError('fixed receipt parent required')
        current=os.open('/',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:
            _root_directory(current)
            for part in target.parts[1:]:
                child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=current)
                os.close(current);current=child
                _root_directory(current)
            self._directory(current)
            self.fd=current;current=None
        finally:
            if current is not None:os.close(current)

    @classmethod
    def create(cls,binding):
        if sys.platform!='linux' or os.geteuid()!=0:raise ValueError('root Linux required')
        if type(binding) is not ReceiptBinding:raise ValueError('typed binding required')
        root=os.open('/',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        parent=None
        try:
            _root_directory(root)
            parent=os.open('run',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=root)
            _root_directory(parent)
            name='regear-paired-receipt-'+uuid.uuid4().hex
            os.mkdir(name,0o700,dir_fd=parent)
            os.fsync(parent)
            return cls('/run/'+name,binding)
        finally:
            if parent is not None:os.close(parent)
            os.close(root)

    @classmethod
    def open(cls,path,expected_binding):
        return cls(path,expected_binding)

    def _directory(self,fd):
        info=os.fstat(fd)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid!=self.owner_uid or info.st_mode&0o077:
            raise ValueError('unsafe receipt directory')

    def _read(self,name,optional=False):
        self._directory(self.fd)
        try:fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=self.fd)
        except FileNotFoundError:
            if optional:return None
            raise
        try:
            info=os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid!=self.owner_uid or info.st_mode&0o077
                    or info.st_nlink!=1 or not 0<info.st_size<=MAX_BYTES):
                raise ValueError('unsafe receipt file')
            raw=os.read(fd,MAX_BYTES+1)
            if len(raw)!=info.st_size:raise ValueError('receipt changed during read')
            after=os.fstat(fd)
            fields=('st_dev','st_ino','st_uid','st_mode','st_nlink','st_size','st_mtime_ns','st_ctime_ns')
            if any(getattr(info,field)!=getattr(after,field) for field in fields):
                raise ValueError('receipt metadata changed during read')
            return raw
        finally:os.close(fd)

    def read(self,expected_binding=None):
        expected=self.binding if expected_binding is None else expected_binding
        return decode_pair(self._read('map.json'),self._read('receive.json',True),expected)

    def _write(self,name,value):
        self._directory(self.fd)
        raw=json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
        if len(raw)>MAX_BYTES:raise ValueError('receipt too large')
        fd=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=self.fd)
        try:
            if os.write(fd,raw)!=len(raw):raise OSError('short immutable receipt write')
            os.fsync(fd)
        finally:os.close(fd)
        os.fsync(self.fd)

    def write_map(self,token,identity):
        if type(identity) is not MapIdentity:raise ValueError('typed map identity required')
        self._write('map.json',dict(schema=1,stage='map',binding=asdict(self.binding),token=_token(token),map_id=identity.map_id))

    def write_receive(self,token,identity):
        if type(identity) is not ReceiveIdentity:raise ValueError('typed receive identity required')
        first=self.read()
        if first.receive_identity is not None or _token(token)==first.map_token:
            raise ValueError('receive receipt already exists or token overlaps')
        self._write('receive.json',dict(schema=1,stage='receive',binding=asdict(self.binding),token=token,
            identity=asdict(identity),map_token=first.map_token,map_id=first.map_identity.map_id))

    def close(self):
        descriptor,self.fd=self.fd,None
        if descriptor is not None:os.close(descriptor)

    def __enter__(self):return self
    def __exit__(self,*_):self.close()
