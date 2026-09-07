"""Inactive pre-native session observation for PREPARE_WITHHOLD only.

Independent intended configuration is never learned from live output. A match
does not approve native script resolution, execution, or launch. Existing unit
drop-ins (including drm_janitor) are neither changed nor implicitly accepted.
"""
from dataclasses import dataclass
from enum import Enum
import re
import shlex

from ..adapters.steamos.commands import UserServiceCommandRunner
from ..ports.presentation_activation import UserServiceOperation
from .device_filter_effective_launch import SteamLaunchExpectation,EffectiveSteamLaunchObserver,FIELDS,EMPTY,_matches_exec
from .device_filter_runtime_bundle import RuntimeBundle
from .device_filter_peer import WaitingPeerIdentity


class SessionEntryPurpose(Enum):
    PREPARE_WITHHOLD='prepare_withhold'


@dataclass(frozen=True)
class SessionEntryExpectation:
    runtime: RuntimeBundle
    environment: tuple[str,...]
    dropins: tuple[str,...]
    purpose: SessionEntryPurpose

    def __post_init__(self):
        # Reuse exact archive path and explicit environment validation only.
        SteamLaunchExpectation(self.runtime,self.environment)
        if (self.runtime.session_argv!=('/usr/bin/python3','-I',self.runtime.path,'session')
                or self.purpose is not SessionEntryPurpose.PREPARE_WITHHOLD
                or type(self.dropins) is not tuple or not 1<=len(self.dropins)<=16
                or any(type(path) is not str or re.fullmatch(
                    r'/(?:etc|usr/lib)/systemd/user/(?:gamescope-session\.service|service)\.d/[A-Za-z0-9_.-]+\.conf',path) is None
                    for path in self.dropins) or len(set(self.dropins))!=len(self.dropins)):
            raise ValueError('independent prepare-only session configuration required')


@dataclass(frozen=True)
class EffectiveSessionEntry:
    identity: WaitingPeerIdentity
    runtime_digest: str
    observed_at: float
    purpose: SessionEntryPurpose=SessionEntryPurpose.PREPARE_WITHHOLD
    native_execution_authorized: bool=False


class EffectiveSessionEntryObserver:
    def __init__(self,user,expectation,*,deadline,commands=None,clock=None):
        if type(expectation) is not SessionEntryExpectation:
            raise ValueError('independent session expectation required')
        self.user,self.expectation=user,expectation
        options=dict(deadline=deadline,commands=commands)
        if clock is not None:options['clock']=clock
        self._bounds=EffectiveSteamLaunchObserver(user,
            SteamLaunchExpectation(expectation.runtime,expectation.environment),**options)
        self.commands=self._bounds.commands

    def __call__(self,identity):
        if (type(identity) is not WaitingPeerIdentity or identity.unit!='gamescope-session.service'
                or identity.uid!=self.user.uid):raise ValueError('authenticated session entry required')
        before=self._bounds._now()
        result=self.commands.run(UserServiceOperation.OBSERVE_FILTER_SESSION_ENTRY,
            uid=self.user.uid,username=self.user.username,
            timeout_seconds=min(1,self._bounds.deadline-before))
        after=self._bounds._now()
        if after<before or result.ok is not True:raise ValueError('session query unavailable')
        raw=result.output
        if type(raw) is not str or not 0<len(raw)<=4096 or not raw.isascii():
            raise ValueError('bounded session properties required')
        fields={}
        for line in raw.splitlines():
            key,sep,value=line.partition('=')
            if not sep or key not in FIELDS or key in fields:raise ValueError('unexpected session property')
            fields[key]=value
        if (set(fields)!=FIELDS or fields['LoadState']!='loaded'
                or fields['FragmentPath']!='/usr/lib/systemd/user/gamescope-session.service'
                or tuple(shlex.split(fields['DropInPaths']))!=self.expectation.dropins
                or any(fields[key] for key in EMPTY)
                or fields['InvocationID']!=identity.invocation or fields['MainPID']!=str(identity.pid)
                or not _matches_exec(fields['ExecStart'],self.expectation.runtime.session_argv,identity.pid)
                or tuple(shlex.split(fields['Environment']))!=self.expectation.environment):
            raise ValueError('session entry differs from independent expectation')
        if self._bounds._now()<after:raise ValueError('observation clock reversed')
        return EffectiveSessionEntry(identity,self.expectation.runtime.digest,before)
