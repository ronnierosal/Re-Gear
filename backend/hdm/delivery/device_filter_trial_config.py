"""Render the designated prepare-only trial drop-ins; no writes or activation.

Only ExecStart is reset. Native hooks, environment files, and unrelated drop-ins
remain untouched. Independently supplied expectations can therefore still fail
against unsupported effective properties; rendering does not approve a session.
"""
from dataclasses import dataclass
import re

from ..ports.presentation_activation import GamescopeUserContext

from .device_filter_dropin_store import NAME, UNITS
from .device_filter_effective_launch import SteamLaunchExpectation
from .device_filter_runtime_bundle import RuntimeBundle
from .device_filter_runtime_store import _validate
from .device_filter_session_entry import SessionEntryExpectation, SessionEntryPurpose

def _state_assignment(user):
    if (type(user) is not GamescopeUserContext or type(user.uid) is not int or user.uid <= 0
            or type(user.gid) is not int or user.gid < 0):
        raise ValueError('independently resolved user required')
    home = user.home.as_posix()
    if (re.fullmatch(r'/[A-Za-z0-9_.@+/-]+', home) is None
            or any(part in ('', '.', '..') for part in home.split('/')[1:])):
        raise ValueError('safe absolute user home required')
    return 'HDM_STATE_ROOT=' + home + '/.local/share/handheld-dock-mode'



@dataclass(frozen=True)
class TrialDropin:
    unit: str
    path: str
    content: bytes


def render_trial_dropin(runtime, unit, *, user):
    """Produce only a fixed runtime command and the existing state-root setting."""
    if type(runtime) is not RuntimeBundle or unit not in UNITS:
        raise ValueError('fixed runtime unit and state root required')
    _validate(runtime)
    state_assignment = _state_assignment(user)
    argv = runtime.session_argv if unit == 'gamescope-session.service' else runtime.steam_argv
    # Validation above restricts every argument to fixed ASCII tokens and a hex
    # digest. No systemd specifier, variable, shell command, or escape is allowed.
    command = ' '.join('"' + argument + '"' for argument in argv)
    content = ('[Service]\nExecStart=\nExecStart=' + command + '\n'
               'Environment="' + state_assignment + '"\n').encode('ascii')
    return TrialDropin(unit, '/etc/systemd/user/' + unit + '.d/' + NAME, content)


def session_trial_expectation(runtime, *, existing_dropins, existing_environment,
                              user):
    """Compose an independent expectation without discarding native drop-ins.

    Inputs must come from reviewed intended configuration, not a live query
    promoted into authority. Existing per-user paths remain unsupported by the
    session observer and are explicitly rejected instead of silently excluded.
    """
    rendered = render_trial_dropin(runtime, 'gamescope-session.service', user=user)
    state_assignment = _state_assignment(user)
    SteamLaunchExpectation(runtime, existing_environment)
    if type(existing_dropins) is not tuple:
        raise ValueError('explicit existing root drop-ins required')
    # Validate native paths before combining; an empty set is valid input only.
    if existing_dropins:
        SessionEntryExpectation(runtime, existing_environment, existing_dropins,
                                SessionEntryPurpose.PREPARE_WITHHOLD)
    dropins = tuple(path for path in existing_dropins if path != rendered.path) + (rendered.path,)
    names = tuple(path.rsplit('/', 1)[-1] for path in dropins)
    if len(set(names)) != len(names):
        raise ValueError('ambiguous drop-in basename precedence')
    dropins = tuple(sorted(dropins, key=lambda path: path.rsplit('/', 1)[-1]))
    environment = tuple(state_assignment if item.startswith('HDM_STATE_ROOT=') else item
                        for item in existing_environment)
    if not any(item.startswith('HDM_STATE_ROOT=') for item in existing_environment):
        environment += (state_assignment,)
    return SessionEntryExpectation(runtime, environment, dropins,
                                   SessionEntryPurpose.PREPARE_WITHHOLD)
