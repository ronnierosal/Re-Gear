"""Inert, injected inventory capture. No factory, RPC, path resolution or grant.

Only a privately advertised lexical sysfs path is retained, never trusted router
identity or lifetime binding. A separate reviewed execution route is required.
The installed evidence reader and its interface introspection remain unchanged.
"""
from collections import Counter
from dataclasses import dataclass, field
import json
import math
import re
import time

from .commands import BoltInventoryCaptureCommandRunner as Runner, CommandResult


@dataclass(frozen=True)
class CaptureReport:
    code: str
    object_count: int | None = None
    type_counts: tuple = ()
    status_counts: tuple = ()
    sysfs_path: str | None = field(default=None, repr=False)
    calls: int = 0
    bytes_read: int = 0


class _Stop(Exception):
    pass


def _unique(items):
    result={}
    for key,value in items:
        if key in result:raise ValueError('duplicate field')
        result[key]=value
    return result


def capture_inventory(runner, *, clock=time.monotonic):
    """One complete two-object frame; injected runners must enforce OS cleanup.

    Native runner additionally bounds total stdout+stderr and subprocess time.
    These independent checks also bound fake/replayed input. Errors withdraw all
    captured fields. Unknown observations never become an external attachment.
    """
    calls=used=0
    try:
        start=clock();last=start
        if type(start) not in (int,float) or not math.isfinite(start):raise ValueError
        def guard():
            nonlocal last
            now=clock()
            if type(now) not in (int,float) or not math.isfinite(now) or now<last:raise ValueError
            last=now
            if now-start>=3:raise _Stop('timeout')
        def read(destination,path,interface,member,signature='',args=()):
            nonlocal calls,used
            guard()
            if calls>=8:raise _Stop('bounds')
            argv=Runner.validate(Runner.PREFIX+('call',destination,path,interface,member)+((signature,)+args if signature else ()))
            calls+=1;result=runner.run(argv);guard()
            if type(result) is not CommandResult or result.argv!=argv:raise ValueError
            if not result.ok:raise _Stop('unavailable')
            if type(result.stdout) is not str or type(result.stderr) is not str:raise ValueError
            used+=len(result.stdout.encode('utf-8'))+len(result.stderr.encode('utf-8'))
            if used>65536:raise _Stop('bounds')
            depth=0;quoted=escaped=False
            for char in result.stdout:
                if quoted:
                    if escaped:escaped=False
                    elif char=='\\':escaped=True
                    elif char=='"':quoted=False
                elif char=='"':quoted=True
                elif char in '[{':
                    depth+=1
                    if depth>8:raise ValueError
                elif char in ']}':depth-=1
            value=json.loads(result.stdout,object_pairs_hook=_unique,
                parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            if type(value) is not dict or set(value)!={'type','data'} or type(value['data']) is not list or len(value['data'])!=1:raise ValueError
            return value['type'],value['data'][0]
        def owner():
            sig,value=read('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','GetNameOwner','s',('org.freedesktop.bolt',))
            if sig!='s' or type(value) is not str or len(value)>128 or not Runner.OWNER.fullmatch(value):raise ValueError
            return value
        before=owner()
        sig,paths=read(before,Runner.ROOT,'org.freedesktop.bolt1.Manager','ListDevices')
        if (sig!='ao' or type(paths) is not list or len(paths)>64
                or any(type(p) is not str or len(p)>1024 or not Runner.DEVICE_PATH.fullmatch(p) for p in paths)
                or len(set(paths))!=len(paths)):raise ValueError
        types=[];statuses=[];advertised=None;code='inventory_unresolved'
        def prop(path,name):
            sig,value=read(before,path,'org.freedesktop.DBus.Properties','Get','ss',('org.freedesktop.bolt1.Device',name))
            if sig!='v' or type(value) is not dict or set(value)!={'type','data'} or value['type']!='s' or type(value['data']) is not str:raise ValueError
            return value['data']
        if len(paths)==2:
            types=[prop(p,'Type') for p in paths]
            statuses=[prop(p,'Status') for p in paths]
            code='classification_unresolved'
            known={'connected','auth-error','authorized','disconnected','unknown','connecting','authorizing'}
            if any(t not in ('host','peripheral') for t in types) or any(s not in known for s in statuses):
                types=[];statuses=[]
            elif types.count('host')==1 and types.count('peripheral')==1:
                index=types.index('peripheral');code='status_unresolved'
                if all(s in ('connected','auth-error','authorized') for s in statuses):
                    advertised=prop(paths[index],'SysfsPath')
                    parts=advertised.split('/')
                    if (len(advertised)>1024 or not advertised.startswith('/sys/devices/')
                            or any(not p or p in ('.','..') or not re.fullmatch(r'[A-Za-z0-9_:+.\-]+',p) for p in parts[1:])):raise ValueError
                    code='observed'
        if owner()!=before:raise _Stop('owner_changed')
        guard()
        return CaptureReport('capture.'+code,len(paths),tuple(sorted(Counter(types).items())),
                             tuple(sorted(Counter(statuses).items())),advertised,calls,used)
    except _Stop as error:
        return CaptureReport('capture.'+str(error),calls=calls,bytes_read=used)
    except (ValueError,TypeError,OverflowError,RecursionError,StopIteration):
        return CaptureReport('capture.malformed',calls=calls,bytes_read=used)
    except (OSError,TimeoutError):
        return CaptureReport('capture.unavailable',calls=calls,bytes_read=used)
