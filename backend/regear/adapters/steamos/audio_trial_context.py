"""Fresh bracketed hardware/session context for the separate audio trial."""
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import time

from .audio_trial_observer import AudioTrialContext
from .discovery import SteamOsDiscovery
from .drm import DrmDiscovery
from .pci import PciUsb4Discovery
from .host import HostDiscovery
from .gamescope import GamescopeDiscovery
from .gamescope_user import resolve_gamescope_user
from .filter_unit_observer import FilterUnitObserver
from ...profiles.ally_x_audio import match_ally_x_analog_audio
from ...profiles.gpd_g1 import match_gpd_g1
from ...domain.inference import infer_placement
from ...domain.control_plane import PlacementState
from ...domain.models import ObservedSnapshot, GameState


def _boot_identity():
    with Path('/proc/sys/kernel/random/boot_id').open('r', encoding='ascii') as source:
        value = source.read(65).strip()
    if re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', value) is None:
        raise ValueError('boot identity unavailable')
    return value


def _process_cgroup(pid):
    with (Path('/proc') / str(pid) / 'cgroup').open('r', encoding='ascii') as source:
        raw = source.read(4097)
    lines = raw.splitlines()
    if len(raw) > 4096 or len(lines) != 1 or not lines[0].startswith('0::/'):
        raise ValueError('unified process cgroup unavailable')
    return lines[0][3:]


class AudioTrialContextSource:
    """Injected sources must perform new observations on every call.

    Deadline bounds acceptance, with short service-command deadlines. Existing
    filesystem discovery is synchronous and cannot be forcibly interrupted.
    """
    def __init__(self, user, portable_sink, *, deadline, drm=None, pci=None,
                 host=None, gamescope=None, collect_snapshot=None,
                 resolve_user=resolve_gamescope_user, observe_unit=None,
                 read_boot=_boot_identity, read_process_cgroup=_process_cgroup, clock=time.monotonic,
                 wall_clock=lambda: datetime.now(timezone.utc)):
        if (type(portable_sink) is not str or
                re.fullmatch(r'[A-Za-z0-9_.:-]{1,256}', portable_sink) is None):
            raise ValueError('invalid portable sink')
        self.user, self.portable_sink, self.deadline = user, portable_sink, deadline
        self.drm = DrmDiscovery() if drm is None else drm
        self.pci = PciUsb4Discovery() if pci is None else pci
        self.host = HostDiscovery() if host is None else host
        self.gamescope = GamescopeDiscovery() if gamescope is None else gamescope
        self.collect_snapshot = (SteamOsDiscovery().collect_snapshot if collect_snapshot is None
                                 else collect_snapshot)
        self.resolve_user, self.observe_unit = resolve_user, observe_unit
        self.read_boot, self.clock, self.wall_clock = read_boot, clock, wall_clock
        self.read_process_cgroup = read_process_cgroup

    def _now(self):
        now = self.clock()
        if (type(now) not in (int, float) or not math.isfinite(now) or now < 0
                or type(self.deadline) not in (int, float) or not math.isfinite(self.deadline)
                or not 0 < self.deadline - now <= 30):
            raise TimeoutError('audio context deadline expired')
        return now

    def _bracket(self):
        self._now()
        boot = self.read_boot()
        if type(boot) is not str or re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', boot) is None:
            raise ValueError('boot identity unavailable')
        cards, devices = self.drm.scan(), self.pci.scan_pci()
        usb4, complete = self.pci.scan_usb4_checked()
        host = self.host.scan()
        if complete is not True or type(usb4) is not tuple or len(usb4) > 64:
            raise ValueError('incomplete transport inventory')
        internal = match_ally_x_analog_audio(host, cards, devices)
        external = match_gpd_g1(cards, devices, usb4)
        if internal is None or not external.verified or internal.audio_bdf == external.audio_bdf:
            raise ValueError('audio hardware identity unverified')
        scan = self.gamescope.scan()
        owner = self.resolve_user(scan)
        if not scan.ok or not owner.ok or owner.context != self.user:
            raise ValueError('Gamescope owner changed or unverified')
        process = scan.process
        if (type(process.pid) is not int or process.pid <= 0
                or type(process.start_time_ticks) is not int or process.start_time_ticks <= 0
                or type(process.uid) is not int or process.uid != self.user.uid):
            raise ValueError('Gamescope process identity unavailable')
        observer = self.observe_unit
        if observer is None:
            observer = FilterUnitObserver(self.user, deadline=min(self.deadline, self._now() + 1.0), clock=self.clock)
        unit = observer('gamescope-session.service')
        if (type(unit) is not dict or set(unit) != FilterUnitObserver.FIELDS
                or unit['ActiveState'] != 'active'
                or type(unit['InvocationID']) is not str
                or re.fullmatch(r'[0-9a-f]{32}', unit['InvocationID']) is None
                or type(unit['MainPID']) is not str or re.fullmatch(r'[1-9][0-9]*', unit['MainPID']) is None
                or type(unit['ControlGroup']) is not str
                or unit['ControlGroup'] != f'/user.slice/user-{self.user.uid}.slice/user@{self.user.uid}.service/session.slice/gamescope-session.service'):
            raise ValueError('session service identity unavailable')
        if self.read_process_cgroup(process.pid) != unit['ControlGroup']:
            raise ValueError('Gamescope process is outside observed session service')
        # MainPID may be the session shell rather than the Gamescope child.
        # Both are retained across the bracket; PID-start binds the child.
        relevant = set(external.pci_functions) | {internal.gpu_bdf, internal.audio_bdf} | set(internal.upstream)
        topology = dict(internal=asdict(internal), external=asdict(external),
                        devices=sorted((asdict(p) for p in devices if p.bdf in relevant), key=lambda p: p['bdf']),
                        usb4=sorted((asdict(u) for u in usb4), key=lambda u: u['sysfs_id']))
        digest = hashlib.sha256(json.dumps(topology, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        card = next(c for c in cards if c.pci_bdf == internal.gpu_bdf)
        self._now()
        return (hashlib.sha256(boot.encode()).hexdigest(), digest, external.audio_bdf,
                internal.audio_bdf, process.pid, process.start_time_ticks, process.uid,
                unit['InvocationID'], unit['MainPID'], unit['ControlGroup'], card.vendor_device,
                tuple(c.name for c in card.connectors if c.internal and c.connected is True))

    def __call__(self):
        started = self._now()
        before = self._bracket()
        wall_before = self.wall_clock()
        snapshot = self.collect_snapshot()
        wall_after = self.wall_clock()
        self._now()
        if type(snapshot) is not ObservedSnapshot:
            raise ValueError('snapshot unavailable')
        stamp = datetime.fromisoformat(snapshot.observed_at)
        if (wall_before.tzinfo is None or wall_after.tzinfo is None or stamp.tzinfo is None
                or not wall_before <= stamp <= wall_after
                or infer_placement(snapshot) is not PlacementState.PORTABLE
                or snapshot.game_state is not GameState.IDLE
                or snapshot.gamescope.pid != before[4]
                or snapshot.gamescope.render_vendor_device != before[10]
                or snapshot.host_profile != 'asus-rog-ally-x'
                or any(g.vendor_device != before[10] for g in snapshot.gpus if g.selected_for_render is True)
                or not any(d.active is True and d.connector in before[11] for d in snapshot.displays)):
            raise ValueError('fresh Portable idle snapshot required')
        after = self._bracket()
        ended = self._now()
        if before != after or not 0 <= ended - started <= 2:
            raise ValueError('audio hardware/session context changed or expired')
        return AudioTrialContext(before[0], before[1], before[2], before[3],
                                 self.portable_sink, self.user.uid, before[7], True, True, started)
