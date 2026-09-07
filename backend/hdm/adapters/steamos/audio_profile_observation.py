"""Pure, bounded profile evidence for a caller-verified PCI audio function.

This parser does not establish G1 topology, freshness, or mutation authority.
Object IDs and profile indexes are ephemeral observations, not durable identity.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re


MAX_DUMP_BYTES = 1024 * 1024
MAX_OBJECTS = 4096
MAX_PROFILES = 256
_BDF = re.compile(r'^[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]$')
_NAME = re.compile(r'^[A-Za-z0-9_.:+-]{1,256}$')


@dataclass(frozen=True, slots=True)
class AudioProfile:
    name: str
    index: int
    available: str


@dataclass(frozen=True, slots=True)
class AudioProfileObservation:
    ready: bool
    code: str
    device_bdf: str = ''
    device_id: int | None = None
    current_profile: AudioProfile | None = None
    off_profile: AudioProfile | None = None
    profiles: tuple[AudioProfile, ...] = ()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate_json_key')
        result[key] = value
    return result


def _index(value, *, positive=False):
    return type(value) is int and (1 if positive else 0) <= value <= 4294967295


def parse_audio_profile_observation(raw_dump: bytes | str, *, audio_bdf: str) -> AudioProfileObservation:
    """Return explicit unavailable evidence instead of guessing any identity."""
    def fail(reason):
        return AudioProfileObservation(False, 'audio_profile.' + reason)

    if not isinstance(audio_bdf, str) or not _BDF.fullmatch(audio_bdf):
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
    matches = []
    seen = set()
    for value in values:
        if not isinstance(value, dict) or not _index(value.get('id')):
            return fail('object_invalid')
        if value['id'] in seen:
            return fail('object_ambiguous')
        seen.add(value['id'])
        if value.get('type') != 'PipeWire:Interface:Device':
            continue
        info = value.get('info')
        props = info.get('props') if isinstance(info, dict) else None
        if not isinstance(props, dict):
            return fail('device_invalid')
        if props.get('device.bus-path') == 'pci-' + audio_bdf:
            matches.append(value)
    if len(matches) != 1:
        return fail('device_ambiguous')
    device = matches[0]
    if not _index(device['id'], positive=True):
        return fail('device_identity_invalid')
    props = device['info']['props']
    if props.get('device.api') != 'alsa' or props.get('device.bus') != 'pci':
        return fail('device_identity_invalid')
    params = device['info'].get('params')
    if not isinstance(params, dict):
        return fail('profiles_unavailable')
    available, selected = params.get('EnumProfile'), params.get('Profile')
    if (not isinstance(available, list) or not 1 <= len(available) <= MAX_PROFILES
            or not isinstance(selected, list) or len(selected) != 1):
        return fail('profiles_unavailable')
    profiles = []
    names, indexes = set(), set()
    for item in available:
        if (not isinstance(item, dict) or not _index(item.get('index'))
                or not isinstance(item.get('name'), str) or not _NAME.fullmatch(item['name'])
                or item.get('available') not in ('yes', 'no', 'unknown')):
            return fail('profile_invalid')
        if item['name'] in names or item['index'] in indexes:
            return fail('profile_ambiguous')
        names.add(item['name'])
        indexes.add(item['index'])
        profiles.append(AudioProfile(item['name'], item['index'], item['available']))
    current = selected[0]
    if (not isinstance(current, dict) or not _index(current.get('index'))
            or not isinstance(current.get('name'), str) or not _NAME.fullmatch(current['name'])):
        return fail('current_profile_invalid')
    current_matches = [p for p in profiles if p.index == current['index'] and p.name == current['name']]
    if len(current_matches) != 1:
        return fail('current_profile_mismatch')
    off = [p for p in profiles if p.name == 'off' and p.available == 'yes']
    if len(off) != 1:
        return fail('off_unavailable')
    return AudioProfileObservation(True, 'audio_profile.observed', audio_bdf,
                                   device['id'], current_matches[0], off[0], tuple(profiles))
