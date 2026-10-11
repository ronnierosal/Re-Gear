"""Provider-neutral physical-output evidence. No discovery or dispatch authority.

M1 must establish who can issue these observations, generation/sequence semantics,
exact mode IDs and readback, admission and qualified rollback. Booleans here are
injected evidence, never inferred from platform names or command acceptance.
"""
from dataclasses import dataclass
from fractions import Fraction
from math import isfinite


def identity(value: object) -> bool:
    return isinstance(value, str) and 0 < len(value) <= 256 and value == value.strip()


def number(value: object) -> bool:
    return type(value) in (int, float) and isfinite(value) and value >= 0


@dataclass(frozen=True)
class Binding:
    output: str
    session: str
    provider: str
    generation: int

    def __post_init__(self):
        if not all(identity(v) for v in (self.output, self.session, self.provider)) or type(self.generation) is not int or self.generation < 0:
            raise ValueError('binding.invalid')


@dataclass(frozen=True)
class Mode:
    identity: str
    width: int
    height: int
    hz_numerator: int
    hz_denominator: int

    def __post_init__(self):
        if not identity(self.identity) or any(type(v) is not int or v <= 0 for v in (self.width, self.height, self.hz_numerator, self.hz_denominator)):
            raise ValueError('mode.invalid')

    @property
    def hz(self) -> Fraction:
        return Fraction(self.hz_numerator, self.hz_denominator)

    @property
    def resolution(self) -> tuple[int, int]:
        return self.width, self.height


@dataclass(frozen=True)
class Observation:
    binding: Binding
    modes: tuple[Mode, ...]
    current: Mode | None
    observed_at: float
    sequence: int
    available: bool | None
    game_idle: bool | None
    lifecycle_idle: bool | None
    admitted: bool | None
    rollback_qualified: bool | None = None

    def validate(self, now: float, max_age: float = 2) -> None:
        if not isinstance(self.binding, Binding) or not number(now) or not number(self.observed_at) or not number(max_age) or not 0 <= now - self.observed_at <= max_age:
            raise ValueError('evidence.stale_or_invalid')
        if type(self.sequence) is not int or self.sequence < 0 or any(v is not True for v in (self.available, self.game_idle, self.lifecycle_idle, self.admitted)):
            raise ValueError('evidence.unavailable_or_denied')
        if type(self.modes) is not tuple or not 0 < len(self.modes) <= 512 or any(not isinstance(m, Mode) for m in self.modes):
            raise ValueError('modes.invalid')
        ids = [m.identity for m in self.modes]
        tuples = [(m.width, m.height, m.hz) for m in self.modes]
        if len(set(ids)) != len(ids) or len(set(tuples)) != len(tuples) or self.current not in self.modes:
            raise ValueError('modes.ambiguous_or_current_unknown')


def cycle(evidence: Observation, axis: str, now: float) -> Mode:
    """Cycle supplied complete tuples; never combine independent dimensions/Hz."""
    evidence.validate(now)
    current = evidence.current
    if axis == 'refresh':
        modes = sorted((m for m in evidence.modes if m.resolution == current.resolution), key=lambda m: (m.hz, m.identity))
        if len(modes) < 2:
            raise ValueError('cycle.no_alternative')
        return modes[(modes.index(current) + 1) % len(modes)]
    if axis == 'resolution':
        resolutions = sorted({m.resolution for m in evidence.modes})
        if len(resolutions) < 2:
            raise ValueError('cycle.no_alternative')
        target = resolutions[(resolutions.index(current.resolution) + 1) % len(resolutions)]
        return min((m for m in evidence.modes if m.resolution == target), key=lambda m: (m.hz != current.hz, m.hz, m.identity))
    raise ValueError('cycle.axis_invalid')
