"""Exercise the production coordination gate without a model-provider dependency."""
import unittest

from tests.test_github_coordination import BASE, HEAD, c, ev, pr, ready


class ReviewSessionIndependenceTests(unittest.TestCase):
    def candidate(self, **changes):
        candidate = ready(**changes)
        candidate["review"] = ev(reviewer="codex-independent-review-session")
        return candidate

    def test_separate_codex_reviewer_accepts_codex_owned_candidate(self):
        candidate = self.candidate()
        self.assertEqual(candidate["agent"], "codex-cloud")
        c.check(candidate, pr())

    def test_owner_or_missing_reviewer_cannot_replace_independent_review(self):
        for reviewer in ("codex-one", "", None):
            with self.subTest(reviewer=reviewer):
                with self.assertRaisesRegex(ValueError, "independent reviewer"):
                    candidate = self.candidate()
                    candidate["review"]["reviewer"] = reviewer
                    c.check(candidate, pr())

    def test_exact_software_and_review_evidence_remain_required(self):
        for field in ("software", "review"):
            for delta in ({"head": "c" * 40}, {"base": "c" * 40},
                          {"result": "FAIL"}, {"url": ""}):
                with self.subTest(field=field, delta=delta):
                    candidate = self.candidate()
                    candidate[field].update(delta)
                    with self.assertRaises(ValueError):
                        c.check(candidate, pr())
            candidate = self.candidate()
            del candidate[field]
            with self.assertRaises(ValueError):
                c.check(candidate, pr())

    def test_same_family_review_does_not_bypass_draft_gate(self):
        with self.assertRaisesRegex(ValueError, "draft"):
            c.check(self.candidate(), pr(draft=True))

    def test_class_c_still_requires_exact_immutable_hardware_evidence(self):
        candidate = self.candidate(hardware="required", **{"class": "C"})
        with self.assertRaisesRegex(ValueError, "hardware_evidence"):
            c.check(candidate, pr())
        candidate["hardware_evidence"] = ev(
            agent="codex-local", tester="hardware-driver", tested_commit=HEAD,
            artifact="sha256:" + "d" * 64)
        c.check(candidate, pr())
        for delta in ({"tested_commit": BASE}, {"artifact": "unverified"},
                      {"head": BASE}, {"agent": "codex-cloud"}):
            with self.subTest(delta=delta):
                bad = dict(candidate, hardware_evidence=dict(candidate["hardware_evidence"], **delta))
                with self.assertRaises(ValueError):
                    c.check(bad, pr())

    def test_class_d_still_requires_supervised_procedure(self):
        candidate = self.candidate(hardware="required", **{"class": "D"})
        candidate["hardware_evidence"] = ev(
            agent="codex-local", tester="hardware-driver", tested_commit=HEAD,
            artifact="sha256:" + "d" * 64)
        with self.assertRaisesRegex(ValueError, "procedure"):
            c.check(candidate, pr())
        candidate["procedure_approval"] = "https://example.org/supervised-procedure"
        c.check(candidate, pr())


if __name__ == "__main__":
    unittest.main()
