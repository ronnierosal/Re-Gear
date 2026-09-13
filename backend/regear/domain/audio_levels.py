"""Read and validate audio levels without ever inventing one.

The Command Center's utility rail offers a volume slider and a mic-mute
button. Both are read from and written to WirePlumber through `wpctl`, which
Re-Gear already runs for audio device selection. This module is the pure half:
it turns command output into a reading, decides whether a requested level may
be dispatched, and decides whether a write actually took effect.

Three rules, and each exists because the alternative lies to a player.

- **Unparsed output is unknown, never a default.** `wpctl`'s output format is
  not a stable contract; it is a human-readable CLI. A parser that fell back to
  0 on anything it did not recognise would render a muted-looking slider for a
  device playing at full volume, and a player would reach for hardware keys
  that then jump from an imagined zero. Anything not matched exactly is
  `unknown` and the control stays unavailable.

- **A write is not a reading.** `wpctl set-volume` exiting zero means the
  command was accepted, not that the sink moved -- a node can be removed, a
  profile can change under the request, and a clamped device can accept 90 and
  sit at 100. So a set is reported successful only after re-reading and seeing
  the value, the same shape `application.tdp_control` already uses for power
  limits. Unverified is its own outcome, distinct from failure.

- **Over-amplification is reported, not hidden.** PipeWire allows volumes above
  1.0, and SteamOS exposes that. A reading of 1.4 is a real state a player can
  be in and is worth seeing; clamping the *reading* to 100 would conceal why
  something sounds distorted. Writes are a different matter -- those stay
  inside the supported range, because nothing in Re-Gear should be the thing
  that pushed a device into distortion.

Nothing here performs I/O, and nothing here decides whether the capability is
supported at all; that is the application's job, since absence of a port is not
a property of a number.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

#: `wpctl get-volume` prints e.g. "Volume: 0.65" or "Volume: 0.65 [MUTED]".
#: Anchored, and the value must be a plain decimal: a parser that accepted
#: trailing text would happily read "Volume: 0.65 of 1.00" as 65%.
_VOLUME = re.compile(r"^\s*Volume:\s*(\d+(?:\.\d+)?)\s*(\[MUTED\])?\s*$")

#: Highest volume a Re-Gear write may request. Reading above this is allowed
#: and reported; writing above it is not.
MAX_SETTABLE_PERCENT = 100
MIN_SETTABLE_PERCENT = 0

#: `wpctl` stores a float and rounds on display, so a write of 65 can read back
#: as 0.65 or 0.649999. One percentage point absorbs that without absorbing a
#: real disagreement -- a device that clamped 90 to 100 is still caught.
READBACK_TOLERANCE_PERCENT = 1


@dataclass(frozen=True)
class AudioLevel:
    """One observed level. `known` false means no reading, never a zero."""

    known: bool
    percent: int | None = None
    muted: bool | None = None
    #: Why a reading is absent. Empty when known.
    code: str = ""

    @property
    def over_amplified(self) -> bool:
        return self.known and self.percent is not None and self.percent > MAX_SETTABLE_PERCENT


UNKNOWN_LEVEL = AudioLevel(False, code="audio_levels.unreadable")


def parse_level(output: str | None) -> AudioLevel:
    """Turn one `wpctl get-volume` line into a reading.

    Absent, empty, malformed or multi-line output is unknown. Multi-line is
    rejected rather than scanned for a match, because a command that printed a
    warning above its answer is a command whose answer is not trustworthy.
    """
    if not isinstance(output, str):
        return UNKNOWN_LEVEL
    stripped = output.strip()
    if not stripped or "\n" in stripped:
        return UNKNOWN_LEVEL
    match = _VOLUME.match(stripped)
    if match is None:
        return UNKNOWN_LEVEL
    try:
        value = float(match.group(1))
    except ValueError:  # pragma: no cover - the pattern already constrains this
        return UNKNOWN_LEVEL
    # A negative volume is not expressible by the pattern; an absurd one is.
    # Treat anything beyond a plausible ceiling as a parse failure rather than
    # reporting a number nobody can act on.
    if value > 10:
        return UNKNOWN_LEVEL
    return AudioLevel(True, percent=round(value * 100), muted=match.group(2) is not None)


def settable_percent(requested: object) -> int | None:
    """The percent this may dispatch, or None if it may not.

    Rejects non-integers outright. A float would mean deciding how to round
    someone's input, and a slider that silently moved to a different value than
    it showed is worse than one that refused.
    """
    if isinstance(requested, bool) or not isinstance(requested, int):
        return None
    if requested < MIN_SETTABLE_PERCENT or requested > MAX_SETTABLE_PERCENT:
        return None
    return requested


def readback_verified(requested: int, observed: AudioLevel) -> bool:
    """Did the device actually take the value it was asked for?

    An unknown reading is never verification. Neither is a value outside the
    tolerance, which is exactly the clamped-device case worth surfacing.
    """
    if not observed.known or observed.percent is None:
        return False
    return abs(observed.percent - requested) <= READBACK_TOLERANCE_PERCENT


def mute_verified(requested: bool, observed: AudioLevel) -> bool:
    """Did the mute state actually change? Unknown is never a yes."""
    if not observed.known or observed.muted is None:
        return False
    return observed.muted is requested
