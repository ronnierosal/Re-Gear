"""Inactive Steam-only effective configuration observation, never approval.

The expectation is supplied independently, never learned from the live query.
Gamescope native session/PATH resolution is unsupported. Runtime file integrity,
held-peer authentication and environment-file contents are not inferred here.
"""
from dataclasses import dataclass
import math
import re
import shlex
import time

from ..adapters.steamos.commands import UserServiceCommandRunner
from ..ports.presentation_activation import UserServiceOperation
from .device_filter_runtime_bundle import RuntimeBundle
from .device_filter_peer import WaitingPeerIdentity

FRAGMENT = '/usr/lib/systemd/user/steam-launcher.service'
DROPIN = '/etc/systemd/user/steam-launcher.service.d/95-regear-filter-runtime.conf'
EMPTY = ('EnvironmentFiles','ExecStartPre','ExecStartPost','ExecCondition',
         'ExecSearchPath','RootDirectory','RootImage')
FIELDS = frozenset(('LoadState','FragmentPath','DropInPaths','ExecStart','Environment',
                    'InvocationID','MainPID',*EMPTY))


@dataclass(frozen=True)
class SteamLaunchExpectation:
    runtime: RuntimeBundle
    environment: tuple[str, ...]

    def __post_init__(self):
        if type(self.runtime) is not RuntimeBundle:
            raise ValueError('independent runtime expectation required')
        digest = self.runtime.digest
        if (type(digest) is not str or re.fullmatch(r'[0-9a-f]{64}',digest) is None
                or self.runtime.path != f'/var/lib/regear/filter-runtime/{digest}/runtime.pyz'
                or self.runtime.steam_argv != ('/usr/bin/python3','-I',self.runtime.path,'steam')):
            raise ValueError('fixed runtime command required')
        if (type(self.environment) is not tuple or len(self.environment)>64
                or any(type(v) is not str or len(v)>512 or not v.isascii()
                       or re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*=[^\x00-\x1f\x7f]*',v) is None
                       for v in self.environment)
                or len({v.split('=',1)[0] for v in self.environment})!=len(self.environment)):
            raise ValueError('explicit unique environment required')


@dataclass(frozen=True)
class EffectiveSteamLaunch:
    identity: WaitingPeerIdentity
    runtime_digest: str
    observed_at: float


def _matches_exec(value, argv, pid):
    # Strict supported systemctl-show serialization; unknown forms fail closed.
    if not value.startswith('{ ') or not value.endswith(' }'):
        return False
    fields={}
    for part in value[2:-2].split(' ; '):
        key,sep,item=part.partition('=')
        if not sep or key in fields:return False
        fields[key]=item
    if set(fields)!={'path','argv[]','ignore_errors','start_time','stop_time','pid','code','status'}:
        return False
    return (fields['path']==argv[0] and fields['argv[]']==' '.join(argv)
            and fields['ignore_errors']=='no'
            and fields['pid']==str(pid)
            and all('{' not in v and '}' not in v for v in fields.values()))


class EffectiveSteamLaunchObserver:
    def __init__(self,user,expectation,*,deadline,commands=None,clock=time.monotonic):
        if type(expectation) is not SteamLaunchExpectation:
            raise ValueError('independent Steam configuration required')
        self.user,self.expectation,self.deadline=user,expectation,deadline
        self.commands=commands if commands is not None else UserServiceCommandRunner(timeout_seconds=1)
        self.clock=clock

    def _now(self):
        now=self.clock()
        if (type(now) not in (int,float) or not math.isfinite(now)
                or type(self.deadline) not in (int,float) or not math.isfinite(self.deadline)
                or not 0<=now<self.deadline or self.deadline-now>5):
            raise ValueError('effective launch deadline unavailable')
        return now

    def __call__(self,identity):
        if (type(identity) is not WaitingPeerIdentity or identity.unit!='steam-launcher.service'
                or identity.uid!=self.user.uid):
            raise ValueError('Steam peer required; Gamescope resolution unsupported')
        before=self._now()
        result=self.commands.run(UserServiceOperation.OBSERVE_FILTER_STEAM_LAUNCH,
            uid=self.user.uid,username=self.user.username,timeout_seconds=min(1,self.deadline-before))
        after=self._now()
        if after<before or result.ok is not True:
            raise ValueError('effective Steam query unavailable')
        raw=result.output
        if type(raw) is not str or not 0<len(raw)<=4096 or not raw.isascii():
            raise ValueError('bounded Steam properties required')
        fields={}
        for line in raw.splitlines():
            key,sep,value=line.partition('=')
            if not sep or key not in FIELDS or key in fields:
                raise ValueError('unexpected Steam property')
            fields[key]=value
        if (set(fields)!=FIELDS or fields['LoadState']!='loaded'
                or fields['FragmentPath']!=FRAGMENT or fields['DropInPaths']!=DROPIN
                or any(fields[key] for key in EMPTY)
                or fields['InvocationID']!=identity.invocation or fields['MainPID']!=str(identity.pid)
                or not _matches_exec(fields['ExecStart'],self.expectation.runtime.steam_argv,identity.pid)
                or tuple(shlex.split(fields['Environment']))!=self.expectation.environment):
            raise ValueError('effective Steam configuration differs from expectation')
        ended=self._now()
        if ended<after:raise ValueError('observation clock reversed')
        return EffectiveSteamLaunch(identity,self.expectation.runtime.digest,before)
