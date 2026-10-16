"""Inert Bolt evidence reader over injected, nonactivating native reads.

No transport or production consumer is installed here. The transport must honor
the deadline and cap bytes *before* allocation, target the supplied unique bus
owner, prohibit activation/interactive authorization, and return bounded UTF-8
JSON values (not CLI text). Errors must raise; only a confirmed missing owner
returns JSON null. This adapter cannot interrupt a blocking injected transport.

Interface contract reference (inspection only, no copied implementation): Bolt,
Christian Kellner/contributors, data/org.freedesktop.bolt.xml at upstream commit
976c04f3bad1824e2a967964e42e03ea70cf7658:
https://github.com/gicmo/bolt/blob/976c04f3bad1824e2a967964e42e03ea70cf7658/data/org.freedesktop.bolt.xml
Installed introspection must match; upstream is never installed-host proof.
"""
from dataclasses import dataclass, field
import json
import math
import re
from typing import Callable
from xml.etree import ElementTree

from ...ports.usb4_native_evidence import Fact, NativeSnapshot, ReadBudget


@dataclass(frozen=True)
class NativeRead:
    destination: str
    path: str
    interface: str
    member: str
    arguments: tuple[str, ...] = ()
    auto_start: bool = field(default=False, init=False)
    interactive: bool = field(default=False, init=False)


_ROOT = '/org/freedesktop/bolt'
_MANAGER = 'org.freedesktop.bolt1.Manager'
_DEVICE = 'org.freedesktop.bolt1.Device'
_OWNER = re.compile(r':[0-9]+\.[0-9]+')
_PATH = re.compile(r'/(?:[A-Za-z0-9_]+/)*[A-Za-z0-9_]+')


class BoltNativeEvidenceReader:
    """Qualify read shapes only; no permission or attachment capability is minted.

GetAll values are normalized D-Bus property values with their native types.
Stored is per-device enrollment evidence, not proof of grant permission. Bolt's
Generation property is hardware generation, NOT an attachment lifetime counter.
Without qualified private lifetime binding, attachment freshness stays unknown;
neither Status nor active service ownership authorizes a device.
"""
    def __init__(self, read: Callable[[NativeRead, ReadBudget], bytes], *, clock):
        self._read = read
        self._clock = clock
        self._last = None

    def _guard(self, budget):
        now = self._clock()
        if type(now) not in (int, float) or not math.isfinite(now) or (
                self._last is not None and now < self._last):
            raise ValueError('invalid clock')
        self._last = now
        if now >= budget.deadline:
            raise TimeoutError
        return now

    def _value(self, request, budget):
        self._guard(budget)
        raw = self._read(request, budget)
        self._guard(budget)
        if type(raw) is not bytes or len(raw) > budget.max_bytes:
            raise ValueError('native read bounds')
        def pairs(items):
            result = {}
            for key, value in items:
                if key in result: raise ValueError('duplicate field')
                result[key] = value
            return result
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs)
        def count(v):
            if type(v) is dict: return 1 + sum(1 + count(x) for x in v.values())
            if type(v) is list: return 1 + sum(count(x) for x in v)
            return 1
        objects = count(value)
        if objects > budget.max_objects:
            raise ValueError('native read bounds')
        return value, len(raw), objects

    def service_owner(self, budget):
        value, size, _ = self._value(NativeRead('org.freedesktop.DBus',
            '/org/freedesktop/DBus', 'org.freedesktop.DBus', 'GetNameOwner',
            ('org.freedesktop.bolt',)), budget)
        if value is not None and (type(value) is not str or not _OWNER.fullmatch(value)):
            raise ValueError('native owner invalid')
        # The collector charges two owner lengths; reserve the four JSON quote
        # bytes in observe. Reject padding rather than silently undercounting it.
        if size != len(json.dumps(value, separators=(',', ':')).encode('utf-8')):
            raise ValueError('native owner accounting invalid')
        return value

    @staticmethod
    def _interface(xml, name, *, device=False):
        if type(xml) is not str or '<!' in xml:
            raise NotImplementedError
        try: root = ElementTree.fromstring(xml)
        except ElementTree.ParseError: raise NotImplementedError from None
        matches = root.findall(f"./interface[@name='{name}']")
        if root.tag != 'node' or len(matches) != 1:
            raise NotImplementedError
        interface = matches[0]
        method = 'Authorize' if device else 'ListDevices'
        expected = [('s', 'in')] if device else [('ao', 'out')]
        methods = interface.findall(f"./method[@name='{method}']")
        if len(methods) != 1 or [(a.get('type'), a.get('direction', 'in'))
                for a in methods[0].findall('arg')] != expected:
            raise NotImplementedError
        if device:
            for name, signature in [('Uid', 's'), ('Status', 's'), ('Stored', 'b')]:
                properties = interface.findall(f"./property[@name='{name}']")
                if len(properties) != 1 or properties[0].get('type') != signature or properties[0].get('access') not in ('read', 'readwrite'):
                    raise NotImplementedError

    def observe(self, owner, budget):
        if type(owner) is not str or not _OWNER.fullmatch(owner):
            raise ValueError('native owner invalid')
        used_bytes, used_objects = 4, 0
        def read(path, interface, member, arguments=()):
            nonlocal used_bytes, used_objects
            remaining = ReadBudget(budget.deadline, budget.max_bytes-used_bytes, budget.max_objects-used_objects)
            if remaining.max_bytes <= 0 or remaining.max_objects <= 0:
                raise ValueError('native read bounds')
            value, size, objects = self._value(NativeRead(owner,path,interface,member,arguments),remaining)
            used_bytes += size; used_objects += objects
            return value
        def introspect(path, interface, device=False):
            self._interface(read(path, 'org.freedesktop.DBus.Introspectable', 'Introspect'), interface, device=device)
        introspect(_ROOT,_MANAGER)
        devices = read(_ROOT,_MANAGER,'ListDevices')
        if type(devices) is not list or any(type(p) is not str or len(p)>1024 or not _PATH.fullmatch(p) for p in devices) or len(set(devices))!=len(devices):
            raise ValueError('native device inventory invalid')
        api = enrollment = Fact.UNKNOWN
        state = Fact.AMBIGUOUS if len(devices)>1 else Fact.UNKNOWN
        if len(devices)==1:
            introspect(devices[0],_DEVICE,device=True)
            properties = read(devices[0],'org.freedesktop.DBus.Properties','GetAll',(_DEVICE,))
            if type(properties) is not dict or type(properties.get('Uid')) is not str or not properties['Uid'] or len(properties['Uid'])>128 or type(properties.get('Status')) is not str or properties['Status'] not in ('unknown','disconnected','connecting','connected','authorizing','auth-error','authorized') or type(properties.get('Stored')) is not bool:
                raise ValueError('native properties invalid')
            api = enrollment = Fact.OBSERVED
        return NativeSnapshot(captured_at=self._guard(budget),api=api,
            enrollment_store=enrollment,attachment_state=state,
            bytes_read=used_bytes,objects_read=used_objects)
