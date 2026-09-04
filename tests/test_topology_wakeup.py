"""Synthetic uevents only: no host socket, device, or transition access."""

import asyncio
import socket
import unittest
from unittest.mock import Mock, patch

from backend.hdm.adapters.steamos import topology_wakeup as module


def event(subsystem=b"drm", action=b"change"):
    return action + b"@/devices/example\0ACTION=" + action + b"\0DEVPATH=/devices/example\0SUBSYSTEM=" + subsystem + b"\0"


class ParserTests(unittest.TestCase):
    def test_allowlisted_subsystems_and_actions(self):
        for subsystem in (b"pci", b"drm", b"thunderbolt"):
            for action in (b"add", b"remove", b"change", b"bind", b"unbind", b"move"):
                self.assertTrue(module.is_topology_invalidation(event(subsystem, action)))

    def test_rejects_other_subsystems_actions_and_malformed_messages(self):
        for data in (
            b"", event(b"usb"), event(action=b"online"), event()[:-1],
            event() + b"SUBSYSTEM=pci\0", event().replace(b"ACTION=change", b"ACTION=add"),
            event().replace(b"DEVPATH=/devices/example", b"DEVPATH=/other"),
            b"libudev\0" + event(), b"x" * (module.MAX_DATAGRAM_BYTES + 1),
            event() + b"x=y\0" * 129,
            event(b"thunderbolt")[:-1],
            event(b"thunderbolt") + b"x" * module.MAX_DATAGRAM_BYTES,
        ):
            with self.subTest(data=data[:60]):
                self.assertFalse(module.is_topology_invalidation(data))


class MonitorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.monitor = module.LinuxTopologyWakeup()
        self.sock = Mock()
        self.sock.fileno.return_value = 42
        self.loop = Mock()

    def tearDown(self):
        self.monitor.close()

    def start(self):
        with patch.object(module.sys, "platform", "linux"), patch.object(
            module.socket, "AF_NETLINK", 16, create=True
        ), patch.object(module.socket, "socket", return_value=self.sock), patch.object(
            module.asyncio, "get_running_loop", return_value=self.loop
        ):
            return self.monitor.start()

    def test_subscription_and_idempotent_cleanup(self):
        self.assertTrue(self.start())
        self.assertTrue(self.start())
        self.sock.bind.assert_called_once_with((0, 1))
        self.sock.setblocking.assert_called_once_with(False)
        self.loop.add_reader.assert_called_once_with(42, self.monitor._on_readable)
        self.monitor.close()
        self.monitor.close()
        self.loop.remove_reader.assert_called_once_with(42)
        self.sock.close.assert_called_once()
        self.assertFalse(self.monitor.available)
        self.assertFalse(self.monitor.start())

    async def test_events_coalesce_and_next_wait_times_out(self):
        self.start()
        self.sock.recvmsg.side_effect = [(event(), [], 0, (0, 1))] * 5 + [BlockingIOError()]
        self.monitor._on_readable()
        self.assertTrue(await self.monitor.wait(0.001))
        self.assertEqual(self.monitor.last_wake_source, "kernel_event")
        self.assertFalse(await self.monitor.wait(0.001))
        self.assertEqual(self.monitor.last_wake_source, "poll_timer")

    async def test_local_invalidations_coalesce_without_socket(self):
        self.monitor.invalidate()
        self.monitor.invalidate()
        self.assertTrue(await self.monitor.wait(0.001))
        self.assertEqual(self.monitor.last_wake_source, "local_change")
        self.assertFalse(await self.monitor.wait(0.001))

    async def test_mixed_kernel_and_local_wake_preserves_both_causes(self):
        self.start()
        self.sock.recvmsg.side_effect = [(event(), [], 0, (0, 1)), BlockingIOError()]
        self.monitor._on_readable()
        self.monitor.invalidate()
        self.assertTrue(await self.monitor.wait(0.001))
        self.assertEqual(self.monitor.last_wake_source, "kernel_and_local")

    async def test_sender_truncation_and_unrelated_events_ignored(self):
        self.start()
        self.sock.recvmsg.side_effect = [
            (event(), [], 0, (1234, 1)),
            (event(), [], getattr(socket, "MSG_TRUNC", 0x20), (0, 1)),
            (event(b"input"), [], 0, (0, 1)), BlockingIOError(),
        ]
        self.monitor._on_readable()
        self.assertFalse(await self.monitor.wait(0.001))

    def test_drain_work_is_bounded_under_storm(self):
        self.start()
        self.sock.recvmsg.return_value = (event(), [], 0, (0, 1))
        self.monitor._on_readable()
        self.assertEqual(self.sock.recvmsg.call_count, module.MAX_DRAIN_DATAGRAMS)

    async def test_receive_failure_wakes_once_and_releases_reader(self):
        self.start()
        self.sock.recvmsg.side_effect = OSError("receive queue lost")
        self.monitor._on_readable()
        self.assertFalse(self.monitor.available)
        self.assertTrue(await self.monitor.wait(0.001))
        self.assertEqual(self.monitor.last_wake_source, "observer_degraded")
        self.assertFalse(await self.monitor.wait(0.001))
        self.loop.remove_reader.assert_called_once_with(42)

    async def test_unsupported_platform_uses_real_timeout(self):
        with patch.object(module.sys, "platform", "win32"):
            self.assertFalse(self.monitor.start())
        loop = asyncio.get_running_loop()
        started = loop.time()
        self.assertFalse(await self.monitor.wait(0.01))
        self.assertGreaterEqual(loop.time() - started, 0.009)

    def test_bind_failure_closes_socket(self):
        self.sock.bind.side_effect = PermissionError()
        self.assertFalse(self.start())
        self.sock.close.assert_called_once()
        self.loop.add_reader.assert_not_called()

    def test_unsupported_reader_closes_socket(self):
        self.loop.add_reader.side_effect = NotImplementedError()
        self.assertFalse(self.start())
        self.sock.close.assert_called_once()

    async def test_close_wakes_waiter(self):
        task = asyncio.create_task(self.monitor.wait(30))
        await asyncio.sleep(0)
        self.monitor.close()
        self.assertFalse(await asyncio.wait_for(task, 0.5))

    async def test_cancelled_owner_closes_without_pending_tasks(self):
        self.start()
        before = asyncio.all_tasks()

        async def owner():
            try:
                await self.monitor.wait(30)
            finally:
                self.monitor.close()

        task = asyncio.create_task(owner())
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(self.monitor.available)
        self.assertEqual(asyncio.all_tasks(), before)

    async def test_invalid_fallback_cannot_create_busy_loop(self):
        for timeout in (0, -1, float("inf"), float("nan")):
            with self.assertRaises(ValueError):
                await self.monitor.wait(timeout)


if __name__ == "__main__":
    unittest.main()
