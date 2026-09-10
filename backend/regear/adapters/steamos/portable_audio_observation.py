"""Pure default-sink evidence bound to caller-verified internal PCI audio.

Neither non-G1 identity nor configured-default metadata establishes Portable
audio. The caller establishes topology authority and freshness independently.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re


MAX_DUMP_BYTES = 1024 * 1024
MAX_OBJECTS = 4096
MAX_METADATA_ENTRIES = 4096
_BDF = re.compile(r'[0-9a-f]{4}:[0-9a-f]{2}:[0-1][0-9a-f]\.[0-7]')
_SINK_NAME = re.compile(r'[A-Za-z0-9_.:-]{1,256}')


@dataclass(frozen=True, slots=True)
class PortableDefaultObservation:
    ready: bool
    code: str
    sink_name: str = ''
    device_bdf: str = ''
    device_id: int | None = None
    sink_id: int | None = None


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate_json_key')
        result[key] = value
    return result


def _number(value, positive=False):
    return type(value) is int and (1 if positive else 0) <= value < 2**32


def parse_portable_default(raw_dump: bytes | str, *, sink_name: str,
                           audio_bdf: str) -> PortableDefaultObservation:
    """Observe one exact internal sink and its actual subject-zero default."""
    def fail(code):
        return PortableDefaultObservation(False, 'portable_audio.' + code)

    if (type(sink_name) is not str or not _SINK_NAME.fullmatch(sink_name)
            or type(audio_bdf) is not str or not _BDF.fullmatch(audio_bdf)):
        return fail('identity_invalid')
    if not isinstance(raw_dump, (bytes, str)) or len(raw_dump) > MAX_DUMP_BYTES:
        return fail('dump_invalid')
    try:
        if isinstance(raw_dump, bytes):
            raw_dump = raw_dump.decode('utf-8')
        elif len(raw_dump.encode('utf-8')) > MAX_DUMP_BYTES:
            return fail('dump_invalid')
        values = json.loads(raw_dump, object_pairs_hook=_unique_object)
    except (ValueError, UnicodeError, RecursionError):
        return fail('dump_invalid')
    if not isinstance(values, list) or len(values) > MAX_OBJECTS:
        return fail('dump_invalid')
    ids, device_matches, sink_matches, defaults = set(), [], [], []
    default_metadata_count = 0
    for value in values:
        if not isinstance(value, dict) or not _number(value.get('id')):
            return fail('object_invalid')
        if value['id'] in ids:
            return fail('object_ambiguous')
        ids.add(value['id'])
        kind = value.get('type')
        if kind not in ('PipeWire:Interface:Device', 'PipeWire:Interface:Node',
                        'PipeWire:Interface:Metadata'):
            continue
        info = value.get('info')
        # pw-dump's metadata_dump emits properties at the object top level;
        # Device and Node info serializers nest their properties under info.
        props = (value.get('props') if kind == 'PipeWire:Interface:Metadata'
                 else info.get('props') if isinstance(info, dict) else None)
        if not isinstance(props, dict):
            return fail('properties_unavailable')
        if kind == 'PipeWire:Interface:Device':
            if props.get('device.bus-path') == 'pci-' + audio_bdf:
                if (not _number(value['id'], True) or props.get('device.api') != 'alsa'
                        or props.get('device.bus') != 'pci'):
                    return fail('device_identity_invalid')
                device_matches.append(value['id'])
        elif kind == 'PipeWire:Interface:Node':
            if props.get('node.name') == sink_name:
                if (not _number(value['id'], True) or not _number(props.get('device.id'), True)
                        or props.get('media.class') != 'Audio/Sink'):
                    return fail('sink_identity_invalid')
                sink_matches.append((value['id'], props['device.id']))
        else:
            is_default = props.get('metadata.name') == 'default'
            default_metadata_count += int(is_default)
            entries = value.get('metadata')
            if not isinstance(entries, list) or len(entries) > MAX_METADATA_ENTRIES:
                return fail('metadata_invalid')
            keys = set()
            for entry in entries:
                if (not isinstance(entry, dict) or not _number(entry.get('subject'))
                        or type(entry.get('key')) is not str):
                    return fail('metadata_invalid')
                key = (entry['subject'], entry['key'])
                if key in keys:
                    return fail('metadata_ambiguous')
                keys.add(key)
                if entry['key'] == 'default.audio.sink':
                    default = entry.get('value')
                    if (not is_default or entry['subject'] != 0 or not isinstance(default, dict)
                            or type(default.get('name')) is not str
                            or not _SINK_NAME.fullmatch(default['name'])):
                        return fail('default_invalid')
                    defaults.append(default['name'])
    if len(device_matches) != 1 or len(sink_matches) != 1:
        return fail('device_or_sink_ambiguous')
    if sink_matches[0][1] != device_matches[0]:
        return fail('sink_device_mismatch')
    if default_metadata_count != 1 or len(defaults) != 1:
        return fail('default_ambiguous')
    if defaults[0] != sink_name:
        return fail('default_mismatch')
    return PortableDefaultObservation(True, 'portable_audio.observed', sink_name,
                                      audio_bdf, device_matches[0], sink_matches[0][0])
