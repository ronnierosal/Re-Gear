"""Read-only observation and bounded time adapters for transition runtime."""

from __future__ import annotations

import hashlib
import json
import time

from ..domain.serialization import snapshot_to_dict
from ..ports.discovery import DiscoveryPort
from ..ports.transition import VersionedObservation


class SnapshotTransitionObservationAdapter:
    def __init__(self, discovery: DiscoveryPort) -> None:
        self._discovery = discovery

    def observe(self) -> VersionedObservation:
        return versioned_snapshot_observation(self._discovery.collect_snapshot())


def versioned_snapshot_observation(snapshot) -> VersionedObservation:
    """Bind one already-collected snapshot without triggering another scan."""
    complete = snapshot_to_dict(snapshot)
    semantic = dict(complete)
    semantic.pop("observed_at", None)
    encoded = json.dumps(
        semantic,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    sample = json.dumps(
        complete,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return VersionedObservation(
        hashlib.sha256(encoded).hexdigest(),
        snapshot,
        hashlib.sha256(sample).hexdigest(),
    )


class SystemMonotonicClock:
    @staticmethod
    def now_ms() -> int:
        return time.monotonic_ns() // 1_000_000


class BoundedDeadlineWaiter:
    MAX_WAIT_MS = 250

    @classmethod
    def wait_ms(cls, milliseconds: int) -> None:
        if milliseconds <= 0 or milliseconds > cls.MAX_WAIT_MS:
            raise ValueError("transition polling wait is outside its bound")
        time.sleep(milliseconds / 1000)
