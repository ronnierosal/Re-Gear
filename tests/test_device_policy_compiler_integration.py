"""Combined Claude policy / Codex compiler contract; no kernel operations."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from regear.domain.egpu_device_policy import EgpuDeviceNode, compose_egpu_device_policy
from regear.domain.models import EgpuResourceKind
from regear.delivery.device_filter_program import compile_device_filter
from test_device_filter_program import evaluate


class DevicePolicyCompilerIntegrationTests(unittest.TestCase):
    def test_composed_multifunction_policy_denies_only_exact_character_devices(self):
        nodes = (
            EgpuDeviceNode(EgpuResourceKind.DRM_CARD, 226, 1),
            EgpuDeviceNode(EgpuResourceKind.DRM_RENDER, 226, 129),
            EgpuDeviceNode(EgpuResourceKind.AUDIO_CONTROL, 116, 15),
            EgpuDeviceNode(EgpuResourceKind.AUDIO_HARDWARE, 116, 14),
            *(EgpuDeviceNode(EgpuResourceKind.AUDIO_PCM, 116, n) for n in range(10, 14)),
        )
        policy = compose_egpu_device_policy(nodes)
        self.assertTrue(policy.usable)
        program = compile_device_filter(policy.devices)
        self.assertEqual(len(program), 312)
        for major, minor in policy.devices:
            for access in range(1, 8):
                self.assertEqual(evaluate(program, 2, major, minor, access), 0)
                self.assertEqual(evaluate(program, 1, major, minor, access), 1)
        for major, minor in ((226, 0), (226, 128), (116, 9), (116, 16)):
            self.assertEqual(evaluate(program, 2, major, minor, 7), 1)
        reversed_policy = compose_egpu_device_policy(tuple(reversed(nodes)))
        self.assertEqual(compile_device_filter(reversed_policy.devices), program)

    def test_incomplete_policy_cannot_compile_an_empty_allow_all_filter(self):
        policy = compose_egpu_device_policy((
            EgpuDeviceNode(EgpuResourceKind.DRM_RENDER, 226, 129),
        ))
        self.assertFalse(policy.usable)
        with self.assertRaises(ValueError):
            compile_device_filter(policy.devices)
