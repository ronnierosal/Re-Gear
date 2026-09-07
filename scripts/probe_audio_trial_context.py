"""Read-only end-to-end audio context probe; never starts an audio trial."""
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import time

if Path(__file__).name != '__main__.py':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

from hdm.adapters.steamos.audio_trial_context import AudioTrialContextSource
from hdm.adapters.steamos.audio_trial_observer import AudioTrialLiveObserver
from hdm.adapters.steamos.portable_audio_observation import parse_portable_default
from hdm.adapters.steamos.commands import PipeWireCommandRunner
from hdm.adapters.steamos.drm import DrmDiscovery
from hdm.adapters.steamos.pci import PciUsb4Discovery
from hdm.adapters.steamos.host import HostDiscovery
from hdm.adapters.steamos.gamescope import GamescopeDiscovery
from hdm.adapters.steamos.gamescope_user import resolve_gamescope_user
from hdm.profiles.ally_x_audio import match_ally_x_analog_audio


def portable_baseline(raw, audio_bdf):
    """Extract only a candidate; strict full-dump validation is mandatory."""
    if not isinstance(raw, (bytes, str)) or len(raw) > 1024 * 1024:
        raise ValueError('baseline dump invalid')
    if isinstance(raw, str) and len(raw.encode('utf-8')) > 1024 * 1024:
        raise ValueError('baseline dump invalid')
    values = json.loads(raw)
    if not isinstance(values, list) or len(values) > 4096:
        raise ValueError('baseline dump invalid')
    names = []
    for value in values:
        if not isinstance(value, dict) or value.get('type') != 'PipeWire:Interface:Metadata':
            continue
        props = value.get('props')
        if not isinstance(props, dict) or props.get('metadata.name') != 'default':
            continue
        entries = value.get('metadata')
        if not isinstance(entries, list) or len(entries) > 4096:
            raise ValueError('baseline metadata invalid')
        for entry in entries:
            if (isinstance(entry, dict) and type(entry.get('subject')) is int
                    and entry['subject'] == 0 and entry.get('key') == 'default.audio.sink'):
                configured = entry.get('value')
                name = configured.get('name') if isinstance(configured, dict) else None
                if type(name) is not str or re.fullmatch(r'[A-Za-z0-9_.:-]{1,256}', name) is None:
                    raise ValueError('baseline name invalid')
                names.append(name)
    if len(names) != 1:
        raise ValueError('baseline default ambiguous')
    observed = parse_portable_default(raw, sink_name=names[0], audio_bdf=audio_bdf)
    if observed.ready is not True:
        raise ValueError('baseline internal binding invalid')
    return observed.sink_name


class _ContextFailure(Exception):
    pass


_CONTEXT_REASON_CODES = {
    'incomplete transport inventory': 'transport_inventory',
    'audio hardware identity unverified': 'hardware_identity',
    'Gamescope owner changed or unverified': 'owner_changed',
    'Gamescope process identity unavailable': 'process_identity',
    'session service identity unavailable': 'session_identity',
    'Gamescope process is outside observed session service': 'session_membership',
    'fresh Portable idle snapshot required': 'snapshot_not_idle_portable',
    'audio hardware/session context changed or expired': 'context_changed',
}


def capture(*, drm=None, pci=None, host=None, gamescope=None,
            resolve_user=resolve_gamescope_user, commands=None,
            context_factory=AudioTrialContextSource, clock=time.monotonic):
    started = clock()
    if type(started) not in (int, float) or not math.isfinite(started) or started < 0:
        raise ValueError('invalid clock')
    deadline = started + 10
    report = dict(schema_version=1, ready=False, code='baseline_unavailable',
                  disconnect_clearance=False, resources_released=False)
    drm = DrmDiscovery() if drm is None else drm
    pci = PciUsb4Discovery() if pci is None else pci
    host = HostDiscovery() if host is None else host
    gamescope = GamescopeDiscovery() if gamescope is None else gamescope
    commands = PipeWireCommandRunner() if commands is None else commands
    phase = 'baseline'
    try:
        analog = match_ally_x_analog_audio(host.scan(), drm.scan(), pci.scan_pci())
        if analog is None:
            raise ValueError('internal relationship unavailable')
        resolution = resolve_user(gamescope.scan())
        if not resolution.ok or resolution.context is None:
            raise ValueError('owner unavailable')
        remaining = deadline - clock()
        if not 0 < remaining <= 10:
            raise TimeoutError('baseline deadline')
        result = commands.dump(resolution.context, timeout_seconds=min(2.0, remaining))
        if result.ok is not True:
            report['code'] = 'baseline_root_required' if result.code == 'audio.root_required' else 'baseline_dump_unavailable'
            return report
        sink = portable_baseline(result.output, analog.audio_bdf)
        phase = 'context'
        source = context_factory(resolution.context, sink, deadline=deadline, clock=clock)
        contexts = []
        def context():
            try:
                value = source()
            except (OSError, ValueError, TypeError, AttributeError, RecursionError) as error:
                reason = _CONTEXT_REASON_CODES.get(str(error), 'unavailable') if type(error) is ValueError else 'unavailable'
                raise _ContextFailure(reason) from error
            contexts.append(value)
            return value
        phase = 'actual_profile'
        observed = AudioTrialLiveObserver(resolution.context, context, deadline=deadline,
                                         commands=commands, clock=clock)()
        if clock() >= deadline:
            raise TimeoutError('probe deadline')
        # Digest only; raw context contains the private sink name and UID.
        encoded = json.dumps({k:v for k,v in asdict(contexts[-1]).items() if k != 'observed_at'},
                             sort_keys=True,separators=(',', ':')).encode()
        report.update(ready=True,code='audio_context_observed',
                      context_digest=hashlib.sha256(encoded).hexdigest())
    except _ContextFailure as failure:
        report['code'] = 'context_' + failure.args[0]
    except TimeoutError:
        report['code'] = phase + '_deadline'
    except (OSError, ValueError, TypeError, AttributeError, RecursionError):
        report['code'] = phase + '_unavailable'
    finally:
        ended = clock()
        report['elapsed_seconds'] = round(ended-started,3) if type(ended) in (int,float) and math.isfinite(ended) and ended >= started else None
    return report


def main():
    if sys.platform != 'linux':
        print(json.dumps(dict(ready=False,code='linux_required',disconnect_clearance=False)))
        return 1
    report = capture()
    print(json.dumps(report,sort_keys=True))
    return 0 if report['ready'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
