"""Fresh Steam-only prepare evidence; no launch, arm, or runtime authority.

Idle means no recognized Steam game scope in complete bounded scans, not absence
of arbitrary workloads. Importer and broker restrictions remain UNKNOWN. Each
DMA timestamp is collection start for the entire bracket and is never renewed.
Gamescope effective-launch resolution is explicitly unsupported.
"""
from dataclasses import dataclass,field
import math
import os
from pathlib import Path
import time

from ..adapters.steamos.prepare_hardware_identity import PrepareHardwareIdentity,PrepareHardwareIdentitySource
from ..adapters.steamos.game_scopes import LaunchGameScopeDiscovery,GameScopeScan
from ..adapters.steamos.device_receive_symbols import read_receive_symbols,ReceiveSymbols
from ..domain.models import GameState
from .device_filter_arm import FilterArm
from .device_filter_peer import WaitingPeerIdentity
from .device_filter_lifecycle import LaunchBinding
from .device_filter_effective_launch import SteamLaunchExpectation,EffectiveSteamLaunchObserver,EffectiveSteamLaunch
from .device_filter_wrapper import config_hash
from .gamescope_wrapper import _load_config
from .inherited_resource_scan import scan_inherited_resources,InheritedResourceObservation
from .device_receive_layout_cache import DmaReceiveLayoutCache,CachedDmaLayout,MAX_BTF_BYTES
from .device_receive_attachment import DmaReceiveObservation


@dataclass(frozen=True)
class PreparedLaunchCollection:
    evidence: object
    dma: DmaReceiveObservation = field(repr=False)

    def __post_init__(self):
        from .device_filter_prepare_server import FilterPrepareEvidence
        if type(self.evidence) is not FilterPrepareEvidence or type(self.dma) is not DmaReceiveObservation:
            raise ValueError('typed prepare collection required')


def read_btf():
    with open('/sys/kernel/btf/vmlinux','rb') as source:return source.read(MAX_BTF_BYTES+1)


class PreparedLaunchObservationSource:
    _unit="steam-launcher.service"
    _expectation_type=SteamLaunchExpectation
    _effective_type=EffectiveSteamLaunch
    _effective_factory=EffectiveSteamLaunchObserver
    _collection_type=PreparedLaunchCollection

    def _effective_role_valid(self,value):return True

    def __init__(self,user,expected_arm,runtime,expected_hardware,effective_expectation,*,state_root,deadline,
                 hardware=None,scopes=None,effective_observer=None,inherited_scan=scan_inherited_resources,
                 config_loader=_load_config,hash_config=config_hash,btf_reader=read_btf,
                 symbols_reader=read_receive_symbols,layout_cache=None,clock=time.monotonic):
        if (type(expected_arm) is not FilterArm or user.uid!=expected_arm.uid
                or type(expected_hardware) is not PrepareHardwareIdentity
                or type(effective_expectation) is not self._expectation_type or effective_expectation.runtime!=runtime
                or expected_arm.unit!=self._unit):
            raise ValueError('independent Steam preparation expectations required')
        self.user,self.arm,self.runtime,self.expected_hardware=user,expected_arm,runtime,expected_hardware
        self.state_root=Path(state_root)
        if not self.state_root.is_absolute() or '..' in self.state_root.parts:raise ValueError('absolute state root required')
        self.deadline,self.clock=deadline,clock
        self.hardware=PrepareHardwareIdentitySource(clock=clock) if hardware is None else hardware
        self.scopes=LaunchGameScopeDiscovery(clock=clock) if scopes is None else scopes
        self.effective=(self._effective_factory(user,effective_expectation,deadline=deadline,clock=clock)
                        if effective_observer is None else effective_observer)
        self.scan,self.load_config,self.hash_config=inherited_scan,config_loader,hash_config
        self.read_btf,self.read_symbols=btf_reader,symbols_reader
        self.cache=DmaReceiveLayoutCache() if layout_cache is None else layout_cache

    def __call__(self,held):
        from .device_filter_prepare_server import FilterPrepareEvidence,IsolationCoverage
        previous=None
        def now():
            nonlocal previous
            value=self.clock()
            if (type(value) not in (int,float) or not math.isfinite(value) or value<0
                    or type(self.deadline) not in (int,float) or not math.isfinite(self.deadline)
                    or value>=self.deadline or (previous is not None and value<previous)):
                raise ValueError('prepare observation deadline unavailable')
            previous=value
            return value
        start=now()
        if self.deadline-start>5:raise ValueError('bounded launch observation required')
        identity=held.revalidate()
        if (type(identity) is not WaitingPeerIdentity or identity.uid!=self.user.uid
                or identity.unit!=self._unit):
            raise ValueError('Steam held identity required; Gamescope unsupported')
        hardware=self.hardware.collect(deadline=self.deadline);now()
        if type(hardware) is not PrepareHardwareIdentity or hardware!=self.expected_hardware:
            raise ValueError('independent hardware expectation changed')
        if (hardware.boot_hash,hardware.topology_hash)!=(self.arm.boot_hash,self.arm.topology_hash):
            raise ValueError('hardware differs from expected operation')
        denied=((os.major(hardware.external.device),hardware.external.primary_minor),
                (os.major(hardware.external.device),os.minor(hardware.external.device)))
        def idle():
            scan=self.scopes.scan(identity.uid,deadline=self.deadline);now()
            if (type(scan) is not GameScopeScan or scan.state is not GameState.IDLE or not scan.ok
                    or scan.scopes or scan.app_ids or scan.unparsed_current_scopes):
                raise ValueError('recognized Steam scope idle evidence unavailable')
            return scan
        before_game=idle()
        before_config=self.hash_config(self.load_config(self.state_root));now()
        if before_config!=self.arm.config_hash:raise ValueError('saved launch configuration changed')
        def effective_launch():
            effective=self.effective(identity);current=now()
            if (type(effective) is not self._effective_type or not self._effective_role_valid(effective) or effective.identity!=identity
                    or effective.runtime_digest!=self.runtime.digest or type(effective.observed_at) not in (int,float)
                    or not math.isfinite(effective.observed_at) or not start<=effective.observed_at<=current):
                raise ValueError('effective Steam launch not observed in bracket')
            return effective
        effective_launch()
        inherited=self.scan(held,denied,deadline=self.deadline,clock=self.clock);now()
        if (type(inherited) is not InheritedResourceObservation or inherited.complete is not True
                or any(value is not False for value in (inherited.target_character_seen,inherited.dma_buf_seen,inherited.unclassified_seen))):
            raise ValueError('inherited resources incomplete or present')
        parsed=self.cache.parse(self.read_btf(),pointer_size=8);now()
        if type(parsed) is not CachedDmaLayout:raise ValueError('typed running-kernel layout required')
        symbols=self.read_symbols();now()
        if type(symbols) is not ReceiveSymbols:raise ValueError('fresh symbol identities required')
        if self.hash_config(self.load_config(self.state_root))!=before_config:raise ValueError('configuration changed during collection')
        now()
        if idle()!=before_game:raise ValueError('scope evidence changed')
        if self.hardware.collect(deadline=self.deadline)!=hardware:raise ValueError('hardware changed during collection')
        effective_launch()
        if held.revalidate()!=identity:raise ValueError('held identity changed during collection')
        finish=now()
        if finish-start>2:raise ValueError('prepare collection exceeded freshness bound')
        binding=LaunchBinding(hardware.boot_hash,self.arm.operation,identity.unit,identity.invocation,
            identity.uid,identity.pid,identity.starttime,identity.cgroup_dev,identity.cgroup_inode,
            hardware.topology_hash,self.deadline)
        dma=DmaReceiveObservation(binding,parsed.layout,symbols.dma_buf_fops,symbols.amdgpu_dmabuf_ops,
                                  hardware.internal.primary_minor,parsed.btf_sha256,start)
        evidence=FilterPrepareEvidence(hardware.boot_hash,hardware.topology_hash,before_config,self.runtime.digest,
            denied,True,True,True,True,IsolationCoverage.UNKNOWN,IsolationCoverage.UNKNOWN)
        if now()-start>2:raise ValueError('prepare collection exceeded freshness bound')
        return self._collection_type(evidence,dma)
