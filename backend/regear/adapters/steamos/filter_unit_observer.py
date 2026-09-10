"""Bounded read-only identity for the two supervised filter launch services."""
import math
import time

from ...ports.presentation_activation import UserServiceOperation
from .commands import UserServiceCommandRunner


class FilterUnitObserver:
    OPERATIONS = {
        "gamescope-session.service": UserServiceOperation.OBSERVE_FILTER_GAMESCOPE,
        "steam-launcher.service": UserServiceOperation.OBSERVE_FILTER_STEAM,
    }
    FIELDS = frozenset(("MainPID", "InvocationID", "ActiveState", "ControlGroup"))

    def __init__(self, user, *, deadline, commands=None, clock=time.monotonic):
        # User must come from the existing authenticated Gamescope-user resolver.
        self.user, self.deadline, self.clock = user, deadline, clock
        self.commands = commands if commands is not None else UserServiceCommandRunner(timeout_seconds=1.0)

    def __call__(self, unit):
        if type(unit) is not str or unit not in self.OPERATIONS:
            raise ValueError("unapproved launch observation")
        now = self.clock()
        if (type(self.deadline) not in (int, float) or not math.isfinite(self.deadline)
                or type(now) not in (int, float) or not math.isfinite(now)
                or now < 0 or not 0 < self.deadline - now <= 5):
            raise ValueError("launch observation deadline expired")
        result = self.commands.run(self.OPERATIONS[unit], uid=self.user.uid,
            username=self.user.username, timeout_seconds=min(1.0, self.deadline - now))
        after = self.clock()
        if (type(after) not in (int, float) or not math.isfinite(after) or after < now or after >= self.deadline):
            raise ValueError("launch observation expired during command")
        output = result.output
        if result.ok is not True or type(output) is not str or not 0 < len(output) <= 2048 or not output.isascii():
            raise ValueError("launch service observation unavailable")
        fields = {}
        for line in output.splitlines():
            key, separator, value = line.partition("=")
            if not separator or key not in self.FIELDS or key in fields:
                raise ValueError("malformed launch service properties")
            fields[key] = value
        if set(fields) != self.FIELDS:
            raise ValueError("incomplete launch service properties")
        return fields
