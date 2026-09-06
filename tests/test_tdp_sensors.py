import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from hdm.adapters.steamos.tdp_sensors import TdpSensorDiscovery


class TdpSensorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.hwmon = self.root / "class/hwmon"
        self.power = self.root / "class/power_supply"
        self.hwmon.mkdir(parents=True)
        self.power.mkdir(parents=True)
        self.scanner = TdpSensorDiscovery(self.root, clock=lambda: 10.0)

    @staticmethod
    def fields(root, **fields):
        root.mkdir(parents=True, exist_ok=True)
        for name, value in fields.items():
            (root / name).write_text(str(value) + "\n", encoding="utf-8")
        return root

    def sensor(self, name="hwmon83", **fields):
        return self.fields(self.hwmon / name, **{"name": "k10temp", "temp1_label": "Tctl", "temp1_input": 62500, **fields})

    def battery(self, **fields):
        return self.fields(self.power / "arbitrary-battery", **{"type": "Battery", "status": "Discharging", "power_now": 13500000, **fields})

    def test_discovery_by_name_and_distinct_label_semantics(self):
        self.fields(self.hwmon / "hwmon0", name="amdgpu", temp1_input=99999)
        self.sensor(temp2_label="Tdie", temp2_input=60250, temp3_label="Tccd1", temp3_input=59125)
        result = self.scanner.scan()
        self.assertTrue(result.complete)
        self.assertEqual(result.temperature_status, "observed")
        channels = result.temperatures[0].channels
        self.assertEqual([(v.label, v.meaning, v.celsius.value) for v in channels], [
            ("Tctl", "cooling_control_value", 62.5), ("Tdie", "die_temperature", 60.25), ("Tccd1", "ccd_temperature", 59.125),
        ])

    def test_battery_power_and_external_online_are_separate(self):
        self.battery()
        self.fields(self.power / "not-AC0", type="Mains", online=1)
        self.fields(self.power / "usb-c", type="USB_PD", online=2)
        result = self.scanner.scan()
        self.assertTrue(result.complete)
        battery = next(s for s in result.power_supplies if s.kind == "battery")
        self.assertEqual(battery.status.value, "discharging")
        self.assertEqual(battery.battery_terminal_power_watts.value, 13.5)
        self.assertEqual(battery.online.state, "not_applicable")
        online = {s.kind: s.online.value for s in result.power_supplies if s.kind != "battery"}
        self.assertEqual(online, {"mains": "online_fixed", "usb": "online_programmable"})
        self.assertNotIn("apu", json.dumps(result.to_dict()).lower())

    def test_signed_battery_power_does_not_override_status(self):
        self.battery(status="Charging", power_now=-12345000)
        source = self.scanner.scan().power_supplies[0]
        self.assertEqual(source.battery_terminal_power_watts.value, -12.345)
        self.assertEqual(source.status.value, "charging")

    def test_multiple_k10temp_sources_remain_ambiguous(self):
        self.sensor("hwmon2")
        self.sensor("hwmon9")
        result = self.scanner.scan()
        self.assertEqual(len(result.temperatures), 2)
        self.assertEqual(result.temperature_status, "ambiguous")

    def test_missing_roots_and_empty_roots_never_claim_observed(self):
        for root in (self.root, self.root / "missing"):
            result = TdpSensorDiscovery(root).scan()
            self.assertEqual(result.temperature_status, "unknown")
            self.assertEqual(result.power_status, "unknown")
        self.assertFalse(TdpSensorDiscovery(self.root / "missing").scan().complete)

    def test_missing_or_unknown_label_retains_value_without_claiming_die(self):
        root = self.sensor()
        for label in (None, "private unexpected label"):
            if label is None:
                (root / "temp1_label").unlink()
            else:
                (root / "temp1_label").write_text(label)
            result = self.scanner.scan()
            self.assertFalse(result.complete)
            channel = result.temperatures[0].channels[0]
            self.assertEqual((channel.label, channel.meaning, channel.celsius.value), ("unknown", "unknown", 62.5))

    def test_malformed_nonfinite_oversized_and_out_of_range_values_are_unknown(self):
        root = self.sensor()
        for value in ("NaN", "inf", "1.5", "1e3", "１２", "2147483648", "-2147483649", "x" * 129):
            with self.subTest(value=value):
                (root / "temp1_input").write_text(value, encoding="utf-8")
                result = self.scanner.scan()
                self.assertFalse(result.complete)
                self.assertEqual(result.temperature_status, "unknown")
                self.assertEqual(result.temperatures[0].channels[0].celsius.state, "unknown")

    def test_missing_battery_power_is_not_inferred_from_current_and_voltage(self):
        root = self.battery(current_now=1000000, voltage_now=15000000)
        (root / "power_now").unlink()
        result = self.scanner.scan()
        self.assertFalse(result.complete)
        self.assertIsNone(result.power_supplies[0].battery_terminal_power_watts.value)

    def test_unknown_status_online_or_type_remain_unknown(self):
        root = self.fields(self.power / "supply", type="Mains", online=3)
        self.assertFalse(self.scanner.scan().complete)
        self.fields(root, type="unrecognized-private-type", online=1)
        self.assertFalse(self.scanner.scan().complete)
        self.assertEqual(self.scanner.scan().power_supplies[0].kind, "unknown")
        self.fields(root, type="Battery", status="Unknown", power_now=5000000)
        self.assertFalse(self.scanner.scan().complete)

    def test_incomplete_discovery_suppresses_positive_summary(self):
        self.sensor()
        self.fields(self.hwmon / "unreadable-name")
        self.fields(self.power / "mains", type="Mains", online=1)
        result = self.scanner.scan()
        self.assertFalse(result.complete)
        self.assertEqual((result.temperature_status, result.power_status), ("unknown", "unknown"))
        self.assertEqual(result.power_supplies[0].online.value, "online_fixed")

    def test_limits_on_source_and_channel_enumeration(self):
        self.sensor()
        self.sensor("hwmon99")
        self.battery()
        for constant in ("MAX_HWMON_ENTRIES", "MAX_CHANNEL_ENTRIES", "MAX_SUPPLY_ENTRIES"):
            with self.subTest(constant=constant), patch.object(self.scanner, constant, 0):
                self.assertFalse(self.scanner.scan().complete)

    def test_clock_window_and_invalid_clocks(self):
        self.sensor()
        times = iter((15.0, 15.25))
        result = TdpSensorDiscovery(self.root, clock=lambda: next(times)).scan()
        self.assertEqual((result.started_at, result.finished_at), (15.0, 15.25))
        for first, last in ((float("nan"), 1), (1, float("inf")), (2, 1), (True, 2), (-1, 2)):
            times = iter((first, last))
            result = TdpSensorDiscovery(self.root, clock=lambda: next(times)).scan()
            self.assertFalse(result.complete)
            self.assertEqual(result.temperature_status, "unknown")

    def test_permission_failure_is_unknown_and_does_not_expose_details(self):
        self.sensor()
        with patch.object(Path, "open", side_effect=PermissionError("private details")):
            result = self.scanner.scan()
        self.assertFalse(result.complete)
        payload = json.dumps(result.to_dict())
        self.assertNotIn("private", payload)
        self.assertNotIn(str(self.root), payload)

    def test_scan_does_not_modify_files(self):
        self.sensor()
        self.battery()
        before = {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.scanner.scan()
        after = {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
