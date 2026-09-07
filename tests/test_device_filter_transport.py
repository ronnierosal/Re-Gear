from dataclasses import asdict, replace
import os
import socket
import struct
import sys
import unittest
from unittest.mock import patch

from backend.hdm.delivery import device_filter_transport as transport
from backend.hdm.delivery.device_filter_protocol import FilterRequest, FilterGrant, encode_request, encode_grant
from backend.hdm.delivery.device_filter_lifecycle import LaunchBinding


class FakeSocket:
    family = transport._AF_UNIX
    kind = 5
    uid = 0
    short = False

    def __init__(self, incoming=b""):
        self.incoming, self.sent, self.timeouts = incoming, [], []
        self.closed = False

    def getsockopt(self, level, option, length=None):
        return self.kind if option == socket.SO_TYPE else struct.pack("=iII", 50, self.uid, 1000)

    def settimeout(self, value):
        self.timeouts.append(value)

    def send(self, raw):
        self.sent.append(raw)
        return len(raw) - int(self.short)

    def recv(self, maximum):
        assert maximum == 2049
        return self.incoming

    def connect(self, path):
        self.path = path

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.closed = True


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.request = FilterRequest(1, "trial", "gamescope-session.service", "a" * 32, "b" * 64)
        self.grant = FilterGrant(**asdict(self.request), revision=3, status="granted")
        self.connection = FakeSocket(encode_grant(self.grant))
        self.binding = LaunchBinding("c" * 64, "trial", self.request.unit, "a" * 32,
                                     1000, 50, 70, 20, 30, "d" * 64, 15)

    def exchange(self):
        return transport.exchange_connected(self.connection, self.request, deadline=14, clock=lambda: 10)

    def test_single_exchange(self):
        self.assertEqual(self.exchange(), self.grant)
        self.assertEqual(self.connection.sent, [encode_request(self.request)])

    def test_wrong_server_or_socket_fails_before_send(self):
        for field, value in (("uid", 1000), ("kind", 1), ("family", socket.AF_INET)):
            self.connection = FakeSocket()
            setattr(self.connection, field, value)
            with self.assertRaises(ValueError):
                self.exchange()
            self.assertEqual(self.connection.sent, [])

    def test_packet_length_correlation_and_short_send(self):
        for raw in (b"", bytes(2049), encode_grant(replace(self.grant, nonce="e" * 64))):
            self.connection.incoming = raw
            with self.assertRaises(ValueError):
                self.exchange()
        self.connection.short = True
        self.connection.sent.clear()
        with self.assertRaises(OSError):
            self.exchange()
        self.assertEqual(len(self.connection.sent), 1)

    def test_absolute_deadline_checked_after_receive(self):
        times = iter((10, 11, 12, 14))
        with self.assertRaises(TimeoutError):
            transport.exchange_connected(self.connection, self.request, deadline=14, clock=lambda: next(times))
        self.assertEqual(self.connection.timeouts, [4, 3, 2])
        for deadline in (True, 10, 16, float("nan")):
            with self.assertRaises(TimeoutError):
                transport.exchange_connected(self.connection, self.request, deadline=deadline, clock=lambda: 10)

    def test_fixed_production_endpoint_and_close(self):
        def factory(family, kind):
            self.assertEqual((family, kind), (transport._AF_UNIX, 5))
            return self.connection
        with patch.object(transport.sys, "platform", "linux"):
            transport.request_grant(self.request, deadline=14, clock=lambda: 10, socket_factory=factory)
        self.assertEqual(self.connection.path, "/run/regear/device-filter/launch.sock")
        self.assertTrue(self.connection.closed)

    def test_server_receive_and_binding_check(self):
        self.connection.uid = 1000
        self.connection.incoming = encode_request(self.request)
        peer, request = transport.receive_request(self.connection, expected_uid=1000, deadline=14, clock=lambda: 10)
        self.assertEqual(peer, transport.PeerCredentials(50, 1000, 1000))
        self.assertEqual(request, self.request)
        self.assertIs(transport.send_grant(self.connection, request, self.binding, 3, deadline=14, clock=lambda: 10), True)
        self.assertEqual(self.connection.sent, [encode_grant(self.grant)])
        with self.assertRaises(ValueError):
            transport.send_grant(self.connection, request, replace(self.binding, invocation="e" * 32), 3,
                                 deadline=14, clock=lambda: 10)
        with self.assertRaises(ValueError):
            transport.send_grant(self.connection, request, replace(self.binding, pid=51), 3,
                                 deadline=14, clock=lambda: 10)
        with self.assertRaises(ValueError):
            transport.receive_request(self.connection, expected_uid=1001, deadline=14, clock=lambda: 10)

    @unittest.skipUnless(sys.platform == "linux", "Linux seqpacket fixture")
    def test_real_socketpair_transport_evidence(self):
        left, right = socket.socketpair(transport._AF_UNIX, socket.SOCK_SEQPACKET)
        with left, right:
            peer = transport.peer_identity(left)
            self.assertEqual((peer.pid, peer.uid, peer.gid), (os.getpid(), os.getuid(), os.getgid()))
            right.send(encode_request(self.request))
            self.assertEqual(transport._receive(left, 14, lambda: 10), encode_request(self.request))


if __name__ == "__main__":
    unittest.main()
