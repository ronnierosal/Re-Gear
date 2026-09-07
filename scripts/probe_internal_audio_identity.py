"""Read-only relationship evidence, never internal-audio certification."""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys

if Path(__file__).name != '__main__.py':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

from hdm.adapters.steamos.drm import DrmDiscovery
from hdm.adapters.steamos.pci import PciUsb4Discovery
from hdm.adapters.steamos.host import HostDiscovery
from hdm.adapters.steamos.gamescope import GamescopeDiscovery
from hdm.adapters.steamos.gamescope_user import resolve_gamescope_user
from hdm.adapters.steamos.commands import PipeWireCommandRunner
from hdm.adapters.steamos.audio_profile_observation import parse_audio_profile_observation
from hdm.profiles.ally_x import match_ally_x

_BDF = re.compile(r'[0-9a-f]{4}:[0-9a-f]{2}:[01][0-9a-f]\.[0-7]')
_HEX_ID = re.compile(r'0x[0-9a-f]{4}')
_CLASS = re.compile(r'0x[0-9a-f]{6}')
_DRIVER = re.compile(r'[A-Za-z0-9_-]{1,64}')


def _pci_record(record):
    if (not _BDF.fullmatch(record.bdf) or not _HEX_ID.fullmatch(record.vendor)
            or not _HEX_ID.fullmatch(record.device) or not _CLASS.fullmatch(record.class_code)
            or (record.driver and not _DRIVER.fullmatch(record.driver))
            or len(record.ancestry) > 32 or any(not _BDF.fullmatch(p) for p in record.ancestry)):
        raise ValueError('pci_record_invalid')
    return dict(bdf=record.bdf, vendor=record.vendor, device=record.device,
                class_code=record.class_code, driver=record.driver,
                ancestry=list(record.ancestry))


def capture(*, drm, pci, host, gamescope, resolve_user, commands):
    """Injected read-only sources; omit raw DMI, process and PipeWire properties."""
    report = dict(schema_version=1, internal_audio_verified=False,
                  disconnect_clearance=False, errors=[], internal_gpu_candidates=[],
                  pci_audio_devices=[], pipewire_audio_devices=[])
    try:
        report['ally_x_host_match'] = match_ally_x(host.scan()).exact
    except (OSError, ValueError, TypeError):
        report['ally_x_host_match'] = False
        report['errors'].append('host_observation_unavailable')
    try:
        devices = pci.scan_pci()
        cards = drm.scan()
        if len(devices) > 4096 or len(cards) > 64:
            raise ValueError('inventory_bound')
        by_bdf = {}
        for record in devices:
            safe = _pci_record(record)
            if safe['bdf'] in by_bdf:
                raise ValueError('duplicate_pci_identity')
            by_bdf[safe['bdf']] = safe
            if safe['class_code'].startswith('0x0403'):
                report['pci_audio_devices'].append(safe)
                if len(report['pci_audio_devices']) > 64:
                    raise ValueError('audio_inventory_bound')
        for card in cards:
            if card.boot_vga is True and any(c.internal for c in card.connectors):
                exact = by_bdf.get(card.pci_bdf)
                if exact is None:
                    raise ValueError('gpu_pci_relationship_missing')
                report['internal_gpu_candidates'].append(exact)
    except (OSError, ValueError, TypeError, AttributeError):
        report['errors'].append('pci_drm_observation_unavailable')
        return report
    try:
        resolution = resolve_user(gamescope.scan())
        if not resolution.ok or resolution.context is None:
            report['errors'].append('gamescope_user_unresolved')
            return report
        result = commands.dump(resolution.context)
    except (OSError, ValueError, TypeError, AttributeError):
        report['errors'].append('pipewire_observation_unavailable')
        return report
    if result.ok is not True:
        report['errors'].append('audio.root_required' if result.code == 'audio.root_required'
                                else 'pipewire_observation_unavailable')
        return report
    # The strict parser handles byte limits, duplicate objects/keys and exact
    # ALSA PCI binding. Iterate known PCI audio identities rather than exposing
    # names, paths, serials or identifiers from arbitrary PipeWire objects.
    for device in report['pci_audio_devices']:
        observation = parse_audio_profile_observation(result.output, audio_bdf=device['bdf'])
        row = dict(pci=device, profile_observation_code=observation.code)
        if observation.ready:
            row['profiles'] = [dict(name=p.name, index=p.index, available=p.available)
                               for p in observation.profiles]
            row['selected_profile'] = dict(name=observation.current_profile.name,
                                           index=observation.current_profile.index)
            row['same_pci_slot_as_gpu_candidates'] = [
                gpu['bdf'] for gpu in report['internal_gpu_candidates']
                if gpu['bdf'].rsplit('.', 1)[0] == device['bdf'].rsplit('.', 1)[0]]
        report['pipewire_audio_devices'].append(row)
    return report


def main():
    if sys.argv[1:]:
        raise SystemExit('No arguments accepted')
    if sys.platform != 'linux':
        print(json.dumps(dict(error='linux_required', internal_audio_verified=False,
                              disconnect_clearance=False)))
        return 1
    report = capture(drm=DrmDiscovery(), pci=PciUsb4Discovery(), host=HostDiscovery(),
                     gamescope=GamescopeDiscovery(), resolve_user=resolve_gamescope_user,
                     commands=PipeWireCommandRunner())
    print(json.dumps(report, sort_keys=True))
    return 0 if not report['errors'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
