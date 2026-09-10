"""Async task driver for the serialized Docked-iGPU watch lifecycle."""

from __future__ import annotations

import asyncio
import threading
from typing import Protocol

from ..application.docked_igpu_lifecycle import DockedIgpuLifecycleStatus


class DockedIgpuLifecyclePort(Protocol):
    def status(self) -> DockedIgpuLifecycleStatus: ...

    def tick(self) -> DockedIgpuLifecycleStatus: ...

    def acknowledge_action(self) -> bool: ...

    def close(self) -> DockedIgpuLifecycleStatus: ...


class DockedIgpuLifecycleScheduler:
    """Drive one lifecycle without owning transition approval or execution."""

    def __init__(self, lifecycle: DockedIgpuLifecyclePort) -> None:
        self._lifecycle = lifecycle
        self._latest = lifecycle.status()
        self._latest_lock = threading.Lock()
        self._wake = asyncio.Event()
        self._running = False

    def status(self) -> DockedIgpuLifecycleStatus:
        with self._latest_lock:
            return self._latest

    def wake(self) -> None:
        """Request one fresh tick after an external lifecycle state change."""

        self._wake.set()

    def acknowledge_action(self) -> bool:
        """Clear only the lifecycle's current Action Required state."""

        acknowledged = self._lifecycle.acknowledge_action()
        if acknowledged:
            self._set_latest(self._lifecycle.status())
        return acknowledged

    async def run(self) -> None:
        if self._running:
            raise RuntimeError("Docked-iGPU lifecycle scheduler is already running")
        self._running = True
        try:
            while True:
                self._wake.clear()
                status = await asyncio.to_thread(self._lifecycle.tick)
                self._set_latest(status)
                if status.poll_after_ms == 0:
                    await self._wake.wait()
                    continue
                try:
                    await asyncio.wait_for(
                        self._wake.wait(),
                        timeout=status.poll_after_ms / 1000,
                    )
                except asyncio.TimeoutError:
                    pass
        finally:
            try:
                status = await asyncio.to_thread(self._lifecycle.close)
                self._set_latest(status)
            finally:
                self._running = False

    def _set_latest(self, value: DockedIgpuLifecycleStatus) -> None:
        with self._latest_lock:
            self._latest = value
