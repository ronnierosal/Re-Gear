"""Read-only kernel topology invalidations, never identity or action authority.

One owning asyncio task calls start(), wait(timeout), and close() in finally.
Every wake requires fresh authoritative discovery; fallback polling is mandatory
because kernel notifications can be lost and do not cover game/session state.
"""

from __future__ import annotations

import asyncio
import math
import socket
import sys


MAX_DATAGRAM_BYTES = 8192
MAX_DRAIN_DATAGRAMS = 32
COALESCE_SECONDS = 0.1
_NETLINK_KOBJECT_UEVENT = 15
_ACTIONS = frozenset((b"add", b"remove", b"change", b"bind", b"unbind", b"move"))


def is_topology_invalidation(data: bytes) -> bool:
    """Accept bounded PCI/DRM/Thunderbolt events; retain no private fields."""
    if not data or len(data) > MAX_DATAGRAM_BYTES or not data.endswith(b"\0"):
        return False
    fields = data.split(b"\0")
    if len(fields) > 128:
        return False
    header = fields[0].split(b"@", 1)
    if len(header) != 2 or header[0] not in _ACTIONS or not header[1].startswith(b"/devices/"):
        return False
    values: dict[bytes, bytes] = {}
    for field in fields[1:-1]:
        key, separator, value = field.partition(b"=")
        if not separator or key in values:
            return False
        values[key] = value
    return (
        values.get(b"SUBSYSTEM") in (b"pci", b"drm", b"thunderbolt")
        and values.get(b"ACTION") == header[0]
        and values.get(b"DEVPATH") == header[1]
    )


class LinuxTopologyWakeup:
    """Single-consumer, no-background-task netlink listener with timed fallback."""

    def __init__(self) -> None:
        self._socket: socket.socket | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._reader_fd: int | None = None
        self._pending = asyncio.Event()
        self._pending_sources: set[str] = set()
        self.last_wake_source = "startup"
        self._started = False
        self._closed = False

    @property
    def available(self) -> bool:
        return self._socket is not None

    def invalidate(self) -> None:
        """Wake fresh observation after a local preference/acknowledgement change."""
        if not self._closed:
            self._pending_sources.add("local_change")
            self._pending.set()

    def start(self) -> bool:
        """Subscribe once; unsupported platforms/permissions use timed fallback."""
        if self._closed or self._started:
            return self.available
        self._started = True
        if sys.platform != "linux" or not hasattr(socket, "AF_NETLINK"):
            return False
        self._loop = asyncio.get_running_loop()
        try:
            self._socket = socket.socket(socket.AF_NETLINK, socket.SOCK_DGRAM, _NETLINK_KOBJECT_UEVENT)
            self._socket.setblocking(False)
            self._socket.bind((0, 1))  # Kernel multicast group; no outbound messages.
            fd = self._socket.fileno()
            self._loop.add_reader(fd, self._on_readable)
            self._reader_fd = fd
        except (OSError, NotImplementedError, AttributeError):
            self._release_socket()
        return self.available

    def _release_socket(self) -> None:
        if self._reader_fd is not None and self._loop is not None:
            self._loop.remove_reader(self._reader_fd)
            self._reader_fd = None
        if self._socket is not None:
            self._socket.close()
            self._socket = None

    def _on_readable(self) -> None:
        if self._socket is None:
            return
        for _ in range(MAX_DRAIN_DATAGRAMS):
            try:
                data, _, flags, address = self._socket.recvmsg(MAX_DATAGRAM_BYTES)
            except BlockingIOError:
                return
            except OSError:
                # Includes queue overflow: force one fresh scan, then fallback.
                self._release_socket()
                self._pending_sources.add("observer_degraded")
                self._pending.set()
                return
            if (
                isinstance(address, tuple)
                and len(address) == 2
                and address[0] == 0
                and not flags & getattr(socket, "MSG_TRUNC", 0x20)
                and is_topology_invalidation(data)
            ):
                self._pending_sources.add("kernel_event")
                self._pending.set()

    async def wait(self, timeout_seconds: float) -> bool:
        """Return True for a coalesced invalidation, False on fallback/close.

        Timeout must be finite and positive. Cancellation propagates; the owner
        must close in finally. No events or tasks are queued per datagram.
        """
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("fallback timeout must be finite and positive")
        if self._closed:
            self.last_wake_source = "closed"
            return False
        try:
            await asyncio.wait_for(self._pending.wait(), timeout_seconds)
        except asyncio.TimeoutError:
            self.last_wake_source = "poll_timer"
            return False
        if self._closed:
            self.last_wake_source = "closed"
            return False
        await asyncio.sleep(min(COALESCE_SECONDS, timeout_seconds))
        sources = self._pending_sources
        self.last_wake_source = (
            "closed" if self._closed else
            "observer_degraded" if "observer_degraded" in sources else
            "kernel_and_local" if len(sources) > 1 else
            next(iter(sources), "unknown")
        )
        self._pending_sources = set()
        self._pending.clear()
        return not self._closed

    def close(self) -> None:
        """Release the subscription and wake any pending waiter, idempotently."""
        self._closed = True
        self._release_socket()
        self._pending.set()
