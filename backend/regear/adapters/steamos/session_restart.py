"""Perform an approved disconnect restart, and verify it by observation.

The live disconnect needs two kinds of restart: the session target, and the
audio holders the target does not reach. `regear.egpu_disconnect` prints the
commands and waits for an operator to run them, because `subprocess` is
confined to `regear.adapters.steamos.commands` and nothing there could restart
the audio units. That is workable at a terminal and cannot work behind an RPC,
which is what leaves the capability operator-only.

This performs them through the same fixed allow-list every other user-service
operation goes through. `UserServiceCommandRunner` builds its argv from a
constant suffix looked up by operation, so adding an operation adds one exact
command shape and no ability to run anything else. The units themselves were
already approved: `regear.domain.filter_arm_sequence.APPROVED_EXPLICIT_RESTARTS`
lists both audio units, so the domain had decided these may be restarted and
only the executor could not do it.

**A restart is not believed, it is checked.** `systemctl restart` returning
success means the unit was asked to restart, not that it let go of the eGPU.
So the command is followed by watching the holders the restart should clear,
and the step succeeds only when they are actually gone. That is the same
contract the operator tool satisfies by waiting for a human, and it is why a
unit that restarts without releasing reports failure rather than success.

Anything not in the allow-list is refused rather than improvised. An
unapproved holder is already refused upstream when the plan is composed; this
is the second place that holds, so a plan that somehow named an unapproved
unit could still not run it here.
"""

from __future__ import annotations

from typing import Callable

from ...domain.filter_arm_sequence import SESSION_TARGET, units_cleared_by
from ...ports.presentation_activation import (
    UserServiceCommandPort,
    UserServiceOperation,
)


#: The only units this may restart, and the exact operation each maps to.
#: Membership here is the executor's half of the approval; the domain's half is
#: `APPROVED_HOLDER_UNITS`, and both have to agree before anything runs.
APPROVED_RESTARTS: dict[str, UserServiceOperation] = {
    "wireplumber.service": UserServiceOperation.RESTART_WIREPLUMBER,
    "pipewire.service": UserServiceOperation.RESTART_PIPEWIRE,
    SESSION_TARGET: UserServiceOperation.RESTART_GAMESCOPE_SESSION,
}


def await_units_released(
    units: tuple[str, ...],
    observe: Callable[[], tuple[str, ...]],
    *,
    deadline: float,
    now: Callable[[], float],
    sleep: Callable[[float], None],
    interval: float = 2.0,
) -> bool:
    """Wait for every unit in `units` to stop holding the device.

    Succeeds on the fact the sequence depends on -- that the holders let go --
    rather than on a command having returned success, which is the weaker
    claim. An empty set passes immediately, because there is nothing to wait
    for.
    """
    if not units:
        return True
    wanted = set(units)
    while True:
        if not wanted & set(observe()):
            return True
        remaining = deadline - now()
        if remaining <= 0:
            return False
        sleep(max(0.0, min(interval, remaining)))


class SessionUnitRestart:
    """Restart one approved unit and report whether the device was released."""

    def __init__(
        self,
        *,
        commands: UserServiceCommandPort,
        uid: int,
        username: str,
        observe_holders: Callable[[], tuple[str, ...]],
        now: Callable[[], float],
        sleep: Callable[[float], None],
        timeout_seconds: float = 60.0,
    ) -> None:
        self._commands = commands
        self._uid = uid
        self._username = username
        self._observe = observe_holders
        self._now = now
        self._sleep = sleep
        self._timeout = timeout_seconds

    def restart(self, unit: str) -> bool:
        """Restart `unit`, then wait for what it should have released.

        Returns whether the holders are gone, which is what the arm sequence
        needs, and never whether the command was accepted.
        """
        operation = APPROVED_RESTARTS.get(unit)
        if operation is None:
            return False

        # Read the holders before restarting: afterwards the set has changed,
        # and what this must wait for is what the unit was holding when the
        # plan named it.
        expected = units_cleared_by(unit, tuple(self._observe()))
        result = self._commands.run(
            operation, uid=self._uid, username=self._username
        )
        if not result.ok:
            return False
        return await_units_released(
            expected,
            self._observe,
            deadline=self._now() + self._timeout,
            now=self._now,
            sleep=self._sleep,
        )
