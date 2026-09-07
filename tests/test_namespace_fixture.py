import unittest

from scripts.probe_namespace_fixture import EXPECTED_CHECKS, fixture_checks_pass


class NamespaceFixtureTests(unittest.TestCase):
    def test_complete_fixture_evidence(self):
        self.assertTrue(fixture_checks_pass(dict.fromkeys(EXPECTED_CHECKS, True)))

    def test_missing_or_substituted_observation_rejected(self):
        checks = dict.fromkeys(EXPECTED_CHECKS, True)
        checks.pop("outside_hardlink_still_readable")
        self.assertFalse(fixture_checks_pass(checks))
        checks["isolation_proven"] = True
        self.assertFalse(fixture_checks_pass(checks))

    def test_false_and_truthy_non_boolean_rejected(self):
        for value in (False, 1, "true", None):
            checks = dict.fromkeys(EXPECTED_CHECKS, True)
            checks["mount_namespace_changed"] = value
            self.assertFalse(fixture_checks_pass(checks))

    def test_invalid_child_shape_rejected(self):
        for value in (None, [], True, "passed", {}):
            self.assertFalse(fixture_checks_pass(value))
