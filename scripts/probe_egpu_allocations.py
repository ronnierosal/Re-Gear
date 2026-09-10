"""Bounded read-only follow-up probe; stdout only, never disconnect clearance."""
from __future__ import annotations

import dataclasses
import json
import itertools
import os
from pathlib import Path
import sys
import time

if Path(__file__).name != '__main__.py':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

from regear.adapters.steamos.drm import DrmDiscovery
from regear.adapters.steamos.pci import PciUsb4Discovery
from regear.adapters.steamos.egpu_clients import EgpuClientDiscovery
from regear.profiles.gpd_g1 import match_gpd_g1

NAMES = frozenset(('steam', 'gamescope-wl', 'wireplumber'))


def bounded_text(path, limit=16384):
    with path.open('rb') as source:
        raw = source.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('read_bound')
    return raw.decode('utf-8', errors='strict')


def process_start(path):
    # comm can contain spaces/parentheses; split after its last closing paren.
    fields = bounded_text(path / 'stat').rsplit(')', 1)[1].split()
    return int(fields[19])


def exact_match():
    topology = PciUsb4Discovery()
    return match_gpd_g1(DrmDiscovery().scan(), topology.scan_pci(), topology.scan_usb4())


def capture_processes(targets, *, proc_root=Path('/proc')):
    """Capture only the three known remaining holders, not all system clients."""
    rows = {}
    errors = []
    deadline = time.monotonic() + 10
    entries = list(itertools.islice(proc_root.iterdir(), 8193))
    if len(entries) > 8192:
        raise ValueError('process_count_bound')
    for path in entries:
        if time.monotonic() >= deadline:
            errors.append('capture_deadline')
            break
        if not path.name.isdecimal():
            continue
        try:
            name = bounded_text(path / 'comm', 256).strip()
            if name not in NAMES:
                continue
            start = process_start(path)
            row = {'name': name, 'fdinfo': [], 'mapping_counts': {}, 'libraries': [], 'errors': []}
            try:
                descriptors = list(itertools.islice((path / 'fd').iterdir(), 8193))
                if len(descriptors) > 8192:
                    raise ValueError('descriptor_count_bound')
                for descriptor in descriptors:
                    if time.monotonic() >= deadline:
                        row['errors'].append('capture_deadline')
                        break
                    try:
                        target = os.readlink(descriptor).removesuffix(' (deleted)')
                        if target not in targets:
                            continue
                        info = bounded_text(path / 'fdinfo' / descriptor.name)
                        if os.readlink(descriptor).removesuffix(' (deleted)') != target:
                            raise ValueError('descriptor_changed')
                        row['fdinfo'].append((targets[target].value, info))
                    except FileNotFoundError:
                        row['errors'].append('descriptor_disappeared')
                    except (OSError, ValueError):
                        row['errors'].append('descriptor_unreadable')
            except (OSError, ValueError):
                row['errors'].append('descriptors_unreadable')
            try:
                libraries = set()
                for line in bounded_text(path / 'maps', 4 * 1024 * 1024).splitlines():
                    fields = line.split(None, 5)
                    if len(fields) < 5:
                        raise ValueError('malformed_mapping')
                    if len(fields) != 6:
                        continue
                    target = fields[-1].removesuffix(' (deleted)')
                    if target in targets:
                        kind = targets[target].value
                        row['mapping_counts'][kind] = row['mapping_counts'].get(kind, 0) + 1
                    basename = Path(target).name
                    # Export categories, never raw mapping paths or arbitrary names.
                    for needle, category in (('libGLX_mesa', 'mesa_opengl'), ('libvulkan', 'vulkan'),
                                              ('libVkLayer_MESA_device_select', 'mesa_vulkan_device_select')):
                        if basename.startswith(needle):
                            libraries.add(category)
                row['libraries'] = sorted(libraries)
            except (OSError, ValueError):
                row['errors'].append('mappings_unreadable')
            if process_start(path) != start:
                errors.append('process_changed')
                continue
            rows[(path.name, start)] = row
        except FileNotFoundError:
            continue
        except (OSError, ValueError, IndexError):
            errors.append('process_observation_incomplete')
    return rows, sorted(set(errors))


def audio_states(match):
    states = []
    sound = Path('/sys/bus/pci/devices') / match.audio_bdf / 'sound'
    if not match.audio_bdf or not sound.is_dir():
        return ['unknown']
    for card in sound.iterdir():
        if not card.name.startswith('card') or not card.name[4:].isdigit():
            continue
        paths = list((Path('/proc/asound') / card.name).glob('pcm*/sub*/status'))
        if len(paths) > 32:
            return ['unknown']
        for path in paths:
            try:
                value = bounded_text(path, 4096)
                if value.strip() == 'closed':
                    states.append('closed')
                else:
                    state = next((line.split(':', 1)[1].strip() for line in value.splitlines()
                                  if line.startswith('state:')), 'unknown')
                    states.append(state if state in ('RUNNING', 'PREPARED', 'OPEN', 'SETUP',
                                                     'XRUN', 'DRAINING', 'PAUSED', 'SUSPENDED') else 'unknown')
            except (OSError, ValueError):
                states.append('unknown')
    return states or ['unknown']


def main():
    match = exact_match()
    if not match.verified:
        print(json.dumps({'error': 'egpu_identity_unverified', 'disconnect_clearance': False}))
        return 1
    targets, error = EgpuClientDiscovery()._resource_targets(match.gpu_bdf, match.audio_bdf)
    if error:
        print(json.dumps({'error': 'resource_identity_unverified', 'disconnect_clearance': False}))
        return 1
    boot = bounded_text(Path('/proc/sys/kernel/random/boot_id'))
    before, errors_before = capture_processes(targets)
    started = time.monotonic()
    time.sleep(1)
    after, errors_after = capture_processes(targets)
    elapsed = time.monotonic() - started
    current = exact_match()
    stable = (current.verified and current.stable_id == match.stable_id
              and current.gpu_bdf == match.gpu_bdf and current.audio_bdf == match.audio_bdf
              and bounded_text(Path('/proc/sys/kernel/random/boot_id')) == boot)
    # summarize() is separate so raw kernel client IDs and paths never leave
    # the process. Every memory value is scoped to one deduplicated DRM client.
    report = summarize(before, after, device_stable=stable)
    report.update(schema_version=1, privileged=os.geteuid() == 0,
                  scope='steam_gamescope_wireplumber_only', identity_stable=stable,
                  interval_seconds=round(elapsed, 3), audio_pcm_states=audio_states(match),
                  observation_errors=sorted(set(errors_before + errors_after)),
                  disconnect_clearance=False)
    if not stable:
        report['observation_errors'].append('attachment_changed')
    print(json.dumps(report, sort_keys=True))
    return 0


def summarize(before, after, *, device_stable):
    from regear.delivery.drm_fdinfo import parse_drm_fdinfo, compare_engine_samples
    rows = []
    for key, row in after.items():
        prior = before.get(key)
        groups = {}
        old_groups = {}
        for source, group in ((prior, old_groups), (row, groups)):
            if source is None:
                continue
            for kind, raw in source['fdinfo']:
                if not kind.startswith('drm_'):
                    continue
                parsed = parse_drm_fdinfo(raw)
                identity = (parsed.driver, parsed.client_id) if parsed.client_id is not None else ('unknown', len(group))
                if identity not in group:
                    group[identity] = {'parsed': parsed, 'descriptor_count': 1}
                else:
                    group[identity]['descriptor_count'] += 1
        clients = []
        for identity, entry in groups.items():
            parsed = entry['parsed']
            previous = old_groups.get(identity)
            clients.append(dict(descriptor_count=entry['descriptor_count'],
                stats=dataclasses.asdict(parsed),
                activity=dataclasses.asdict(compare_engine_samples(previous['parsed'], parsed,
                    before_device='matched-egpu', after_device='matched-egpu' if device_stable else ''))
                    if previous else {'status':'unknown','reason':'no_prior_client'}))
            clients[-1]['stats'].pop('client_id', None)
        rows.append(dict(name=row['name'], process_stable=prior is not None,
                         graphics_clients=clients, mapping_counts=row['mapping_counts'],
                         libraries=row['libraries'], errors=sorted(set(
                             row['errors'] + (prior['errors'] if prior is not None else []))),
                         audio_control_descriptors=sum(kind=='audio_control' for kind,_ in row['fdinfo'])))
    return {'processes': rows, 'process_set_stable': set(before)==set(after)}


if __name__ == '__main__':
    raise SystemExit(main())
