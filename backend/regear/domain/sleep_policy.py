"""Pure lifecycle policy for the G1 sleep-inhibitor lease."""

from __future__ import annotations

from .models import EgpuPresence, SleepGuardAction


def decide_sleep_guard(presence: EgpuPresence) -> SleepGuardAction:
    if presence is EgpuPresence.PRESENT:
        return SleepGuardAction.ACQUIRE
    if presence is EgpuPresence.ABSENT:
        return SleepGuardAction.RELEASE
    return SleepGuardAction.HOLD
