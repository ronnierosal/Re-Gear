import dataclasses
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from regear.domain.prepared_egpu_disconnect import (
    EgpuCoolingEvidence,
    PreparedDisconnectStage,
    decide_post_teardown,
    decide_prepared_disconnect,
)


def cooling(**changes):
    value = EgpuCoolingEvidence(
        "attachment", "generation", "0000:08:00.0", True, "amdgpu", True,
        (48.0, 54.25), 1450, True,
    )
    return dataclasses.replace(value, **changes)


class PreparedEgpuDisconnectTests(unittest.TestCase):
    def decide(self, evidence=None, **changes):
        values = dict(
            cooling=evidence or cooling(),
            display_on_handheld=True,
            clients_released=True,
            tunnel_authorized=True,
        )
        values.update(changes)
        return decide_prepared_disconnect(**values)

    def test_prepared_state_keeps_the_cooling_path_connected(self):
        decision = self.decide()
        self.assertEqual(decision.stage, PreparedDisconnectStage.PREPARED_CONNECTED)
        self.assertTrue(decision.stable_while_connected)
        self.assertTrue(decision.may_start_final_teardown)
        self.assertFalse(decision.unplug_required)
        self.assertFalse(decision.safe_to_unplug)

    def test_display_clients_transport_and_cooling_are_independent_requirements(self):
        cases = (
            ({"display_on_handheld": False}, "prepared_disconnect.handheld_display_unverified"),
            ({"clients_released": False}, "prepared_disconnect.clients_not_released"),
            ({"tunnel_authorized": False}, "prepared_disconnect.transport_not_active"),
            ({"tunnel_authorized": None}, "prepared_disconnect.transport_not_active"),
        )
        for changes, code in cases:
            with self.subTest(code=code):
                decision = self.decide(**changes)
                self.assertEqual(decision.stage, PreparedDisconnectStage.REFUSED)
                self.assertEqual(decision.code, code)

    def test_missing_driver_sensor_fan_or_automatic_mode_refuses(self):
        cases = (
            {"attachment_binding": ""},
            {"generation": ""},
            {"device_present": False},
            {"driver_name": ""},
            {"driver_name": "other"},
            {"scan_complete": False},
            {"temperatures_c": ()},
            {"temperatures_c": (float("nan"),)},
            {"temperatures_c": (-1.0,)},
            {"temperatures_c": (201.0,)},
            {"fan_rpm": None},
            {"fan_rpm": -1},
            {"automatic_fan_control": None},
            {"automatic_fan_control": False},
        )
        for changes in cases:
            with self.subTest(changes=changes):
                decision = self.decide(cooling(**changes))
                self.assertEqual(decision.stage, PreparedDisconnectStage.REFUSED)
                self.assertEqual(decision.code, "prepared_disconnect.cooling_unverified")

    def test_zero_rpm_is_observation_not_automatic_failure(self):
        decision = self.decide(cooling(fan_rpm=0))
        self.assertEqual(decision.stage, PreparedDisconnectStage.PREPARED_CONNECTED)

    def test_software_down_is_transitional_until_physical_absence(self):
        decision = decide_post_teardown(
            software_down=True, physical_transport_absent_verified=False
        )
        self.assertEqual(decision.stage, PreparedDisconnectStage.UNPLUG_REQUIRED)
        self.assertTrue(decision.unplug_required)
        self.assertFalse(decision.stable_while_connected)
        self.assertFalse(decision.complete)
        self.assertFalse(decision.safe_to_unplug)

    def test_only_verified_physical_absence_completes_the_flow(self):
        decision = decide_post_teardown(
            software_down=True, physical_transport_absent_verified=True
        )
        self.assertEqual(decision.stage, PreparedDisconnectStage.COMPLETE)
        self.assertTrue(decision.complete)
        self.assertFalse(decision.safe_to_unplug)

    def test_no_final_teardown_evidence_refuses(self):
        decision = decide_post_teardown(
            software_down=False, physical_transport_absent_verified=False
        )
        self.assertEqual(decision.stage, PreparedDisconnectStage.REFUSED)


if __name__ == "__main__":
    unittest.main()
