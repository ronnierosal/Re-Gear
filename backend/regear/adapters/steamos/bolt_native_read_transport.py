"""Normalize fixed busctl replies for the inert reader. No subprocess here.

Logical GetAll reads only Uid/Status/Stored separately; never reads Key. busctl
JSON message/variant envelope follows the existing InputPlumber adapter contract.
Raw output is bounded by the runner before allocation; normalized replies are
independently bounded by the reader. No native error text leaves this adapter.
"""
import json
import math

from .commands import BoltNativeReadCommandRunner as Runner, CommandResult
from .usb4_native_evidence import NativeRead


def _unique(items):
    result = {}
    for key, value in items:
        if key in result: raise ValueError('duplicate native field')
        result[key] = value
    return result


class BoltNativeReadTransport:
    def __init__(self, runner, *, clock):
        self._runner, self._clock = runner, clock

    def __call__(self, request, budget):
        if type(request) is not NativeRead or request.auto_start is not False or request.interactive is not False:
            raise ValueError('native read invalid')
        def call(interface, member, signature='', args=()):
            now = self._clock()
            if type(now) not in (int, float) or not math.isfinite(now):
                raise ValueError('native clock invalid')
            if now >= budget.deadline: raise TimeoutError
            tail = ('call',request.destination,request.path,interface,member)
            argv = Runner.validate(Runner.PREFIX+tail+((signature,)+args if signature else ()))
            result = self._runner.run(argv)
            if type(result) is not CommandResult or result.argv != argv:
                raise ValueError('native response invalid')
            if not result.ok:
                if result.error.endswith('.timeout'): raise TimeoutError
                # Failure is NOT evidence of denied grant permission or absence.
                raise OSError('native read unavailable')
            if type(result.stdout) is not str or len(result.stdout.encode('utf-8')) > budget.max_bytes:
                raise ValueError('native output bounds')
            # Bound nesting before decoding untrusted JSON.
            depth=0; quoted=False; escaped=False
            for char in result.stdout:
                if quoted:
                    if escaped: escaped=False
                    elif char=='\\': escaped=True
                    elif char=='"': quoted=False
                elif char=='"': quoted=True
                elif char in '[{':
                    depth+=1
                    if depth>8: raise ValueError('native output depth')
                elif char in ']}': depth-=1
            value=json.loads(result.stdout,object_pairs_hook=_unique,
                parse_constant=lambda _: (_ for _ in ()).throw(ValueError('native value invalid')))
            if type(value) is not dict or set(value)!={'type','data'} or type(value['data']) is not list or len(value['data'])!=1:
                raise ValueError('native envelope invalid')
            return value['type'],value['data'][0]

        q=request
        if q.member=='GetNameOwner' and q.arguments==('org.freedesktop.bolt',):
            signature,value=call(q.interface,q.member,'s',q.arguments)
            if signature!='s' or type(value) is not str: raise ValueError('native owner invalid')
        elif q.member in ('Introspect','ListDevices') and not q.arguments:
            signature,value=call(q.interface,q.member)
            expected='s' if q.member=='Introspect' else 'ao'
            if signature!=expected or (expected=='s' and type(value) is not str) or (expected=='ao' and (type(value) is not list or any(type(p) is not str for p in value))):
                raise ValueError('native response invalid')
        elif q.interface=='org.freedesktop.DBus.Properties' and q.member=='GetAll' and q.arguments==('org.freedesktop.bolt1.Device',):
            value={}
            for name,expected in (('Uid','s'),('Status','s'),('Stored','b')):
                signature,item=call(q.interface,'Get','ss',(q.arguments[0],name))
                if signature!='v' or type(item) is not dict or set(item)!={'type','data'} or item['type']!=expected or type(item['data']) is not (bool if expected=='b' else str):
                    raise ValueError('native property invalid')
                value[name]=item['data']
        else:
            raise ValueError('native operation invalid')
        raw=json.dumps(value,separators=(',',':')).encode('utf-8')
        if len(raw)>budget.max_bytes: raise ValueError('native output bounds')
        return raw
