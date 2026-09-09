"""Decide whether a game closed for a disconnect or a sleep may be reopened.

The flow that closes a game cannot be the flow that reopens it. Freeing the
eGPU means restarting the player's Steam session -- that is what releases the
device, and a running game is the case that makes it necessary -- so the panel
that asked the question is destroyed before the answer can be acted on. Sleep
is the same problem for a plainer reason: the machine is off in between.

So the intent to reopen is written down before the removal and read back
afterwards, by whatever is alive to read it. That makes it a small piece of
durable state that can outlive its purpose, and everything here is about not
letting it: a game relaunching on its own, minutes or reboots later, with no
one having asked for it, is worse than a game not relaunching at all.

Four facts have to hold, and each refuses on its own:

- **the same boot.** A reboot ends every claim this record had. The player
  turned the machine off; whatever they wanted before that is finished;
- **recently**, on a clock the record names. Never the wall clock, so an NTP
  step cannot make a stale intent look fresh; and which of the two depends on
  what the player was doing, because "five minutes" means something different
  either side of a suspend. See `RelaunchClock`;
- **the device is not disturbed.** A half-detached eGPU needs a person, not a
  game launching into it;
- **exactly once.** The record is consumed by reading it, so a relaunch that
  does happen cannot happen twice.

Pure. It launches nothing and stores nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


#: How long an intent stays honourable, in seconds since it was recorded.
#:
#: Long enough to cover a session restart and the panel coming back -- the
#: measured restart took a few seconds and Steam some seconds more -- and short
#: enough that a player who walked away does not return to a game that started
#: itself.
MAX_AGE_SECONDS = 300


class RelaunchClock(StrEnum):
    """Which clock an intent's age is measured on, and therefore what ages it.

    The two intents want different answers to the same question, so the record
    says which one it was written for rather than the reader guessing.

    A disconnect is over in seconds, and every second of it is spent with the
    handheld awake, so `BOOTTIME` -- which keeps counting through a suspend --
    is the honest measure. If the machine slept in the middle of one, something
    went wrong and the intent should expire.

    A sleep is the opposite. The whole point is that the device is off for a
    while, and the player who ticked "reopen afterwards" meant *when I come
    back*, not *within five minutes of pressing sleep*. `MONOTONIC` does not
    advance while suspended, so the budget is five minutes of the device being
    awake: a player who wakes it gets their game, and one who wakes it and
    wanders off does not come back to a game that started on its own.
    """

    BOOTTIME = "boottime"
    MONOTONIC = "monotonic"


@dataclass(frozen=True, slots=True)
class RelaunchIntent:
    """A recorded wish to reopen one game after a disconnect."""

    steam_app_id: str
    #: Which boot recorded it. An intent never crosses a reboot.
    boot_hash: str
    #: The reading of `clock` when it was recorded. Neither clock moves when
    #: the wall clock is corrected, so an NTP step cannot make a stale intent
    #: look fresh or a fresh one stale.
    recorded_boot_seconds: float
    #: Which clock that reading is on, and therefore what ages it.
    clock: RelaunchClock = RelaunchClock.BOOTTIME


class RelaunchVerdict(StrEnum):
    #: Reopen the game.
    RELAUNCH = "relaunch"
    #: Nothing was recorded.
    NOTHING_RECORDED = "nothing_recorded"
    #: Something was recorded but must not be acted on.
    REFUSED = "refused"


@dataclass(frozen=True, slots=True)
class RelaunchDecision:
    verdict: RelaunchVerdict
    code: str
    steam_app_id: str = ""

    @property
    def should_relaunch(self) -> bool:
        return self.verdict is RelaunchVerdict.RELAUNCH


def decide_relaunch(
    intent: RelaunchIntent | None,
    *,
    boot_hash: str,
    now_boot_seconds: float,
    device_disturbed: bool = False,
) -> RelaunchDecision:
    """Whether the recorded intent may be acted on now.

    A refusal is as final as it sounds: the caller discards the record either
    way, because an intent that could not be honoured this time is not one to
    keep trying.
    """

    if intent is None:
        return RelaunchDecision(
            RelaunchVerdict.NOTHING_RECORDED, "relaunch.nothing_recorded"
        )
    if device_disturbed:
        return RelaunchDecision(
            RelaunchVerdict.REFUSED, "relaunch.device_disturbed", intent.steam_app_id
        )
    if not boot_hash or intent.boot_hash != boot_hash:
        # Either the machine rebooted, or this boot cannot be identified. Both
        # mean the same thing: nothing here can be shown to be this session's.
        return RelaunchDecision(
            RelaunchVerdict.REFUSED, "relaunch.different_boot", intent.steam_app_id
        )
    # `now_boot_seconds` must be a reading of `intent.clock`. A caller mixing
    # the two would compare a suspend-excluding reading against a
    # suspend-including one and get an age that means nothing.
    age = now_boot_seconds - intent.recorded_boot_seconds
    if age < 0:
        # Recorded later than now, within one boot. Something is wrong with the
        # record or the clock, and neither is a reason to launch a game.
        return RelaunchDecision(
            RelaunchVerdict.REFUSED, "relaunch.recorded_in_the_future", intent.steam_app_id
        )
    if age > MAX_AGE_SECONDS:
        return RelaunchDecision(
            RelaunchVerdict.REFUSED, "relaunch.expired", intent.steam_app_id
        )
    return RelaunchDecision(
        RelaunchVerdict.RELAUNCH, "relaunch.approved", intent.steam_app_id
    )
