from __future__ import annotations

import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.application.native_portable_recovery import (  # noqa: E402
    NativePortableRecoverySupervisor,
    NativeRecoveryStage,
)
from regear.domain.models import Confidence, GameState, GpuRole  # noqa: E402
from regear.domain.serialization import snapshot_from_dict  # noqa: E402
from regear.ports.transition import VersionedObservation  # noqa: E402


FIXTURES = ROOT / "tests" / "fixtures"


def snapshot(name: str):
    return snapshot_from_dict(
        json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    )


def observed(generation: str, sample_id: str, value):
    return VersionedObservation(generation, value, sample_id)


def gamescope_down_after_loss():
    docked = snapshot("tv-docked.json")
    return replace(
        docked,
        game_state=GameState.IDLE,
        gpus=tuple(
            gpu
            for gpu in docked.gpus
            if gpu.role is not GpuRole.EXTERNAL
        ),
        displays=tuple(
            replace(display, connected=False, active=False)
            if display.kind.value == "external"
            else display
            for display in docked.displays
        ),
        gamescope=replace(
            docked.gamescope,
            running=False,
            pid=None,
            output_order=(),
            render_gpu_stable_id="",
            render_vendor_device="",
            confidence=Confidence.UNKNOWN,
        ),
    )


class NativePortableRecoverySupervisorTests(unittest.TestCase):
    def test_live_observed_sequence_waits_for_and_verifies_native_recovery(self):
        value = NativePortableRecoverySupervisor(deadline_ms=120_000)

        armed = value.update(
            enabled=True,
            current=observed("docked", "sample-1", snapshot("tv-docked.json")),
            now_ms=0,
        )
        waiting = value.update(
            enabled=True,
            current=observed("lost", "sample-2", gamescope_down_after_loss()),
            now_ms=1_000,
        )
        recovered = value.update(
            enabled=True,
            current=observed("portable", "sample-3", snapshot("portable.json")),
            now_ms=81_000,
        )

        self.assertEqual(armed.stage, NativeRecoveryStage.ARMED)
        self.assertEqual(waiting.stage, NativeRecoveryStage.WAITING)
        self.assertEqual(recovered.stage, NativeRecoveryStage.RECOVERED)
        self.assertEqual(recovered.code, "native_recovery.portable_verified")
        self.assertTrue(recovered.restore_portable_audio)

    def test_timeout_requires_action_without_authorizing_restart(self):
        value = NativePortableRecoverySupervisor(deadline_ms=2_000)
        value.update(
            enabled=True,
            current=observed("docked", "sample-1", snapshot("tv-docked.json")),
            now_ms=0,
        )
        value.update(
            enabled=True,
            current=observed("lost", "sample-2", gamescope_down_after_loss()),
            now_ms=1_000,
        )
        result = value.update(
            enabled=True,
            current=observed("lost-2", "sample-3", gamescope_down_after_loss()),
            now_ms=3_000,
        )

        self.assertEqual(result.stage, NativeRecoveryStage.ACTION_REQUIRED)
        self.assertEqual(result.code, "native_recovery.timeout")
        self.assertFalse(result.restore_portable_audio)

    def test_unknown_game_or_missing_internal_path_never_starts_wait(self):
        for changed in (
            replace(gamescope_down_after_loss(), game_state=GameState.UNKNOWN),
            replace(gamescope_down_after_loss(), displays=()),
        ):
            with self.subTest(changed=changed.game_state):
                value = NativePortableRecoverySupervisor()
                value.update(
                    enabled=True,
                    current=observed(
                        "docked", "sample-1", snapshot("tv-docked.json")
                    ),
                    now_ms=0,
                )
                result = value.update(
                    enabled=True,
                    current=observed("changed", "sample-2", changed),
                    now_ms=1_000,
                )
                self.assertEqual(result.stage, NativeRecoveryStage.ACTION_REQUIRED)

    def test_disabled_and_intentional_portable_return_clear_the_baseline(self):
        value = NativePortableRecoverySupervisor()
        value.update(
            enabled=True,
            current=observed("docked", "sample-1", snapshot("tv-docked.json")),
            now_ms=0,
        )
        disabled = value.update(
            enabled=False,
            current=observed("docked", "sample-2", snapshot("tv-docked.json")),
            now_ms=1_000,
        )
        self.assertEqual(disabled.code, "native_recovery.disabled")

        value.update(
            enabled=True,
            current=observed("docked-2", "sample-3", snapshot("tv-docked.json")),
            now_ms=2_000,
        )
        portable = value.update(
            enabled=True,
            current=observed("portable", "sample-4", snapshot("portable.json")),
            now_ms=3_000,
        )
        self.assertEqual(portable.code, "native_recovery.portable_without_incident")
        self.assertFalse(portable.restore_portable_audio)


if __name__ == "__main__":
    unittest.main()
