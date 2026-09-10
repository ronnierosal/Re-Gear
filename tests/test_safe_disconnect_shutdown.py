from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.adapters.steamos.commands import SystemPowerCommandRunner  # noqa: E402
from regear.application.safe_disconnect_shutdown import (  # noqa: E402
    SafeDisconnectShutdownApprovalStore,
    SafeDisconnectShutdownService,
)
from regear.domain.serialization import snapshot_from_dict  # noqa: E402
from regear.ports.system_power import PowerOffResult  # noqa: E402
from regear.ports.transition import VersionedObservation  # noqa: E402


FIXTURES = ROOT / "tests" / "fixtures"


def observation(name="connected-internal.json", *, generation="generation-1", game=None):
    value = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    if game is not None:
        value["game_state"] = game
    for gpu in value["gpus"]:
        if gpu["role"] == "external":
            old = gpu["stable_id"]
            gpu["stable_id"] = "gpd-g1:0123456789abcdef"
            if value["gamescope"].get("render_gpu_stable_id") == old:
                value["gamescope"]["render_gpu_stable_id"] = gpu["stable_id"]
    return VersionedObservation(generation, snapshot_from_dict(value))


class Observations:
    def __init__(self, *values):
        self.values = list(values)

    def observe(self):
        return self.values.pop(0) if self.values else None


class Power:
    def __init__(
        self,
        result=PowerOffResult(
            True, "safe_disconnect.poweroff_request_accepted_unverified"
        ),
    ):
        self.result = result
        self.calls = 0

    def request_poweroff(self):
        self.calls += 1
        return self.result


def approvals(now=lambda: 10):
    return SafeDisconnectShutdownApprovalStore(
        ttl_seconds=30,
        monotonic=now,
        token_factory=lambda: "safe_disconnect_token_0001",
    )


class SafeDisconnectShutdownTests(unittest.TestCase):
    def test_verified_idle_portable_confirmation_queues_poweroff_once(self):
        power = Power()
        service = SafeDisconnectShutdownService(
            observations=Observations(observation(), observation()),
            power=power,
            approvals=approvals(),
        )

        preview = service.preview(user_confirmed=True)
        self.assertTrue(preview.ready)
        self.assertEqual(preview.approval_token, "safe_disconnect_token_0001")
        result = service.execute(preview.approval_token)

        self.assertTrue(result.accepted)
        self.assertEqual(
            result.code, "safe_disconnect.poweroff_request_accepted_unverified"
        )
        self.assertEqual(power.calls, 1)
        self.assertFalse(service.execute(preview.approval_token).accepted)
        self.assertEqual(power.calls, 1)

    def test_docked_running_unknown_or_unavailable_state_fails_closed(self):
        cases = (
            (observation("tv-docked.json"), "safe_disconnect.portable_unverified"),
            (observation("portable.json"), "safe_disconnect.egpu_not_observed"),
            (observation(game="running"), "safe_disconnect.game_running"),
            (observation(game="unknown"), "safe_disconnect.game_state_unknown"),
            (None, "safe_disconnect.observation_unavailable"),
        )
        for observed, code in cases:
            with self.subTest(code=code):
                preview = SafeDisconnectShutdownService(
                    observations=Observations(observed),
                    power=Power(),
                    approvals=approvals(),
                ).preview(user_confirmed=True)
                self.assertFalse(preview.ready)
                self.assertIn(code, preview.blockers)
                self.assertFalse(preview.approval_token)

    def test_changed_or_expired_evidence_never_powers_off(self):
        power = Power()
        service = SafeDisconnectShutdownService(
            observations=Observations(
                observation(), observation(generation="generation-2")
            ),
            power=power,
            approvals=approvals(),
        )
        token = service.preview(user_confirmed=True).approval_token
        self.assertEqual(
            service.execute(token).code, "safe_disconnect.evidence_changed"
        )
        self.assertEqual(power.calls, 0)

        ticks = iter((0, 31)).__next__
        expired = SafeDisconnectShutdownService(
            observations=Observations(observation(), observation()),
            power=power,
            approvals=approvals(ticks),
        )
        token = expired.preview(user_confirmed=True).approval_token
        self.assertEqual(
            expired.execute(token).code, "safe_disconnect.approval_invalid"
        )
        self.assertEqual(power.calls, 0)

    def test_fixed_power_command_requires_root_and_never_uses_a_shell(self):
        self.assertEqual(
            SystemPowerCommandRunner(effective_uid=lambda: 1000)
            .request_poweroff()
            .code,
            "safe_disconnect.root_required",
        )
        completed = subprocess.CompletedProcess(
            SystemPowerCommandRunner.COMMAND, 0, b"", b""
        )
        with patch("subprocess.run", return_value=completed) as run:
            result = SystemPowerCommandRunner(
                effective_uid=lambda: 0
            ).request_poweroff()
        self.assertTrue(result.requested)
        run.assert_called_once_with(
            SystemPowerCommandRunner.COMMAND,
            capture_output=True,
            check=False,
            shell=False,
            text=False,
            timeout=5.0,
            env={"LANG": "C", "LC_ALL": "C", "PATH": "/usr/bin:/bin"},
        )


if __name__ == "__main__":
    unittest.main()
