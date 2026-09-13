"""Read kernel suspend counters without requesting sleep or changing devices.

API documentation consultation (no copied implementation):
https://github.com/torvalds/linux/blob/master/Documentation/ABI/testing/sysfs-power
The success/fail counters describe kernel attempts, not physical sleep duration,
device health, or attribution to a particular power request. Establish a baseline
before submission; lifecycle ownership and restoration belong to the caller.
"""
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Callable

from .owner_identity import read_boot_hash


@dataclass(frozen=True)
class SuspendEvidence:
    boot_hash: str
    success: int
    fail: int

    def __post_init__(self):
        if (type(self.boot_hash) is not str
                or re.fullmatch('[0-9a-f]{64}', self.boot_hash) is None
                or any(type(v) is not int or v < 0 for v in (self.success, self.fail))):
            raise ValueError('suspend_observer.invalid_evidence')


def classify_suspend(baseline: SuspendEvidence | None,
                     current: SuspendEvidence | None) -> str:
    """Return success, fail, unchanged, or unresolved; never infer missing data."""
    if (type(baseline) is not SuspendEvidence or type(current) is not SuspendEvidence
            or baseline.boot_hash != current.boot_hash
            or current.success < baseline.success or current.fail < baseline.fail):
        return 'unresolved'
    success = current.success - baseline.success
    failure = current.fail - baseline.fail
    if success and failure:
        return 'unresolved'
    if success:
        return 'success'
    if failure:
        return 'fail'
    return 'unchanged'


class SuspendObserver:
    def __init__(self, sysroot: Path = Path('/sys'), *,
                 boot_reader: Callable[[], str] = read_boot_hash):
        self._root = Path(sysroot) / 'power' / 'suspend_stats'
        self._boot = boot_reader

    def _counter(self, name: str) -> int:
        with (self._root / name).open('r', encoding='ascii') as source:
            value = source.read(129)
        if len(value) > 128 or re.fullmatch(r'[0-9]+\n?', value) is None:
            raise ValueError('suspend_observer.invalid_counter')
        return int(value)

    def read(self) -> SuspendEvidence | None:
        """Two matching bounded reads avoid mixing counters across a transition."""
        try:
            boot = self._boot()
            first = SuspendEvidence(boot, self._counter('success'), self._counter('fail'))
            second = SuspendEvidence(self._boot(), self._counter('success'), self._counter('fail'))
            if first != second or self._boot() != boot:
                return None
            return second
        except (OSError, ValueError, UnicodeError):
            return None

    def classify(self, baseline: SuspendEvidence | None) -> str:
        return classify_suspend(baseline, self.read())
