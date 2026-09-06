import json
import os
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from hdm.delivery.auto_tdp_configuration import (
    FILENAME, MAX_BYTES, FileAutoTdpConfiguration, decode_auto_tdp_configuration,
)
from hdm.domain.models import GameState
from hdm.domain.telemetry import TelemetryAdmissionKind, admit_telemetry_collection


class AutoConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.loader = FileAutoTdpConfiguration(self.root)
        self.path = self.root / FILENAME
        # These declarations are fixtures, not actual profile or timing evidence.
        self.value = {"schema_version": 1, "host_context_key": "a" * 64,
            "thermal": {"temperature_label": "Tctl", "temperature_meaning": "cooling_control_value",
                "ceiling_celsius": 80.0, "maximum_age_seconds": 2.0,
                "evidence_reference": "synthetic-thermal-fixture"},
            "collection": {"interval_ms": 1000, "measured_collection_cost_ms": 5,
                "benchmarked": True, "evidence_reference": "synthetic-benchmark-fixture"}}

    def write(self, value=None):
        self.path.write_text(json.dumps(self.value if value is None else value), encoding="utf-8")

    def test_missing_configuration_has_no_defaults_or_write_side_effects(self):
        result = self.loader.load()
        self.assertEqual(result.code, "auto_tdp.configuration_missing")
        self.assertIsNone(result.configuration)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_valid_explicit_configuration_preserves_declared_evidence(self):
        self.write()
        result = self.loader.load()
        self.assertEqual(result.code, "auto_tdp.configuration_loaded")
        self.assertEqual(result.configuration.sensor_config.ceiling_celsius, 80)
        self.assertEqual(result.configuration.benchmark_evidence_reference, "synthetic-benchmark-fixture")
        self.assertEqual(result.configuration.host_context_key, "a" * 64)

    def test_unbenchmarked_configuration_can_load_but_cannot_admit_auto(self):
        self.value["collection"].update(benchmarked=False, evidence_reference=None)
        self.write()
        config = self.loader.load().configuration
        admission = admit_telemetry_collection(config.collection_contract, GameState.RUNNING, auto_tdp_enabled=True)
        self.assertEqual(admission.kind, TelemetryAdmissionKind.REJECT)

    def test_expensive_measurement_is_retained_and_rejected_by_admission(self):
        self.value["collection"]["measured_collection_cost_ms"] = 20
        self.write()
        config = self.loader.load().configuration
        self.assertEqual(config.collection_contract.measured_collection_cost_ms, 20)
        self.assertEqual(admit_telemetry_collection(config.collection_contract, GameState.RUNNING,
            auto_tdp_enabled=True).reason, "telemetry.auto_tdp_cost_exceeds_budget")

    def test_unknown_missing_duplicate_and_boolean_schema_are_rejected(self):
        for transform in (lambda value: value.update(extra=True),
                          lambda value: value.pop("thermal"),
                          lambda value: value.update(schema_version=True)):
            value = deepcopy(self.value)
            transform(value)
            self.write(value)
            self.assertEqual(self.loader.load().code, "auto_tdp.configuration_invalid")
        self.path.write_text(json.dumps(self.value).replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1'))
        self.assertEqual(self.loader.load().code, "auto_tdp.configuration_invalid")

    def test_invalid_sensor_semantics_nonfinite_values_and_provenance_rejected(self):
        for field, invalid in (("temperature_meaning", "die_temperature"), ("ceiling_celsius", float("nan")),
                               ("maximum_age_seconds", 0), ("evidence_reference", ""),
                               ("evidence_reference", "private\npath")):
            value = deepcopy(self.value)
            value["thermal"][field] = invalid
            self.write(value)
            self.assertIsNone(self.loader.load().configuration)

    def test_invalid_host_cadence_or_benchmark_declaration_rejected(self):
        for field, invalid in (("interval_ms", 2000), ("benchmarked", "yes"),
                               ("evidence_reference", None), ("measured_collection_cost_ms", True)):
            value = deepcopy(self.value)
            value["collection"][field] = invalid
            self.write(value)
            self.assertIsNone(self.loader.load().configuration)
        self.value["host_context_key"] = "unknown"
        self.write()
        self.assertIsNone(self.loader.load().configuration)

    def test_byte_bound_malformed_json_and_directory_target_are_rejected(self):
        for raw in (b"x" * (MAX_BYTES + 1), b"not json", b"\xff"):
            self.path.write_bytes(raw)
            self.assertEqual(self.loader.load().code, "auto_tdp.configuration_invalid")
        self.path.unlink()
        self.path.mkdir()
        self.assertEqual(self.loader.load().code, "auto_tdp.configuration_invalid")

    @unittest.skipUnless(os.name == "posix", "POSIX ownership and mode semantics")
    def test_group_writable_file_and_symlink_are_rejected(self):
        self.write()
        self.path.chmod(0o660)
        self.assertIsNone(self.loader.load().configuration)
        self.path.chmod(0o600)
        other = self.root / "other.json"
        self.path.rename(other)
        self.path.symlink_to(other)
        self.assertIsNone(self.loader.load().configuration)

    def test_decoder_requires_bytes_and_enforces_bound_before_json(self):
        for raw in ("{}", b"x" * (MAX_BYTES + 1)):
            with self.assertRaises(ValueError):
                decode_auto_tdp_configuration(raw)
