"""Cover the pre-edit claim query, kept apart from the contention report tests.

`tests/test_pr_collisions.py` owns the queue-wide contention report. These cover
the second question the script answers -- "is anyone already claiming the path I
am about to touch" -- including the single-claimant case the contention report
is defined never to show.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_pr_collisions  # noqa: E402
from check_pr_collisions import (  # noqa: E402
    Claim,
    collect_open_pull_request_bases,
    main,
    path_claims,
    paths_present,
    render_claims,
)


CLAIMS = {
    122: ("backend/regear/egpu_remove.py",),
    75: ("main.py", "a.py"),
    70: ("main.py",),
}


class PathClaimsTests(unittest.TestCase):
    """The question an agent asks before editing, not the queue-wide one."""

    def _claims(self, paths, present):
        return path_claims(CLAIMS, paths, present=present)

    def test_a_single_claimant_is_reported(self) -> None:
        """Contention never reports this case; this report exists for it."""
        found = self._claims(["a.py"], present=["a.py"])
        self.assertEqual([item.pull_requests for item in found], [(75,)])
        self.assertEqual(found[0].kind, "claimed")

    def test_a_claimed_path_absent_from_the_base_is_duplicated_work(self) -> None:
        found = self._claims(["backend/regear/egpu_remove.py"], present=[])
        self.assertEqual(found[0].kind, "duplicate-work")
        self.assertIn("already building this", found[0].reason)

    def test_an_existing_path_with_several_claimants_is_contention(self) -> None:
        found = self._claims(["main.py"], present=["main.py"])
        self.assertEqual(found[0].kind, "contended")
        self.assertEqual(found[0].pull_requests, (70, 75))

    def test_an_unclaimed_path_is_omitted(self) -> None:
        self.assertEqual(self._claims(["untouched.py"], present=["untouched.py"]), ())

    def test_duplicated_work_sorts_above_contention(self) -> None:
        found = self._claims(
            ["main.py", "backend/regear/egpu_remove.py"], present=["main.py"]
        )
        self.assertEqual([item.kind for item in found], ["duplicate-work", "contended"])

    def test_risk_classification_is_shared_with_the_contention_report(self) -> None:
        found = self._claims(["main.py"], present=["main.py"])
        self.assertEqual(found[0].risk, "integration-point")

    def test_a_repeated_path_is_asked_once(self) -> None:
        self.assertEqual(len(self._claims(["a.py", "a.py"], present=["a.py"])), 1)

    def test_bases_are_carried_for_each_claimant(self) -> None:
        found = path_claims(
            CLAIMS, ["main.py"], present=["main.py"], bases={70: "main", 75: "x"}
        )
        self.assertEqual(found[0].bases, ("main", "x"))

    def test_a_missing_base_is_empty_rather_than_dropped(self) -> None:
        found = path_claims(CLAIMS, ["a.py"], present=["a.py"], bases={})
        self.assertEqual(found[0].bases, ("",))

    def test_a_claim_needs_one_base_per_pull_request(self) -> None:
        with self.assertRaises(ValueError):
            Claim("a.py", (1, 2), ("main",), "contended", "shared")


class RenderClaimsTests(unittest.TestCase):
    def test_no_claims_states_how_many_paths_were_checked(self) -> None:
        self.assertIn("2 path(s)", render_claims((), ["a.py", "b.py"]))

    def test_the_report_names_kind_owners_and_base(self) -> None:
        claim = Claim("new.py", (122,), ("main",), "duplicate-work", "shared")
        text = render_claims((claim,), ["new.py"])
        self.assertIn("new.py [duplicate-work] [shared]", text)
        self.assertIn("#122 (base main)", text)
        self.assertIn("Read that pull request", text)

    def test_an_unknown_base_is_not_rendered_as_empty_parentheses(self) -> None:
        claim = Claim("a.py", (75,), ("",), "claimed", "shared")
        self.assertNotIn("()", render_claims((claim,), ["a.py"]))


class FakeCompleted:
    def __init__(self, returncode: int, stderr: str) -> None:
        self.returncode = returncode
        self.stderr = stderr


class PathsPresentTests(unittest.TestCase):
    """A broken ref must never be reported as an absent path."""

    @contextlib.contextmanager
    def _git(self, *, ref_ok: bool = True, present: bool = True):
        """Answer the ref check and the per-path checks independently."""
        original = check_pr_collisions.subprocess.run

        def fake(argv, **kwargs):
            if "rev-parse" in argv:
                return FakeCompleted(0 if ref_ok else 1, "" if ref_ok else "fatal: bad")
            return FakeCompleted(0 if present else 128, "" if present else "fatal: no")

        check_pr_collisions.subprocess.run = fake
        try:
            yield
        finally:
            check_pr_collisions.subprocess.run = original

    def test_a_path_on_the_ref_is_present(self) -> None:
        with self._git(present=True):
            self.assertEqual(paths_present(["a.py"]), ("a.py",))

    def test_a_path_missing_from_the_ref_is_absent(self) -> None:
        with self._git(present=False):
            self.assertEqual(paths_present(["a.py"]), ())

    def test_an_unresolvable_ref_raises_rather_than_reporting_absent(self) -> None:
        # Reporting this as absent would relabel every ordinary claim as
        # duplicated work, which is the one line a reader must not learn to skip.
        with self._git(ref_ok=False):
            with self.assertRaises(RuntimeError):
                paths_present(["a.py"], "origin/nope")

    def test_the_ref_is_resolved_once_rather_than_per_path(self) -> None:
        calls: list = []
        original = check_pr_collisions.subprocess.run

        def fake(argv, **kwargs):
            calls.append(argv)
            return FakeCompleted(0, "")

        check_pr_collisions.subprocess.run = fake
        try:
            paths_present(["a.py", "b.py"])
        finally:
            check_pr_collisions.subprocess.run = original
        self.assertEqual(sum("rev-parse" in call for call in calls), 1)


class PathsPresentLiveTests(unittest.TestCase):
    """Against real git, because the bug this covers was a wrong guess at it.

    `paths_present` first decided absence by matching `git`'s error text. Two
    messages mean absent -- "does not exist in" for a path not in the tree, and
    "exists on disk, but not in" for one that is also in the working copy --
    and only the first was matched. A newly added file therefore raised instead
    of reporting absent, which is precisely the case this report exists for.
    Mocks agreed with the wrong assumption, so these ask git directly.
    """

    def test_a_tracked_file_is_present(self) -> None:
        self.assertEqual(
            paths_present(["scripts/check_pr_collisions.py"], "HEAD"),
            ("scripts/check_pr_collisions.py",),
        )

    def test_a_path_absent_everywhere_is_absent(self) -> None:
        self.assertEqual(paths_present(["no/such/file.py"], "HEAD"), ())

    def test_a_file_on_disk_but_not_in_the_ref_is_absent(self) -> None:
        """The case that broke: present in the working copy, not in the ref."""
        with tempfile.NamedTemporaryFile(
            suffix=".py", dir=ROOT, delete=False
        ) as handle:
            created = Path(handle.name)
        try:
            relative = created.relative_to(ROOT).as_posix()
            self.assertEqual(paths_present([relative], "HEAD"), ())
        finally:
            created.unlink()

    def test_an_unresolvable_ref_raises(self) -> None:
        with self.assertRaises(RuntimeError):
            paths_present(["scripts/check_pr_collisions.py"], "origin/no-such-ref")


class BaseCollectionTests(unittest.TestCase):
    @contextlib.contextmanager
    def _gh(self, payload: str, calls: list | None = None):
        original = check_pr_collisions._run_gh

        def fake(argv, timeout=60):
            if calls is not None:
                calls.append(argv)
            return payload

        check_pr_collisions._run_gh = fake
        try:
            yield
        finally:
            check_pr_collisions._run_gh = original

    def test_bases_come_from_one_listing_call(self) -> None:
        calls: list = []
        with self._gh('[{"number": 5, "base": {"ref": "main"}}]', calls):
            self.assertEqual(collect_open_pull_request_bases("o/r"), {5: "main"})
        self.assertEqual(len(calls), 1)

    def test_a_pull_request_without_a_base_is_empty(self) -> None:
        with self._gh('[{"number": 5}]'):
            self.assertEqual(collect_open_pull_request_bases("o/r"), {5: ""})


class ClaimantsCliTests(unittest.TestCase):
    """The offline path: fixture claims plus an explicit present set."""

    def _run(self, argv):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "claims.json"
            fixture.write_text(
                json.dumps({"122": ["new.py"], "75": ["main.py"], "70": ["main.py"]}),
                encoding="utf-8",
            )
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = main(["--claims", str(fixture), *argv])
            return code, buffer.getvalue()

    def test_a_clean_path_reports_no_claimants(self) -> None:
        code, output = self._run(
            ["--claimants", "untouched.py", "--present", "untouched.py"]
        )
        self.assertEqual(code, 0)
        self.assertIn("No open pull request claims", output)

    def test_duplicated_work_is_surfaced(self) -> None:
        code, output = self._run(["--claimants", "new.py", "--present"])
        self.assertEqual(code, 0)
        self.assertIn("duplicate-work", output)
        self.assertIn("#122", output)

    def test_strict_fails_when_a_path_is_claimed(self) -> None:
        code, _ = self._run(["--claimants", "new.py", "--present", "--strict"])
        self.assertEqual(code, 1)

    def test_strict_succeeds_when_nothing_is_claimed(self) -> None:
        code, _ = self._run(
            ["--claimants", "free.py", "--present", "free.py", "--strict"]
        )
        self.assertEqual(code, 0)

    def test_the_default_contention_report_is_unchanged(self) -> None:
        code, output = self._run([])
        self.assertEqual(code, 0)
        self.assertIn("main.py", output)
        self.assertIn("claimed by 2", output)


if __name__ == "__main__":
    unittest.main()
