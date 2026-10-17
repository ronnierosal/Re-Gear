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
_STANDARD_DOCTYPE = re.compile(
    r'\A[ \t\r\n]*<!DOCTYPE[ \t\r\n]+node[ \t\r\n]+PUBLIC[ \t\r\n]+'
    r'"-//freedesktop//DTD D-BUS Object Introspection 1\.0//EN"[ \t\r\n]+'
    r'"http://www\.freedesktop\.org/standards/dbus/1\.0/introspect\.dtd"[ \t\r\n]*>')

_XML_SPACE = re.compile(r'[ \t\r\n]+')
_XML_NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_.-]*')
_XML_REFERENCE = re.compile(r'&(amp|lt|gt|quot|apos|#[0-9]{1,7}|#x[0-9A-Fa-f]{1,6});')


def _xml_character(value):
    return value in (9, 10, 13) or 0x20 <= value <= 0xD7FF or 0xE000 <= value <= 0xFFFD or 0x10000 <= value <= 0x10FFFF


def _attribute(value):
    """Decode only XML's five predefined entities and valid character refs.

    No entity table, recursion, external resource or second expansion pass.
    XML1.0 attribute whitespace/reference rules: https://www.w3.org/TR/xml/
    """
    value = re.sub(r'\r\n?|\n|\t', ' ', value)
    output = []; position = 0
    while position < len(value):
        end = value.find('&', position)
        if end < 0:
            output.append(value[position:]); break
        output.append(value[position:end])
        match = _XML_REFERENCE.match(value, end)
        if match is None:
            raise NotImplementedError
        ref = match[1]
        if ref.startswith('#'):
            number = int(ref[2:], 16) if ref.startswith('#x') else int(ref[1:])
            if not _xml_character(number): raise NotImplementedError
            output.append(chr(number))
        else:
            output.append(dict(amp='&', lt='<', gt='>', quot='"', apos="'")[ref])
        position = match.end()
    return ''.join(output)


def _introspection_tree(xml):
    """Strict bounded D-Bus element-only subset, independent of optional XML.

    Not a general XML parser: reject namespaces, PI, CDATA and all declarations
    except the exact inert standard DOCTYPE. Well-formed comments are inert.
    Input is capped before tree/attribute allocation; stack parsing is iterative.
    """
    if type(xml) is not str or len(xml) > 65536:
        raise NotImplementedError
    if any(not _xml_character(ord(c)) for c in xml):
        raise NotImplementedError
    if len(xml.encode('utf-8')) > 65536:
        raise NotImplementedError
    xml = _STANDARD_DOCTYPE.sub('', xml, count=1)
    position = 0; root = None; stack = []; count = 0; comments = 0
    while position < len(xml):
        space = _XML_SPACE.match(xml, position)
        if space:
            position = space.end()
            if position == len(xml): break
        if xml.startswith('<!--', position):
            comments += 1
            if comments > 1024: raise NotImplementedError
            end = xml.find('-->', position+4)
            if end < 0: raise NotImplementedError
            body = xml[position+4:end]
            if '--' in body or body.endswith('-'): raise NotImplementedError
            position = end+3
            continue
        # Other declarations/PI still cannot match the element-name grammar.
        if xml[position:position+1] != '<': raise NotImplementedError
        position += 1
        closing = xml[position:position+1] == '/'
        if closing: position += 1
        name = _XML_NAME.match(xml, position)
        if name is None: raise NotImplementedError
        tag = name[0]; position = name.end()
        if closing:
            space = _XML_SPACE.match(xml, position)
            if space: position = space.end()
            if xml[position:position+1] != '>' or not stack or stack[-1][0] != tag:
                raise NotImplementedError
            stack.pop(); position += 1; continue
        count += 1
        if count > 1024 or len(stack) >= 16: raise NotImplementedError
        attributes = {}; children = []; node = (tag, attributes, children)
        while True:
            space = _XML_SPACE.match(xml, position)
            if space: position = space.end()
            if xml.startswith('/>', position):
                position += 2; empty = True; break
            if xml[position:position+1] == '>':
                position += 1; empty = False; break
            if not space or len(attributes) >= 32: raise NotImplementedError
            attribute = _XML_NAME.match(xml, position)
            if attribute is None or attribute[0] == 'xmlns' or attribute[0] in attributes:
                raise NotImplementedError
            key = attribute[0]; position = attribute.end()
            space = _XML_SPACE.match(xml, position)
            if space: position = space.end()
            if xml[position:position+1] != '=': raise NotImplementedError
            position += 1
            space = _XML_SPACE.match(xml, position)
            if space: position = space.end()
            quote = xml[position:position+1]
            if quote not in ('"', "'"): raise NotImplementedError
            position += 1; end = xml.find(quote, position)
            if end < 0 or '<' in xml[position:end]: raise NotImplementedError
            attributes[key] = _attribute(xml[position:end]); position = end+1
        if stack: stack[-1][2].append(node)
        elif root is None: root = node
        else: raise NotImplementedError
        if not empty: stack.append(node)
    if stack or root is None: raise NotImplementedError
    return root


def _children(node, tag, name=None):
    return [child for child in node[2] if child[0] == tag and (name is None or child[1].get('name') == name)]


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
        root = _introspection_tree(xml)
        matches = _children(root, 'interface', name)
        if root[0] != 'node' or len(matches) != 1:
            raise NotImplementedError
        interface = matches[0]
        method = 'Authorize' if device else 'ListDevices'
        expected = [('s', 'in')] if device else [('ao', 'out')]
        methods = _children(interface, 'method', method)
        if len(methods) != 1 or [(a[1].get('type'), a[1].get('direction', 'in'))
                for a in _children(methods[0], 'arg')] != expected:
            raise NotImplementedError
        if device:
            for name, signature in [('Uid', 's'), ('Status', 's'), ('Stored', 'b')]:
                properties = _children(interface, 'property', name)
                if len(properties) != 1 or properties[0][1].get('type') != signature or properties[0][1].get('access') not in ('read', 'readwrite'):
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
        if 1 < len(devices) <= 3:
            # ListDevices includes stored objects, not just physical attachments.
            # Inspect every status, never a first-object shortcut. With three
            # candidates the transport uses at most eight calls including both
            # owner reads. No Uid/Stored/Key is fetched in this branch.
            candidates=[]; unresolved=False
            for path in devices:
                status=read(path,'org.freedesktop.DBus.Properties','Get',(_DEVICE,'Status'))
                if type(status) is not str or status not in ('disconnected','connected','auth-error','authorized'):
                    unresolved=True
                elif status!='disconnected':
                    candidates.append(path)
            if not unresolved and len(candidates)==1:
                introspect(candidates[0],_DEVICE,device=True)
                api=Fact.OBSERVED
                # This is only a candidate's interface, even if it is a host
                # object. No topology, lifetime or external-device binding was
                # established; attachment/enrollment stay UNKNOWN.
                state=Fact.UNKNOWN
        if len(devices)==1:
            introspect(devices[0],_DEVICE,device=True)
            properties = read(devices[0],'org.freedesktop.DBus.Properties','GetAll',(_DEVICE,))
            if type(properties) is not dict or type(properties.get('Uid')) is not str or not properties['Uid'] or len(properties['Uid'])>128 or type(properties.get('Status')) is not str or properties['Status'] not in ('unknown','disconnected','connecting','connected','authorizing','auth-error','authorized') or type(properties.get('Stored')) is not bool:
                raise ValueError('native properties invalid')
            api = enrollment = Fact.OBSERVED
        return NativeSnapshot(captured_at=self._guard(budget),api=api,
            enrollment_store=enrollment,attachment_state=state,
            bytes_read=used_bytes,objects_read=used_objects)
