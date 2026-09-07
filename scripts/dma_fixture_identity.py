"""Read-only, exact render-node identity for a separately supervised fixture."""
from dataclasses import dataclass
import itertools
import os
from pathlib import Path
import re
import stat
import sys

if Path(__file__).name != '__main__.py':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

from scripts.probe_audio_trial_context import capture
from hdm.adapters.steamos.drm import DrmDiscovery
from hdm.adapters.steamos.pci import PciUsb4Discovery
from hdm.adapters.steamos.host import HostDiscovery
from hdm.profiles.ally_x_audio import match_ally_x_analog_audio
from hdm.profiles.gpd_g1 import match_gpd_g1


from hdm.adapters.steamos.prepare_hardware_identity import RenderTarget, resolve_targets


@dataclass(frozen=True)
class FixtureIdentity:
    internal: RenderTarget
    external: RenderTarget
    context_digest: str


def collect_identity(*, context_capture=capture, drm=None, pci=None, host=None,
                     resolve_nodes=resolve_targets, platform=None, effective_uid=None):
    """New context and inventory brackets on each call; no GPU file opens."""
    if (sys.platform if platform is None else platform) != 'linux':
        raise ValueError('Linux required')
    uid=(getattr(os,'geteuid',lambda:-1) if effective_uid is None else effective_uid)()
    if type(uid) is not int or uid!=0:
        raise ValueError('root read-only observation required')
    drm=DrmDiscovery() if drm is None else drm
    pci=PciUsb4Discovery() if pci is None else pci
    host=HostDiscovery() if host is None else host
    def context():
        value=context_capture()
        if (type(value) is not dict or value.get('ready') is not True
                or value.get('code')!='audio_context_observed'
                or type(value.get('context_digest')) is not str
                or re.fullmatch(r'[0-9a-f]{64}',value['context_digest']) is None):
            raise ValueError('fresh audio context unavailable')
        return value['context_digest']
    def matches():
        cards,devices=drm.scan(),pci.scan_pci()
        usb4,complete=pci.scan_usb4_checked()
        if complete is not True or type(usb4) is not tuple or len(usb4)>64:
            raise ValueError('transport inventory incomplete')
        internal=match_ally_x_analog_audio(host.scan(),cards,devices)
        external=match_gpd_g1(cards,devices,usb4)
        if internal is None or external.verified is not True:
            raise ValueError('exact internal and G1 identities unavailable')
        names=[]
        for bdf in (internal.gpu_bdf,external.gpu_bdf):
            names_for_bdf=[card.name for card in cards if card.pci_bdf==bdf]
            if len(names_for_bdf)!=1:
                raise ValueError('DRM card identity ambiguous')
            names.append((bdf,names_for_bdf[0]))
        return tuple(names),internal,external
    before=context()
    first=matches()
    targets=resolve_nodes(first[0])
    second=matches()
    current=resolve_nodes(second[0])
    after=context()
    if before!=after or first!=second or targets!=current:
        raise ValueError('fixture identity changed during observation')
    return FixtureIdentity(targets[0],targets[1],before)
