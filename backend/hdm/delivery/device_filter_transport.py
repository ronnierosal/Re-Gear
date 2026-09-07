"""Bounded one-exchange transport; not a listener or launch authorization.

Peer UID is only transport authentication. Server callers must independently
bind PID/starttime/service and persist the one-shot grant before sending it.
No retry is safe after uncertain delivery. Production client path is fixed.
"""
from dataclasses import dataclass
import math
import socket
import struct
import sys
import time

from .device_filter_lifecycle import LaunchBinding
from .device_filter_protocol import (MAX_BYTES, FilterRequest, FilterGrant,
    encode_request, decode_request, encode_grant, decode_grant, grant_matches)

SOCKET_PATH = "/run/regear/device-filter/launch.sock"
MAX_WAIT = 5.0
_AF_UNIX = getattr(socket, "AF_UNIX", 1)


@dataclass(frozen=True)
class PeerCredentials:
    pid: int
    uid: int
    gid: int

    def __post_init__(self):
        if (type(self.pid) is not int or self.pid <= 0
                or any(type(value) is not int or value < 0 for value in (self.uid, self.gid))):
            raise ValueError("invalid peer identity")


def _remaining(connection, deadline, clock):
    now = clock()
    if (type(deadline) not in (int, float) or type(now) not in (int, float)
            or not math.isfinite(deadline) or not math.isfinite(now)
            or now < 0 or not 0 < deadline - now <= MAX_WAIT):
        raise TimeoutError("handshake deadline unavailable or expired")
    connection.settimeout(deadline - now)


def peer_identity(connection):
    # Numeric Linux UAPI options allow portable fake tests; production socket
    # creation still requires AF_UNIX/SOCK_SEQPACKET support on the host.
    if connection.family != _AF_UNIX or connection.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) != 5:
        raise ValueError("Unix seqpacket socket required")
    raw = connection.getsockopt(socket.SOL_SOCKET, 17, 12)  # SO_PEERCRED
    if type(raw) is not bytes or len(raw) != 12:
        raise ValueError("invalid peer credentials")
    return PeerCredentials(*struct.unpack("=iII", raw))


def _send(connection, raw, deadline, clock):
    _remaining(connection, deadline, clock)
    if connection.send(raw) != len(raw):
        raise OSError("incomplete handshake packet")


def _receive(connection, deadline, clock):
    _remaining(connection, deadline, clock)
    raw = connection.recv(MAX_BYTES + 1)
    _remaining(connection, deadline, clock)
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_BYTES:
        raise ValueError("invalid handshake packet length")
    return raw


def exchange_connected(connection, request, *, deadline, clock=time.monotonic):
    """One exchange on a caller-owned connected socket (also usable by fixtures)."""
    _remaining(connection, deadline, clock)
    if peer_identity(connection).uid != 0:
        raise ValueError("root handshake server required")
    _send(connection, encode_request(request), deadline, clock)
    grant = decode_grant(_receive(connection, deadline, clock))
    if not grant_matches(request, grant):
        raise ValueError("grant correlation mismatch")
    return grant


def request_grant(request, *, deadline, clock=time.monotonic, socket_factory=socket.socket):
    """Fixed production endpoint. Failure never retries or falls back to a grant."""
    if sys.platform != "linux":
        raise RuntimeError("Linux handshake transport required")
    with socket_factory(_AF_UNIX, 5) as connection:
        _remaining(connection, deadline, clock)
        connection.connect(SOCKET_PATH)
        return exchange_connected(connection, request, deadline=deadline, clock=clock)


def receive_request(connection, *, expected_uid, deadline, clock=time.monotonic):
    """Return transport evidence only, before independent service authentication."""
    if type(expected_uid) is not int or expected_uid <= 0:
        raise ValueError("trusted session UID required")
    _remaining(connection, deadline, clock)
    peer = peer_identity(connection)
    if peer.uid != expected_uid:
        raise ValueError("unexpected session peer")
    return peer, decode_request(_receive(connection, deadline, clock))


def send_grant(connection, request, binding, revision, *, deadline, clock=time.monotonic):
    """Caller must already have authenticated this socket and durably granted.

    Successful send is not an acknowledgement of receipt or launch execution.
    """
    _remaining(connection, deadline, clock)
    if type(request) is not FilterRequest or type(binding) is not LaunchBinding:
        raise ValueError("exact request and launch binding required")
    if (request.operation, request.unit, request.invocation) != (
            binding.operation, binding.unit, binding.invocation):
        raise ValueError("launch binding mismatch")
    peer = peer_identity(connection)
    if (peer.uid, peer.pid) != (binding.uid, binding.pid):
        raise ValueError("grant peer process mismatch")
    grant = FilterGrant(request.schema, request.operation, request.unit,
                        request.invocation, request.nonce, revision, "granted")
    _send(connection, encode_grant(grant), min(deadline, binding.deadline), clock)
    return True
