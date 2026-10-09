"""One injected, bounded InputPlumber read frame; no production binding or writes.

Uses the existing explicit-call allowlist. Subprocess deadlines and cleanup belong
to the injected runner; lifecycle owns admission, cancellation and projection.
Protocol facts and attribution: docs/CONTROLLER_PROVIDER_CATALOG.md.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from xml.etree import ElementTree

from .commands import CommandResult, InputPlumberReadCommandRunner as Transport
from .controller_catalog import INTERFACE, PATH
from ...domain.controller_catalog import EvidenceState
from ...ports.controller_catalog import PropertyRead, ProviderReadFrame


@dataclass(frozen=True, slots=True)
class ReaderLimits:
    max_objects: int = 128
    max_calls: int = 512
    max_bytes: int = 1048576
    max_depth: int = 8
    max_nodes: int = 32768
    max_items: int = 256
    max_string: int = 1024

    def __post_init__(self):
        for field, ceiling in zip(self.__dataclass_fields__, (128, 512, 1048576, 8, 32768, 256, 1024)):
            value = getattr(self, field)
            if type(value) is not int or not 0 < value <= ceiling:
                raise ValueError('reader limits require bounded positive integers')


class _Invalid(Exception):
    pass


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise _Invalid()
        result[key] = value
    return result


# Expected types, independent of untrusted live introspection declarations.
SIGNATURES = {
    'Version': 's', 'GamepadOrder': 'as', 'Name': 's', 'PersistentId': 's',
    'ProfileName': 's', 'ProfilePath': 's', 'SourceDevicePaths': 'as',
    'TargetDevices': 'as', 'DbusDevices': 'as', 'Capabilities': 'as',
    'TargetCapabilities': 'as', 'OutputCapabilities': 'as', 'SupportedKeys': 'aq',
    'IdBustype': 's', 'Properties': 'a{ss}',
}
RELATIONS = frozenset({'GamepadOrder', 'SourceDevicePaths', 'TargetDevices', 'DbusDevices'})


class _Read:
    """Budgets reset for every explicit request, including injected fake runners."""
    def __init__(self, runner, limits):
        self.runner, self.limits = runner, limits
        self.calls, self.bytes, self.nodes = limits.max_calls, limits.max_bytes, limits.max_nodes

    def call(self, tail):
        argv = Transport.validate(Transport.PREFIX + tail)
        self.calls -= 1
        if self.calls < 0:
            raise _Invalid()
        result = self.runner.run(argv)
        if type(result) is not CommandResult or result.argv != argv:
            raise _Invalid()
        if type(result.stdout) is not str or type(result.stderr) is not str:
            raise _Invalid()
        self.bytes -= len(result.stdout.encode('utf-8')) + len(result.stderr.encode('utf-8'))
        if self.bytes < 0:
            raise _Invalid()
        if not result.ok:
            return None
        # Depth is checked before JSON decoding, preventing decoder recursion.
        depth, quoted, escaped = 0, False, False
        for char in result.stdout:
            if quoted:
                if escaped: escaped = False
                elif char == '\\': escaped = True
                elif char == '"': quoted = False
            elif char == '"': quoted = True
            elif char in '[{':
                depth += 1
                if depth > self.limits.max_depth: raise _Invalid()
            elif char in ']}': depth -= 1
        value = json.loads(result.stdout, object_pairs_hook=_unique,
                           parse_constant=lambda _: (_ for _ in ()).throw(_Invalid()))
        self.bounded(value, 0, text_limit=False)
        return value

    def bounded(self, value, depth, *, text_limit=True):
        self.nodes -= 1
        if self.nodes < 0 or depth > self.limits.max_depth:
            raise _Invalid()
        if type(value) is str:
            value.encode('utf-8')
            if text_limit and len(value) > self.limits.max_string: raise _Invalid()
        elif type(value) in (dict, list):
            if len(value) > self.limits.max_items: raise _Invalid()
            for item in (list(value.keys()) + list(value.values()) if type(value) is dict else value):
                self.bounded(item, depth + 1, text_limit=text_limit)
        elif type(value) not in (int, bool) and value is not None:
            raise _Invalid()

    def scalar(self, tail):
        value = self.call(tail)
        if value is None: raise _Invalid()
        return self.decode(value, 's')

    def decode(self, envelope, signature):
        if type(envelope) is not dict or set(envelope) != {'type', 'data'} or envelope['type'] != signature:
            raise _Invalid()
        data = envelope['data']
        if type(data) is not list or len(data) != 1: raise _Invalid()
        value = data[0]
        if signature == 's':
            if type(value) is not str: raise _Invalid()
        elif signature in ('as', 'ao', 'aq'):
            if type(value) is not list: raise _Invalid()
            if signature == 'aq':
                if any(type(v) is not int or not 0 <= v <= 65535 for v in value): raise _Invalid()
            elif any(type(v) is not str for v in value): raise _Invalid()
            if signature == 'ao' and (len(set(value)) != len(value) or any(not Transport.PATH.fullmatch(v) for v in value)):
                raise _Invalid()
            value = tuple(value)
        elif signature == 'a{ss}':
            if type(value) is not dict or any(type(k) is not str or type(v) is not str for k,v in value.items()):
                raise _Invalid()
            value = dict(value)
        return value

    def property(self, tail, signature, prop):
        raw = self.call(tail)
        try:
            if raw is None: raise _Invalid()
            decoded = self.decode(self.decode(raw, 'v'), signature)
            self.bounded(list(decoded) if type(decoded) is tuple else decoded, 0)
            if prop in RELATIONS and (len(set(decoded)) != len(decoded) or any(not PATH.fullmatch(v) for v in decoded)):
                raise _Invalid()
            return PropertyRead(EvidenceState.KNOWN, decoded)
        except _Invalid:
            return PropertyRead()

    def topology(self, owner):
        pending, result = [Transport.ROOT], {}
        while pending:
            path = pending.pop(0)
            if path in result or len(result) >= self.limits.max_objects: raise _Invalid()
            xml = self.scalar(('call', owner, path, 'org.freedesktop.DBus.Introspectable', 'Introspect'))
            if '<!' in xml: raise _Invalid()
            root = ElementTree.fromstring(xml)
            if root.tag != 'node': raise _Invalid()
            stack = [(root, 0)]
            while stack:
                node, depth = stack.pop()
                self.nodes -= 1
                if self.nodes < 0 or depth > self.limits.max_depth or len(node.attrib) > 8 or len(node) > self.limits.max_items:
                    raise _Invalid()
                stack.extend((child, depth+1) for child in node)
            children, interfaces = [], {}
            for node in root:
                if node.tag == 'node':
                    name = node.get('name', '')
                    if not re.fullmatch(r'[A-Za-z0-9_]+', name) or len(name) > self.limits.max_string: raise _Invalid()
                    child = path + '/' + name
                    if child in children or not Transport.PATH.fullmatch(child) or len(child) > 512: raise _Invalid()
                    children.append(child)
                elif node.tag == 'interface':
                    name = node.get('name', '')
                    if not INTERFACE.fullmatch(name) or len(name) > self.limits.max_string or name in interfaces: raise _Invalid()
                    if len(interfaces) >= 16: raise _Invalid()
                    properties = {}
                    for prop in node:
                        if prop.tag != 'property': continue
                        key, signature, access = prop.get('name'), prop.get('type'), prop.get('access')
                        if key in properties or len(properties) >= 64: raise _Invalid()
                        if not key or not signature or access not in ('read', 'write', 'readwrite'): raise _Invalid()
                        properties[key] = (signature, access)
                    interfaces[name] = properties
            result[path] = (tuple(sorted(children)), interfaces)
            pending.extend(sorted(children))
            if len(result) + len(pending) > self.limits.max_objects: raise _Invalid()
        return result


class InputPlumberReader:
    """Implements ControllerProviderReader; requires an injected run(argv) runner.

    No cached frame, default runner, startup work, settings ownership decision or
    public projection. Provider ownership is only private coherence evidence.
    """
    def __init__(self, runner, *, limits=ReaderLimits()):
        if type(limits) is not ReaderLimits: raise ValueError('reader limits invalid')
        self._runner, self._limits = runner, limits

    def read_snapshot(self):
        failed = ProviderReadFrame('', {}, EvidenceState.UNKNOWN, False)
        try:
            read = _Read(self._runner, self._limits)
            dbus = ('call', 'org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus')
            def identity():
                bus = read.scalar(dbus + ('GetId',))
                owner = read.scalar(dbus + ('GetNameOwner', 's', Transport.SERVICE))
                if not re.fullmatch(r'[0-9a-fA-F]{32}', bus) or not Transport.OWNER.fullmatch(owner) or len(owner) > 64: raise _Invalid()
                return bus, owner
            bus, owner = identity()
            topology = read.topology(owner)
            objects, relation_reads, complete = {}, [], True
            for path, (_, interfaces) in topology.items():
                objects[path] = {}
                for interface, declarations in interfaces.items():
                    objects[path][interface] = {}
                    for prop in sorted(Transport.PROPERTIES.get(interface, ()) & declarations.keys()):
                        if interface == 'org.shadowblip.InputManager' and path != Transport.ROOT+'/Manager': continue
                        signature, access = declarations[prop]
                        if access == 'write': continue
                        tail = ('call', owner, path, 'org.freedesktop.DBus.Properties', 'Get', 'ss', interface, prop)
                        value = PropertyRead()
                        if signature == SIGNATURES[prop]:
                            value = read.property(tail, signature, prop)
                        objects[path][interface][prop] = value
                        complete &= value.state is EvidenceState.KNOWN
                        if prop in RELATIONS: relation_reads.append((tail, value, signature))
            if read.topology(owner) != topology: raise _Invalid()
            for tail, earlier, signature in relation_reads:
                later = read.property(tail, signature, tail[-1])
                if later != earlier: raise _Invalid()
            if identity() != (bus, owner): raise _Invalid()
            return ProviderReadFrame(bus + ':' + owner, objects, EvidenceState.KNOWN, bool(complete))
        except Exception:
            # Exceptions, stderr and partial private identities never escape.
            return failed
