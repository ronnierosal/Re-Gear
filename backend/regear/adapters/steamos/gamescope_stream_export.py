"""Read only Gamescope's private version-1 PipeWire node advertisement.

Wire signatures derive from Valve's gamescope-pipewire.xml at revision
05949f8149bb5d16b006624d319a76e2433caf4c; see THIRD_PARTY_NOTICES.md.
Reuses the existing peer-checked, bounded Wayland transport without modifying
the performance reader. This obtains an export ID, never frames or a DRM lease.
No production composition, capture or display mutation is provided here.
"""
from dataclasses import dataclass
import math
import re
import socket
import struct
import time

from .gamescope_performance import (
    PerformanceTarget, _connect, _global, _same_process, _string, _uint, _Wire,
)


_INTERFACE = "gamescope_pipewire"
_SOCKET_NAME = re.compile(r"(?:gamescope|wayland)-[0-9]{1,4}\Z")
_CODES = frozenset({"export.target_invalid", "export.context_changed",
                    "export.protocol_unavailable", "export.unavailable",
                    "export.timeout", "export.observed"})


@dataclass(frozen=True, slots=True)
class StreamExportReading:
    code: str
    context_key: str = ""
    node_id: int | None = None
    received_at_ms: int | None = None

    def to_payload(self):
        code = self.code if type(self.code) is str and self.code in _CODES else "export.unavailable"
        valid = (code == "export.observed" and type(self.node_id) is int
                 and 0 < self.node_id < 0xFFFFFFFF and bool(self.context_key)
                 and type(self.received_at_ms) is int and self.received_at_ms >= 0)
        return {"code": code if code != "export.observed" or valid else "export.unavailable",
                "export_observed": valid, "presenter_supported": False,
                "game_renderer_verified": False, "frame_delivery_verified": False,
                "drm_lease_verified": False}


def _target_allowed(target):
    return (type(target) is PerformanceTarget
            and target.socket_path.parent.as_posix() == f"/run/user/{target.uid}"
            and _SOCKET_NAME.fullmatch(target.socket_path.name) is not None)


def _peer_matches(stream, target):
    if not hasattr(socket, "SO_PEERCRED"):
        return False
    pid, uid, _ = struct.unpack("=iii", stream.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
    return pid == target.compositor_pid and uid == target.uid


class GamescopeStreamExportReader:
    def __init__(self, *, clock=time.monotonic, connect=_connect,
                 same_process=_same_process, timeout_seconds=0.5):
        if (type(timeout_seconds) not in (int, float)
                or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 2):
            raise ValueError("Export query deadline is invalid")
        self._clock, self._connect, self._same_process = clock, connect, same_process
        self._timeout = timeout_seconds

    def _now(self):
        now = self._clock()
        if type(now) not in (int, float) or not math.isfinite(now) or now < 0:
            raise ValueError("Invalid monotonic sample")
        return now

    def observe(self, target):
        try:
            return self._observe_once(target)
        except OSError:
            # close() runs after the inner result is formed. A transport cleanup
            # failure must not escape with raw diagnostic text or report success.
            return StreamExportReading("export.unavailable")

    def _observe_once(self, target):
        stream = None
        try:
            if not _target_allowed(target):
                return StreamExportReading("export.target_invalid")
            deadline = self._now() + self._timeout
            if self._same_process(target) is not True:
                return StreamExportReading("export.context_changed")
            remaining = deadline - self._now()
            if remaining <= 0:
                raise TimeoutError
            stream = self._connect(target, remaining)
            if not _peer_matches(stream, target):
                return StreamExportReading("export.context_changed")
            wire = _Wire(stream, self._now, deadline)
            wire.send(1, 1, _uint(2))  # wl_display.get_registry
            wire.send(1, 0, _uint(3))  # wl_display.sync
            advertised, active, candidates = set(), set(), {}
            export_globals = set()
            deleted = set()
            initial_sync_done = False

            def registry_event(obj, opcode, data):
                if obj == 2 and opcode == 0:
                    name, interface, version = _global(data)
                    if name == 0 or name in advertised or version == 0:
                        raise ValueError("Invalid or reused registry identity")
                    advertised.add(name)
                    active.add(name)
                    if interface == _INTERFACE:
                        export_globals.add(name)
                        candidates[name] = version
                    return True
                if obj == 2 and opcode == 1 and len(data) == 4:
                    name = struct.unpack("=I", data)[0]
                    if name not in active:
                        raise ValueError("Unknown registry removal")
                    active.remove(name)
                    candidates.pop(name, None)
                    return True
                if obj == 1 and opcode == 1 and len(data) == 4:
                    identity = struct.unpack("=I", data)[0]
                    if identity != 3 or identity in deleted or not initial_sync_done:
                        raise ValueError("Unexpected object retirement")
                    deleted.add(identity)
                    return True
                return False

            while True:
                obj, opcode, data = wire.event()
                if obj == 3 and opcode == 0 and len(data) == 4:
                    initial_sync_done = True
                    break
                if not registry_event(obj, opcode, data):
                    raise ValueError("Unexpected registry event")
            if len(export_globals) != 1 or len(candidates) != 1 or next(iter(candidates.values())) != 1:
                return StreamExportReading("export.protocol_unavailable")
            name = next(iter(candidates))
            wire.send(2, 0, _uint(name) + _string(_INTERFACE) + _uint(1, 4))
            wire.send(1, 0, _uint(5))
            node_id = None
            while True:
                obj, opcode, data = wire.event()
                if obj == 5 and opcode == 0 and len(data) == 4:
                    break
                if obj == 4 and opcode == 0:
                    if len(data) != 4 or node_id is not None:
                        raise ValueError("Invalid or duplicate export")
                    node_id = struct.unpack("=I", data)[0]
                    if not 0 < node_id < 0xFFFFFFFF:
                        raise ValueError("Unavailable stream node")
                elif not registry_event(obj, opcode, data):
                    raise ValueError("Unexpected export event")
                if len(export_globals) != 1 or len(candidates) != 1 or candidates.get(name) != 1:
                    return StreamExportReading("export.protocol_unavailable")
            if node_id is None:
                return StreamExportReading("export.protocol_unavailable")
            if self._same_process(target) is not True or not _peer_matches(stream, target):
                return StreamExportReading("export.context_changed")
            received = self._now()
            if received >= deadline:
                raise TimeoutError
            return StreamExportReading("export.observed", target.context_key,
                                       node_id, int(received * 1000))
        except TimeoutError:
            return StreamExportReading("export.timeout")
        except (OSError, ValueError, TypeError, AttributeError, struct.error):
            return StreamExportReading("export.unavailable")
        finally:
            if stream is not None:
                stream.close()
