"""A disconnect asked for as a sleep, waiting for the panel that survives it.

Freeing the eGPU restarts the Steam session whenever a session-reached unit
held it, and that restart destroys the panel that pressed "Disconnect and
sleep" before its sleep step can run. So the wish to sleep is written down with
the disconnect, the way the relaunch wish is, and the panel that comes up
afterwards claims it, waits for the same guard evidence the in-panel path
waits for, and asks Steam to sleep. This module decides whether a claimed
record may still be acted on. It sleeps nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

#: Awake seconds. The panel is back within seconds of the restart; a player
#: who walked away must not come back to a handheld that sleeps itself.
MAX_AGE_SECONDS = 300.0
#: How far the two clocks may drift apart before it counts as a suspend.
SUSPEND_DRIFT_SECONDS = 2.0


@dataclass(frozen=True, slots=True)
class PendingSleep:
    """One recorded wish to sleep once the disconnect that carried it is done."""

    #: Which boot recorded it. A continuation never crosses a reboot.
    boot_hash: str
    #: CLOCK_MONOTONIC at the record: stops while suspended, so it ages the
    #: record in awake time.
    recorded_monotonic: float
    #: CLOCK_BOOTTIME at the record: keeps counting through a suspend, so the
    #: gap between the two says whether the machine has slept since.
    recorded_boottime: float


class SleepContinuationVerdict(StrEnum):
    CONTINUE = "continue"
    NOTHING_RECORDED = "nothing_recorded"
    REFUSED = "refused"


@dataclass(frozen=True, slots=True)
class SleepContinuationDecision:
    verdict: SleepContinuationVerdict
    code: str

    @property
    def should_sleep(self) -> bool:
        return self.verdict is SleepContinuationVerdict.CONTINUE


def decide_sleep_continuation(
    record: PendingSleep | None,
    *,
    boot_hash: str,
    now_monotonic: float,
    now_boottime: float,
) -> SleepContinuationDecision:
    """Whether a claimed record may be acted on now.

    A refusal is final: the caller has already consumed the record, because a
    continuation that could not be honoured this time is not one to keep
    offering to every later panel.
    """
    if record is None:
        return SleepContinuationDecision(
            SleepContinuationVerdict.NOTHING_RECORDED, "sleep_continuation.nothing_recorded"
        )
    if not boot_hash or record.boot_hash != boot_hash:
        return SleepContinuationDecision(
            SleepContinuationVerdict.REFUSED, "sleep_continuation.different_boot"
        )
    age = now_monotonic - record.recorded_monotonic
    if age < 0 or age > MAX_AGE_SECONDS:
        return SleepContinuationDecision(
            SleepContinuationVerdict.REFUSED, "sleep_continuation.expired"
        )
    # The gap between the clocks grows only while the machine is suspended. A
    # gap that grew since the record was written means the handheld already
    # slept -- by the player's own hand or otherwise -- and sleeping it again
    # the moment it wakes is not what was asked for.
    drift = (now_boottime - now_monotonic) - (record.recorded_boottime - record.recorded_monotonic)
    if drift > SUSPEND_DRIFT_SECONDS:
        return SleepContinuationDecision(
            SleepContinuationVerdict.REFUSED, "sleep_continuation.slept_since"
        )
    return SleepContinuationDecision(
        SleepContinuationVerdict.CONTINUE, "sleep_continuation.pending"
    )
