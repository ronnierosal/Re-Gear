import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from regear.adapters.steamos.egpu_cooling import EgpuCoolingDiscovery


BDF = "0000:08:00.0"


class EgpuCoolingDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.devices = self.root / "devices"
        self.driver = self.root / "drivers/amdgpu"
        self.device = self.devices / "gpu"
        self.driver.mkdir(parents=True)
        self.device.mkdir(parents=True)
        self.hwmon = self.device / "hwmon/hwmon7"
        self.hwmon.mkdir(parents=True)
        self.write(name="amdgpu", temp1_input=48750, temp2_input=56250,
                   fan1_input=1450, pwm1_enable=2)

    def write(self, **values):
        for name, value in values.items():
            (self.hwmon / name).write_text(f"{value}\n", encoding="ascii")

    def scan(self, **changes):
        values = dict(gpu_bdf=BDF, attachment_binding="attachment", generation="generation")
        values.update(changes)
        return EgpuCoolingDiscovery(
            self.devices,
            clock=lambda: 10.0,
            device_path=lambda bdf: self.device if bdf == BDF else self.devices / "missing",
            driver_name=lambda device: "amdgpu",
        ).scan(**values)

    def test_reads_exact_gpu_temperature_fan_and_automatic_mode(self):
        result = self.scan()
        self.assertTrue(result.scan_complete)
        self.assertEqual(result.driver_name, "amdgpu")
        self.assertEqual(result.temperatures_c, (48.75, 56.25))
        self.assertEqual(result.fan_rpm, 1450)
        self.assertTrue(result.automatic_fan_control)

    def test_manual_or_unknown_pwm_is_not_reported_as_automatic(self):
        for value, expected in ((1, False), (0, False), (None, None), ("bad", None)):
            with self.subTest(value=value):
                path = self.hwmon / "pwm1_enable"
                if value is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_text(f"{value}\n", encoding="ascii")
                result = self.scan()
                self.assertIs(result.automatic_fan_control, expected)
                if value is None:
                    self.write(pwm1_enable=2)

    def test_missing_device_driver_sensor_or_required_field_fails_closed(self):
        cases = (
            self.hwmon / "name",
            self.hwmon / "fan1_input",
            self.hwmon / "pwm1_enable",
        )
        for path in cases:
            with self.subTest(path=path.name):
                original = path.read_bytes()
                path.unlink()
                self.assertFalse(self.scan().scan_complete)
                path.write_bytes(original)
        temperatures = (self.hwmon / "temp1_input", self.hwmon / "temp2_input")
        originals = tuple(path.read_bytes() for path in temperatures)
        for path in temperatures:
            path.unlink()
        self.assertFalse(self.scan().scan_complete)
        for path, original in zip(temperatures, originals):
            path.write_bytes(original)
        no_driver = EgpuCoolingDiscovery(
            self.devices,
            clock=lambda: 10.0,
            device_path=lambda bdf: self.device,
            driver_name=lambda device: "",
        ).scan(gpu_bdf=BDF, attachment_binding="attachment", generation="generation")
        self.assertFalse(no_driver.scan_complete)
        self.assertFalse(self.scan(gpu_bdf="0000:09:00.0").scan_complete)

    def test_ambiguous_or_over_bound_hwmon_fails_closed(self):
        duplicate = self.device / "hwmon/hwmon8"
        duplicate.mkdir()
        for file in self.hwmon.iterdir():
            (duplicate / file.name).write_bytes(file.read_bytes())
        self.assertFalse(self.scan().scan_complete)
        duplicate.rename(self.device / "hwmon/not-amdgpu")
        (self.device / "hwmon/not-amdgpu/name").write_text("other\n")
        with patch.object(EgpuCoolingDiscovery, "MAX_HWMON_ENTRIES", 0):
            self.assertFalse(self.scan().scan_complete)
        with patch.object(EgpuCoolingDiscovery, "MAX_HWMON_FILES", 0):
            self.assertFalse(self.scan().scan_complete)

    def test_malformed_oversized_and_out_of_range_values_fail_closed(self):
        for field, values in {
            "temp1_input": ("NaN", "-1", "200001", "1" * 129),
            "fan1_input": ("-1", "1000001", "1.5", "x" * 129),
            "pwm1_enable": ("-1", "256", "auto", "x" * 129),
        }.items():
            original = (self.hwmon / field).read_bytes()
            for value in values:
                with self.subTest(field=field, value=value):
                    (self.hwmon / field).write_text(value, encoding="ascii")
                    self.assertFalse(self.scan().scan_complete)
            (self.hwmon / field).write_bytes(original)

    def test_invalid_identity_and_clock_fail_closed(self):
        for changes in (
            {"gpu_bdf": "../../bad"},
            {"attachment_binding": ""},
            {"generation": ""},
        ):
            with self.subTest(changes=changes):
                self.assertFalse(self.scan(**changes).scan_complete)
        for clock in (lambda: float("nan"), lambda: -1, lambda: True):
            with self.subTest(clock=clock):
                result = EgpuCoolingDiscovery(
                    self.devices,
                    clock=clock,
                    device_path=lambda bdf: self.device,
                    driver_name=lambda device: "amdgpu",
                ).scan(
                    gpu_bdf=BDF, attachment_binding="attachment", generation="generation"
                )
                self.assertFalse(result.scan_complete)

    def test_scan_is_read_only(self):
        before = {str(path): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        self.scan()
        after = {str(path): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
