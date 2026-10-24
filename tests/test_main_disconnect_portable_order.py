"""Safe Disconnect returns the picture before non-display setup."""

import unittest
from contextlib import nullcontext
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

from tests.test_main_process_delivery import load_main_module


class MainDisconnectPortableOrderTests(unittest.TestCase):
    def setUp(self):
        self.module = load_main_module(real_dock_gate=True)
        self.plugin = self.module.Plugin.__new__(self.module.Plugin)
        self.plugin._unloading = False
        self.plugin._dock_mutation_gate = lambda: NS(admit=nullcontext)
        self.plugin._device_authorization = Mock()

    def test_portable_return_precedes_authorization_observation(self):
        events = []
        binding = NS(
            gpu_bdf="gpu",
            audio_bdf="audio",
            usb_bdf="usb",
            router_id="router",
            binding="b" * 64,
            generation="c" * 64,
        )
        self.plugin._return_portable_before_disconnect = Mock(
            side_effect=lambda *_: events.append("portable")
        )
        self.plugin._device_authorization_observer = Mock()
        self.plugin._device_authorization_observer.observe.side_effect = lambda: (
            events.append("authorization")
            or NS(uuid="", enrolled=False)
        )
        runtime = Mock()
        runtime._operation = "operation"
        runtime.execute_claimed.return_value = NS(
            code="dock_teardown.software_down", software_down=True
        )
        release = Mock()
        release.execute.side_effect = lambda **_: (
            events.append("release") or NS()
        )
        lease = Mock()
        lease.acquire.return_value.active = True
        lease.status.return_value.active = True

        with patch.object(self.module, "DrmDiscovery") as drm, patch.object(
            self.module, "resolve_whole_dock", return_value=binding
        ), patch.object(self.module, "GamescopeDiscovery"), patch.object(
            self.module,
            "resolve_gamescope_user",
            return_value=NS(context=NS(uid=1000, username="deck")),
        ), patch.object(self.module, "RootOwnedRuntimeState"), patch.object(
            self.module, "Login1SleepInhibitor", return_value=lease
        ), patch.object(
            self.module, "WholeDockRuntime", return_value=runtime
        ), patch.object(
            self.module, "build_live_disconnect_runtime", return_value=release
        ):
            drm.return_value.scan.return_value = [NS(boot_vga=False, pci_bdf="gpu")]
            result = self.plugin._run_whole_dock_trial("operation")

        self.assertTrue(result.software_down)
        self.assertEqual(events, ["portable", "authorization", "release"])
        self.plugin._return_portable_before_disconnect.assert_called_once()
        runtime.verify_gpu_release.assert_called_once()
        runtime.execute_claimed.assert_called_once()


if __name__ == "__main__":
    unittest.main()
