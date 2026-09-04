import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from hdm.adapters.steamos.tdp_sensors import (
    HwmonTemperatureSource, PowerSupplySource, SensorField,
    TdpSensorInventory, TemperatureChannel,
)
from hdm.delivery.tdp_sensor_readiness import TdpSensorReadinessConfig, assess_tdp_sensor_readiness


class TdpSensorReadinessTests(unittest.TestCase):
    def setUp(self):
        # Synthetic test policy: these numbers are not hardware operating limits.
        self.config = TdpSensorReadinessConfig("Tctl", "cooling_control_value", 80.0, 2.0)
        self.channel = TemperatureChannel(1, "Tctl", "cooling_control_value", SensorField("observed", 60.0))
        self.thermal = HwmonTemperatureSource(0, True, (self.channel,))
        self.battery = PowerSupplySource(0, "battery", True, SensorField("not_applicable"), SensorField("observed", "charging"), SensorField("observed", 5.0))
        self.external = PowerSupplySource(1, "mains", True, SensorField("observed", "online_fixed"), SensorField("not_applicable"), SensorField("not_applicable"))
        self.inventory = TdpSensorInventory(10.0, 10.2, True, "observed", "observed", (self.thermal,), (self.battery, self.external))

    def assess(self, inventory=None, *, now=11.0):
        return assess_tdp_sensor_readiness(inventory or self.inventory, self.config, now=now)

    def test_explicit_configuration_has_no_defaults_or_mismatched_semantics(self):
        with self.assertRaises(TypeError):
            TdpSensorReadinessConfig()
        for label, meaning in (("Tctl", "die_temperature"), ("Tdie", "cooling_control_value"), ("unknown", "unknown"), (None, "die_temperature")):
            with self.subTest(label=label), self.assertRaises(ValueError):
                TdpSensorReadinessConfig(label, meaning, 80, 2)
        for value in (True, None, 0, -1, float("nan"), float("inf"), 10 ** 1000):
            for field in ("ceiling_celsius", "maximum_age_seconds"):
                with self.subTest(field=field, value=str(value)[:20]), self.assertRaises(ValueError):
                    replace(self.config, **{field: value})

    def test_fresh_external_power_and_temperature_below_supplied_ceiling(self):
        result = self.assess()
        self.assertEqual((result.thermal_state, result.power_source), ("below_ceiling", "external"))
        self.assertEqual(result.code, "tdp.sensor_evidence_observed")
        self.assertEqual(result.temperature_celsius, 60.0)
        self.assertEqual(result.configured_ceiling_celsius, 80.0)
        payload = json.dumps(result.to_dict())
        for unsupported in ("authorized", "writable", "hardware_validated"):
            self.assertNotIn(unsupported, payload)

    def test_ceiling_equality_is_blocking(self):
        for temperature in (80.0, 81.0):
            channel = replace(self.channel, celsius=SensorField("observed", temperature))
            inventory = replace(self.inventory, temperatures=(replace(self.thermal, channels=(channel,)),))
            self.assertEqual(self.assess(inventory).thermal_state, "at_or_above_ceiling")
            self.assertEqual(self.assess(inventory).code, "tdp.thermal_ceiling_reached")

    def test_battery_discharge_requires_offline_external_and_nonzero_power(self):
        battery = replace(self.battery, status=SensorField("observed", "discharging"))
        external = replace(self.external, online=SensorField("observed", "offline"))
        inventory = replace(self.inventory, power_supplies=(battery, external))
        self.assertEqual(self.assess(inventory).power_source, "battery_discharge")
        battery = replace(battery, battery_terminal_power_watts=SensorField("observed", -5.0))
        self.assertEqual(self.assess(replace(inventory, power_supplies=(battery, external))).power_source, "battery_discharge")
        battery = replace(battery, battery_terminal_power_watts=SensorField("observed", 0.0))
        self.assertEqual(self.assess(replace(inventory, power_supplies=(battery, external))).power_source, "unknown")

    def test_contradictory_online_and_discharge_is_unknown(self):
        battery = replace(self.battery, status=SensorField("observed", "discharging"))
        result = self.assess(replace(self.inventory, power_supplies=(battery, self.external)))
        self.assertEqual(result.power_source, "unknown")
        self.assertEqual(result.code, "tdp.power_source_unknown")

    def test_conflicting_missing_or_multiple_supply_sources_are_unknown(self):
        for supplies in ((), (self.battery,), (self.external,), (self.battery, self.battery, self.external), (self.battery, replace(self.external, kind="unknown"))):
            with self.subTest(supplies=supplies):
                self.assertEqual(self.assess(replace(self.inventory, power_supplies=supplies)).power_source, "unknown")

    def test_programmable_online_and_agreeing_external_sources(self):
        usb = replace(self.external, ordinal=2, kind="usb", online=SensorField("observed", "online_programmable"))
        self.assertEqual(self.assess(replace(self.inventory, power_supplies=(self.battery, self.external, usb))).power_source, "external")
        offline = replace(usb, online=SensorField("observed", "offline"))
        self.assertEqual(self.assess(replace(self.inventory, power_supplies=(self.battery, self.external, offline))).power_source, "external")

    def test_negative_temperature_is_unknown(self):
        channel = replace(self.channel, celsius=SensorField("observed", -1))
        inventory = replace(self.inventory, temperatures=(replace(self.thermal, channels=(channel,)),))
        self.assertEqual(self.assess(inventory).thermal_state, "unknown")

    def test_unknown_fields_do_not_become_power_readiness(self):
        for battery in (
            replace(self.battery, complete=False),
            replace(self.battery, status=SensorField()),
            replace(self.battery, battery_terminal_power_watts=SensorField("observed", float("nan"))),
            replace(self.battery, battery_terminal_power_watts=SensorField("observed", True)),
        ):
            self.assertEqual(self.assess(replace(self.inventory, power_supplies=(battery, self.external))).power_source, "unknown")
        self.assertEqual(self.assess(replace(self.inventory, power_supplies=(self.battery, replace(self.external, online=SensorField())))).power_source, "unknown")

    def test_stale_future_reversed_nonfinite_or_long_scan_is_unknown(self):
        for started, finished, now in ((10, 10.2, 12.01), (10, 11, 10.5), (11, 10, 11), (float("nan"), 10.2, 11), (10, float("inf"), 11), (True, 1.1, 2), (0, 10.9, 11)):
            result = self.assess(replace(self.inventory, started_at=started, finished_at=finished), now=now)
            self.assertEqual(result.code, "tdp.sensors_stale")
            self.assertEqual((result.thermal_state, result.power_source), ("unknown", "unknown"))
        self.assertEqual(self.assess(now=12.0).thermal_state, "below_ceiling")

    def test_incomplete_or_ambiguous_inventory_never_readies(self):
        for inventory in (
            replace(self.inventory, complete=False),
            replace(self.inventory, temperature_status="ambiguous"),
            replace(self.inventory, power_status="unknown"),
            replace(self.inventory, temperatures=(self.thermal, self.thermal)),
        ):
            result = self.assess(inventory)
            self.assertEqual((result.thermal_state, result.power_source), ("unknown", "unknown"))

    def test_missing_duplicate_mismatched_or_invalid_selected_temperature(self):
        for channels in ((), (self.channel, self.channel), (replace(self.channel, label="Tdie"),), (replace(self.channel, meaning="die_temperature"),), (replace(self.channel, celsius=SensorField("observed", float("nan"))),), (replace(self.channel, celsius=SensorField("observed", True)),)):
            inventory = replace(self.inventory, temperatures=(replace(self.thermal, channels=channels),))
            self.assertEqual(self.assess(inventory).thermal_state, "unknown")


if __name__ == "__main__":
    unittest.main()
