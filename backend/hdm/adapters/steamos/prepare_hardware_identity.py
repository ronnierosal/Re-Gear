"""Lean launch hardware identity; no audio, process or game-state collection."""
from dataclasses import dataclass
import hashlib
import itertools
import math
import os
from pathlib import Path
import re
import stat
import time

from .drm import DrmDiscovery
from .pci import PciUsb4Discovery
from .host import HostDiscovery
from ...profiles.ally_x_audio import match_ally_x_analog_audio
from ...profiles.gpd_g1 import match_gpd_g1

@dataclass(frozen=True)
class RenderTarget:
    path: str
    device: int
    primary_minor: int
    bdf: str


def _dev(path):
    with path.open('r', encoding='ascii') as source:
        raw = source.read(65)
    match = re.fullmatch(r'(0|[1-9][0-9]{0,3}):(0|[1-9][0-9]{0,6})\n?', raw)
    if match is None:
        raise ValueError('invalid sysfs device number')
    major, minor = map(int, match.groups())
    if major > 4095 or minor > 1048575:
        raise ValueError('device number out of range')
    return major, minor


def resolve_targets(bindings, *, drm_root=Path('/sys/class/drm'),
                    char_root=Path('/sys/dev/char'), dev_root=Path('/dev/dri'),
                    pci_root=Path('/sys/bus/pci/devices'), lstat=lambda path:path.lstat()):
    """Enumerate explicitly: unreadable entries cannot become absent nodes."""
    if (type(bindings) is not tuple or len(bindings) != 2 or
            any(type(pair) is not tuple or len(pair) != 2
                or type(pair[0]) is not str or re.fullmatch(r'[0-9a-f]{4}:[0-9a-f]{2}:[01][0-9a-f]\.[0-7]',pair[0]) is None
                or type(pair[1]) is not str or re.fullmatch(r'card[0-9]+',pair[1]) is None for pair in bindings)
            or bindings[0][0] == bindings[1][0]):
        raise ValueError('two exact GPU identities required')
    entries=list(itertools.islice(drm_root.iterdir(),513))
    if len(entries)>512:
        raise ValueError('DRM inventory bound exceeded')
    found={bdf:[] for bdf,_ in bindings}
    for entry in entries:
        if re.fullmatch(r'(?:card[0-9]+|renderD[0-9]+)',entry.name) is None:
            continue
        real=entry.resolve(strict=True)
        device_path=(entry/'device').resolve(strict=True)
        bdf=device_path.name
        if re.fullmatch(r'[0-9a-f]{4}:[0-9a-f]{2}:[01][0-9a-f]\.[0-7]',bdf) is None:
            raise ValueError('DRM PCI identity unavailable')
        if device_path != (pci_root/bdf).resolve(strict=True):
            raise ValueError('DRM PCI path mismatch')
        major,minor=_dev(entry/'dev')
        if (char_root/f'{major}:{minor}').resolve(strict=True) != real:
            raise ValueError('sysfs character identity mismatch')
        node=dev_root/entry.name
        observed=lstat(node)
        if not stat.S_ISCHR(observed.st_mode) or observed.st_rdev != os.makedev(major,minor):
            raise ValueError('device node identity mismatch')
        if bdf in found:
            found[bdf].append((entry.name,str(node),observed.st_rdev,major,minor))
    result=[]
    for bdf,card_name in bindings:
        primary=[row for row in found[bdf] if row[0].startswith('card')]
        render=[row for row in found[bdf] if row[0].startswith('renderD')]
        if len(primary)!=1 or primary[0][0]!=card_name or len(render)!=1 or primary[0][3]!=render[0][3]:
            raise ValueError('exact primary/render pair unavailable')
        result.append(RenderTarget(render[0][1],render[0][2],primary[0][4],bdf))
    if result[0].device==result[1].device or result[0].path==result[1].path:
        raise ValueError('GPU render identities overlap')
    return tuple(result)


def read_boot_id():
    with open('/proc/sys/kernel/random/boot_id','r',encoding='ascii') as source:
        raw=source.read(65)
    if re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\n',raw) is None:
        raise ValueError('boot identity unavailable')
    return raw.strip()


@dataclass(frozen=True)
class PrepareHardwareIdentity:
    boot_hash: str
    topology_hash: str
    internal: RenderTarget
    external: RenderTarget


class PrepareHardwareIdentitySource:
    """Fresh matching hardware brackets, no game/audio/process observations.

    Topology hash uses the wrapper's boot-id:stable-id material. Richer node
    identities remain separate; equality does not certify workload isolation.
    """
    def __init__(self,*,drm=None,pci=None,host=None,resolve_nodes=resolve_targets,
                 boot=read_boot_id,clock=time.monotonic):
        self.drm=DrmDiscovery() if drm is None else drm
        self.pci=PciUsb4Discovery() if pci is None else pci
        self.host=HostDiscovery() if host is None else host
        self.resolve_nodes,self.boot,self.clock=resolve_nodes,boot,clock

    def collect(self,*,deadline):
        previous=None
        if type(deadline) not in (int,float) or not math.isfinite(deadline) or deadline<0:
            raise ValueError('finite collection deadline required')
        def check():
            nonlocal previous
            now=self.clock()
            if (type(now) not in (int,float) or not math.isfinite(now) or now<0 or now>=deadline
                    or (previous is not None and now<previous)):
                raise ValueError('hardware observation expired')
            previous=now
        def boot():
            check();value=self.boot();check()
            if type(value) is not str or re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}',value) is None:
                raise ValueError('exact raw boot identity required')
            return value
        def inventory():
            check();cards=self.drm.scan();check()
            devices=self.pci.scan_pci();check()
            usb4,complete=self.pci.scan_usb4_checked();check()
            if (type(cards) is not tuple or len(cards)>512 or type(devices) is not tuple or len(devices)>4096
                    or type(usb4) is not tuple or len(usb4)>64 or complete is not True):
                raise ValueError('bounded complete hardware inventory required')
            host=self.host.scan();check()
            internal=match_ally_x_analog_audio(host,cards,devices)
            external=match_gpd_g1(cards,devices,usb4)
            if (internal is None or external.verified is not True or type(external.stable_id) is not str
                    or not external.stable_id or len(external.stable_id)>256):
                raise ValueError('exact supported GPUs unavailable')
            bindings=[]
            for bdf in (internal.gpu_bdf,external.gpu_bdf):
                names=[card.name for card in cards if card.pci_bdf==bdf]
                if len(names)!=1:raise ValueError('ambiguous GPU card binding')
                bindings.append((bdf,names[0]))
            targets=self.resolve_nodes(tuple(bindings));check()
            if (type(targets) is not tuple or len(targets)!=2
                    or any(type(target) is not RenderTarget for target in targets)):
                raise ValueError('exact render targets required')
            return (cards,devices,usb4,host,internal,external,targets)
        before=boot();first=inventory();second=inventory();after=boot()
        if before!=after or first!=second:raise ValueError('hardware identity changed during observation')
        result=PrepareHardwareIdentity(hashlib.sha256(before.encode()).hexdigest(),
            hashlib.sha256((before+':'+first[5].stable_id).encode()).hexdigest(),*first[6])
        check()
        return result


