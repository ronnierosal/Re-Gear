"""Readiness evidence: why manual or Auto TDP cannot start, categorically.

Readiness reports the sustained register range only. A request maps onto the
boost registers as max(watts, register.minimum), so a boost ceiling below the
sustained ceiling narrows the usable range without appearing anywhere in
readiness. A policy in that gap passes can_start and is then refused per-tick as
auto_tdp.readback_invalid, which is a late and generic answer to a question the
device could have answered up front.

These tests pin the probe's bounded register evidence against the real
TdpReading.target_values mapping, so the reported range cannot drift from what
the provider will actually accept.
"""

import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import test_tdp_control as fixtures
from regear.adapters.steamos.auto_tdp_host import AutoTdpHostContext
from regear.ports.tdp import TdpReading, TdpRegister

spec = importlib.util.spec_from_file_location(
    "auto_tdp_context_probe", Path(__file__).resolve().parents[1] / "scripts/probe_auto_tdp_context.py")
probe_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe_module)


def narrow(slow_maximum=25, fast_maximum=25):
    """A device whose boost ceilings sit below its sustained ceiling."""
    return TdpReading("opaque-binding", TdpRegister(15, 7, 30),
                      TdpRegister(15, 15, slow_maximum), TdpRegister(15, 15, fast_maximum))


def accepts(reading, watts):
    try:
        reading.target_values(watts)
        return True
    except ValueError:
        return False


class AutoTdpReadinessEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.provider, self.host = Mock(), Mock()
        self.host.observe.return_value = AutoTdpHostContext("auto_tdp.host_context_observed", "a" * 64)

    def run_probe(self, reading):
        self.provider.observe.return_value = SimpleNamespace(reading=reading)
        return probe_module.probe(self.provider, self.host)

    def test_reported_range_matches_what_the_provider_actually_accepts(self):
        # The evidence is only useful if it agrees with target_values exactly.
        for reading in (fixtures.reading(), narrow(), narrow(43, 25), narrow(25, 53)):
            with self.subTest(reading=reading):
                expressible = self.run_probe(reading)["expressible"]
                low, high = expressible["minimum_watts"], expressible["maximum_watts"]
                self.assertIsNotNone(high)
                for watts in range(reading.sustained.minimum, reading.sustained.maximum + 1):
                    self.assertEqual(accepts(reading, watts), low <= watts <= high)

    def test_a_boost_ceiling_below_the_sustained_ceiling_is_named(self):
        expressible = self.run_probe(narrow())["expressible"]
        self.assertEqual(expressible["maximum_watts"], 25)
        self.assertTrue(expressible["narrowed_by_boost_ceiling"])
        self.assertEqual(expressible["code"], "auto_tdp.provider_range_narrowed_by_boost_ceiling")
        # Readiness would have offered the full sustained ceiling instead.
        self.assertEqual(self.run_probe(narrow())["registers"]["sustained"]["maximum"], 30)

    def test_an_unnarrowed_device_says_so_rather_than_staying_silent(self):
        expressible = self.run_probe(fixtures.reading())["expressible"]
        self.assertEqual(expressible["maximum_watts"], 30)
        self.assertFalse(expressible["narrowed_by_boost_ceiling"])
        self.assertEqual(expressible["code"], "auto_tdp.provider_range_fully_expressible")

    def test_every_register_range_is_reported_separately(self):
        registers = self.run_probe(narrow())["registers"]
        self.assertEqual(set(registers), {"sustained", "slow", "fast"})
        for name, values in registers.items():
            self.assertEqual(set(values), {"minimum", "maximum", "current"}, name)

    def test_register_evidence_survives_an_unusable_host_context(self):
        # A device that cannot export a host key can still explain its range.
        self.host.observe.return_value = AutoTdpHostContext("auto_tdp.host_unsupported")
        result = self.run_probe(narrow())
        self.assertIsNone(result["host_context_key"])
        self.assertEqual(result["code"], "auto_tdp.configuration_context_unavailable")
        self.assertEqual(result["expressible"]["maximum_watts"], 25)

    def test_evidence_is_absent_rather_than_guessed_when_no_reading_exists(self):
        result = self.run_probe(None)
        self.assertIsNone(result["registers"])
        self.assertIsNone(result["expressible"])

    def test_evidence_carries_no_raw_provider_identifier(self):
        rendered = str(self.run_probe(narrow()))
        self.assertNotIn("opaque-binding", rendered)
        self.assertFalse(self.run_probe(narrow())["authorizes_control"])


if __name__ == "__main__":
    unittest.main()
