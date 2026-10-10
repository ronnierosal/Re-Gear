"""Inert planning evidence must never grant runtime authorization."""

import ast
from dataclasses import FrozenInstanceError, fields, replace
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from regear.domain.usb4_authorization_capability import (
    CapabilityEvidence, Fact, Readiness, assess_capability,
)


def qualified():
    return CapabilityEvidence(**{f.name: Fact.VERIFIED for f in fields(CapabilityEvidence)})


class AuthorizationCapabilityTests(unittest.TestCase):
    def assert_inert(self, result):
        for stage in (result.observation, result.authorization, result.enrollment):
            self.assertIs(stage.dispatch_allowed, False)
            self.assertIs(stage.mutation_allowed, False)

    def test_no_live_evidence_is_unknown_and_inert(self):
        result = assess_capability(CapabilityEvidence())
        self.assertEqual(result.authorization.state, Readiness.UNKNOWN)
        self.assertIn("interface_available.unknown", result.authorization.reasons)
        self.assert_inert(result)

    def test_qualified_fixture_is_only_test_planning_not_authority(self):
        result = assess_capability(qualified())
        self.assertEqual(result.observation.state, Readiness.OBSERVABLE)
        self.assertEqual(result.authorization.state, Readiness.ELIGIBLE_FOR_SUPERVISED_TEST)
        self.assertEqual(result.enrollment.state, Readiness.ELIGIBLE_FOR_SUPERVISED_TEST)
        self.assert_inert(result)

    def test_each_missing_or_negative_prerequisite_denies_affected_stage(self):
        for field in fields(CapabilityEvidence):
            for fact in Fact:
                if fact is Fact.VERIFIED:
                    continue
                with self.subTest(field=field.name, fact=fact):
                    result = assess_capability(replace(qualified(), **{field.name: fact}))
                    self.assert_inert(result)
                    stages = [result.enrollment]
                    if field.name not in {"enrollment_interface", "policy_ownership", "persistent_policy", "enrollment_readback"}:
                        stages.append(result.authorization)
                    for stage in stages:
                        self.assertNotEqual(stage.state, Readiness.ELIGIBLE_FOR_SUPERVISED_TEST)
                        self.assertIn(field.name + "." + fact.value, stage.reasons)

    def test_observation_does_not_depend_on_mutation_service(self):
        result = assess_capability(replace(qualified(), interface_available=Fact.UNAVAILABLE))
        self.assertEqual(result.observation.state, Readiness.OBSERVABLE)
        self.assertEqual(result.authorization.state, Readiness.UNAVAILABLE)
        self.assert_inert(result)

    def test_enrollment_has_independent_prerequisites(self):
        for name in ("enrollment_interface", "policy_ownership", "persistent_policy", "enrollment_readback"):
            result = assess_capability(replace(qualified(), **{name: Fact.UNKNOWN}))
            self.assertEqual(result.authorization.state, Readiness.ELIGIBLE_FOR_SUPERVISED_TEST)
            self.assertEqual(result.enrollment.state, Readiness.UNKNOWN)

    def test_already_authorized_or_enrolled_is_not_a_grant_candidate(self):
        for name in ("unauthorized", "unenrolled"):
            result = assess_capability(replace(qualified(), **{name: Fact.REFUTED}))
            self.assertEqual(result.authorization.state, Readiness.BLOCKED)
            self.assertEqual(result.enrollment.state, Readiness.BLOCKED)

    def test_strict_types_and_immutability(self):
        for value in (True, False, 1, "verified", None, object()):
            with self.assertRaises(ValueError):
                CapabilityEvidence(interface_available=value)
            self.assertEqual(assess_capability(value).authorization.state, Readiness.READ_ONLY)
        evidence = qualified()
        with self.assertRaises(FrozenInstanceError):
            evidence.interface_available = Fact.UNKNOWN
        with self.assertRaises(FrozenInstanceError):
            assess_capability(evidence).authorization.dispatch_allowed = True
        object.__setattr__(evidence, "interface_available", True)
        self.assertEqual(assess_capability(evidence).authorization.reasons, ("evidence.malformed",))

    def test_forged_and_subclass_inputs_fail_closed_without_accessor_calls(self):
        class Accessor:
            def __getattr__(self, name):
                raise AssertionError("untrusted accessor invoked")
        class Derived(CapabilityEvidence):
            pass
        for value in (Accessor(), Derived(), {"interface_available": "verified"}, object.__new__(CapabilityEvidence)):
            result = assess_capability(value)
            self.assertEqual(result.authorization.state, Readiness.READ_ONLY)
            self.assert_inert(result)

    def test_contract_has_no_production_consumer_or_effect_import(self):
        root = Path(__file__).resolve().parents[1]
        source = root / "backend/regear/domain/usb4_authorization_capability.py"
        tree = ast.parse(source.read_text())
        imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        self.assertEqual(imports, {"dataclasses", "enum"})
        for path in (root / "backend").rglob("*.py"):
            if path != source:
                self.assertNotIn("usb4_authorization_capability", path.read_text(), str(path))
        self.assertNotIn("usb4_authorization_capability", (root / "main.py").read_text())


if __name__ == "__main__":
    unittest.main()
