"""Identity-only regressions; no Mini feature or runtime admission."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from regear.adapters.steamos.host import HostRecord
from regear.profiles.win_mini import match_win_mini, PROFILE_ID, QUALIFICATION_STATUS
from regear.profiles.registry import DEFAULT_RUNTIME_PROFILE_CATALOG

OBSERVED = ('GPD', 'G1617-01', 'G1617-01')


class MiniIdentityTests(unittest.TestCase):
    def test_exact_and_normalized_tuple(self):
        self.assertTrue(match_win_mini(HostRecord(*OBSERVED)).exact)
        normalized = tuple("  " + value.swapcase() + "\t" for value in OBSERVED)
        self.assertTrue(match_win_mini(HostRecord(*normalized)).exact)

    def test_every_field_is_required_and_exact(self):
        for index in range(3):
            for invalid in ("", " ", "unknown", "near-" + OBSERVED[index],
                            OBSERVED[index] + "-other", None, 1, "x" * 257, "\ud800"):
                fields = list(OBSERVED);fields[index] = invalid
                with self.subTest(field=index, case=type(invalid).__name__):
                    self.assertFalse(match_win_mini(HostRecord(*fields)).exact)

    def test_product_name_alone_and_ambiguous_records_deny(self):
        self.assertFalse(match_win_mini(HostRecord("", OBSERVED[1], "")).exact)
        for invalid in (None, {}, OBSERVED, [HostRecord(*OBSERVED)], object()):
            self.assertFalse(match_win_mini(invalid).exact)

    def test_identity_is_not_registered_or_capability_authority(self):
        self.assertEqual(QUALIFICATION_STATUS, "experimental-unqualified")
        self.assertIsNone(DEFAULT_RUNTIME_PROFILE_CATALOG.host(PROFILE_ID))
        import regear.profiles.win_mini as module
        self.assertFalse(hasattr(module, "CAPABILITIES"))


if __name__ == "__main__":unittest.main()
