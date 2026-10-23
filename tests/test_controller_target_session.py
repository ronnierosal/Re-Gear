"""Inert target transaction contracts; all identifiers and ports are fictional."""

import unittest
from dataclasses import replace

from backend.regear.application.controller_target_session import TargetSession
from backend.regear.domain.controller_target_session import (
    Authority, Frame, Manager, Phase, TargetType,
)
from backend.regear.ports.controller_targets import Dispatch


TYPES = (TargetType("pad-a", True), TargetType("pad-b", True),
         TargetType("keys", False), TargetType("pointer", False))


class Fixture:
    def __init__(self):
        self.now = 100.0
        self.frame = Frame("epoch", "composite", 1,
                           Authority(Manager.REGEAR, "grant"),
                           ("keys", "pad-a", "keys", "pointer"), TYPES,
                           ("pad-a", "pad-b"), True, True, True, True, self.now)
        self.calls = []
        self.on_write = None
        self.on_read = None
        self.dispatch = Dispatch.SUBMITTED
        self.session = TargetSession(self, self, lambda: self.now, TYPES)

    def read(self, deadline):
        if self.on_read:
            self.on_read()
        return self.frame

    def set_targets(self, request):
        self.calls.append(request)
        if self.on_write:
            self.on_write()
        return self.dispatch

    def observe(self, **changes):
        self.frame = replace(self.frame, **({"observed_at": self.now} | changes))

    def prepare(self):
        self.session.stage("composite", "pad-b")
        return self.session.prepare_apply()

    def effective(self):
        request = self.prepare()
        self.session.dispatch(request)
        self.observe(targets=request.desired)
        return self.session.verify()


class SelectionTests(unittest.TestCase):
    def test_stage_is_local_and_choices_intersect_three_verified_sources(self):
        f = Fixture()
        f.on_read = lambda: self.fail("stage must not read")
        f.session.stage("composite", "pad-b")
        self.assertEqual([], f.calls)
        f.on_read = None
        f.observe(compatible=("pad-a",))
        with self.assertRaises(ValueError):
            f.session.prepare_apply()
        self.assertEqual([], f.calls)

    def test_only_gamepad_slot_changes_and_auxiliary_multiplicity_survives(self):
        f = Fixture()
        r = f.prepare()
        self.assertEqual(("keys", "pad-b", "keys", "pointer"), r.desired)
        self.assertEqual(f.frame.targets, r.original)
        self.assertEqual(Phase.REQUESTED, f.session.dispatch(r))
        self.assertNotEqual(Phase.EFFECTIVE, f.session.phase)
        f.observe(targets=r.desired)
        self.assertEqual(Phase.EFFECTIVE, f.session.verify())

    def test_invalid_baselines_and_duplicate_catalogue_fail_before_write(self):
        for changes in (
            {"complete": False}, {"identity_verified": False},
            {"targets": ("keys",)}, {"targets": ("pad-a", "pad-a")},
            {"targets": ("pad-a", "pad-b")},
            {"targets": ("pad-a", "unknown")},
            {"supported": TYPES + (TYPES[0],)},
            {"supported": TYPES + (TargetType("pad-a", False),)},
            {"compatible": ("pad-b", "pad-b")},
        ):
            with self.subTest(changes=changes):
                f = Fixture()
                f.observe(**changes)
                with self.assertRaises(ValueError):
                    f.prepare()
                self.assertEqual([], f.calls)

    def test_os_other_unknown_or_missing_authority_are_passive(self):
        for authority in (Authority(Manager.OS, "grant"),
                          Authority(Manager.OTHER, "grant"),
                          Authority(Manager.UNKNOWN, "grant"),
                          Authority(Manager.REGEAR, "")):
            f = Fixture()
            f.observe(authority=authority)
            with self.assertRaises(ValueError):
                f.prepare()
            self.assertEqual([], f.calls)

    def test_allowlist_and_setter_ids_are_not_labels_or_object_paths(self):
        f = Fixture()
        f.session = TargetSession(f, f, lambda: f.now, TYPES[:1])
        with self.assertRaises(ValueError):
            f.prepare()
        for identifier in ("/device/pad", "Marketing Pad", "", "a\n"):
            with self.assertRaises(ValueError):
                TargetType(identifier, True)


class AdmissionTests(unittest.TestCase):
    def test_fresh_recheck_rejects_identity_authority_generation_and_game_changes(self):
        for changes in (
            {"epoch": "replacement"}, {"composite": "replacement"},
            {"generation": 2}, {"authority": Authority(Manager.REGEAR, "new")},
            {"visible": False}, {"idle": False}, {"idle": None},
            {"targets": ("pad-a",)}, {"complete": False},
            {"compatible": ("pad-a",)},
        ):
            with self.subTest(changes=changes):
                f = Fixture()
                r = f.prepare()
                f.observe(**changes)
                with self.assertRaises(ValueError):
                    f.session.dispatch(r)
                self.assertEqual([], f.calls)

    def test_request_expiry_and_stale_or_future_evidence(self):
        for elapsed in (10.0, 11.0, -1.0, float("nan")):
            f = Fixture()
            r = f.prepare()
            f.now += elapsed
            with self.assertRaises(ValueError):
                f.session.dispatch(r)
            self.assertEqual([], f.calls)
        for stamp in (89.0, 101.0, float("nan")):
            f = Fixture()
            f.observe(observed_at=stamp)
            with self.assertRaises(ValueError):
                f.prepare()

    def test_duplicate_forged_and_other_session_requests_cannot_dispatch(self):
        f = Fixture()
        r = f.prepare()
        with self.assertRaises(ValueError):
            f.session.dispatch(replace(r))
        other = Fixture()
        other.prepare()
        with self.assertRaises(ValueError):
            other.session.dispatch(r)
        f.session.dispatch(r)
        with self.assertRaises(ValueError):
            f.session.dispatch(r)
        self.assertEqual(1, len(f.calls))

    def test_reentrant_apply_restore_and_close_refused_without_deadlock(self):
        f = Fixture()
        r = f.prepare()
        def reenter():
            for action in (lambda: f.session.dispatch(r), f.session.prepare_restore,
                           f.session.close, f.session.verify):
                with self.assertRaises(RuntimeError):
                    action()
        f.on_write = reenter
        self.assertEqual(Phase.REQUESTED, f.session.dispatch(r))
        self.assertEqual(1, len(f.calls))

    def test_exception_or_late_completion_is_uncertain_and_never_replayed(self):
        for callback in (lambda: (_ for _ in ()).throw(TimeoutError()),
                         lambda: setattr(f, "now", f.now + 10)):
            f = Fixture()
            r = f.prepare()
            f.on_write = callback
            self.assertEqual(Phase.RECOVERY_REQUIRED, f.session.dispatch(r))
            self.assertTrue(f.session.rollback_retained)
            with self.assertRaises(ValueError):
                f.session.prepare_restore()
            self.assertEqual(1, len(f.calls))

    def test_mismatched_readback_never_reports_effective(self):
        f = Fixture()
        f.session.dispatch(f.prepare())
        self.assertEqual(Phase.RECOVERY_REQUIRED, f.session.verify())
        self.assertTrue(f.session.rollback_retained)

    def test_concurrent_operation_is_refused_while_writer_owns_session(self):
        from threading import Event, Thread
        f = Fixture()
        r = f.prepare()
        entered, release = Event(), Event()
        def block():
            entered.set()
            if not release.wait(2):
                raise TimeoutError()
        f.on_write = block
        worker = Thread(target=lambda: f.session.dispatch(r))
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            with self.assertRaises(RuntimeError):
                f.session.prepare_apply()
            with self.assertRaises(RuntimeError):
                f.session.close()
        finally:
            release.set()
            worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(1, len(f.calls))
        self.assertEqual(Phase.REQUESTED, f.session.phase)

    def test_slow_reader_cannot_extend_request_start_expiry(self):
        f = Fixture()
        r = f.prepare()
        f.on_read = lambda: setattr(f, "now", f.now + 10)
        with self.assertRaises(ValueError):
            f.session.dispatch(r)
        self.assertEqual([], f.calls)

    def test_explicit_pre_submission_refusal_can_be_retried_but_not_replayed(self):
        f = Fixture()
        r = f.prepare()
        f.dispatch = Dispatch.REFUSED
        self.assertEqual(Phase.STAGED, f.session.dispatch(r))
        self.assertFalse(f.session.rollback_retained)
        with self.assertRaises(ValueError):
            f.session.dispatch(r)
        f.dispatch = Dispatch.SUBMITTED
        self.assertEqual(Phase.REQUESTED, f.session.dispatch(f.prepare()))

    def test_cancellation_after_writer_entry_retains_evidence_and_blocks_apply(self):
        from asyncio import CancelledError
        f = Fixture()
        r = f.prepare()
        def cancel():
            raise CancelledError()
        f.on_write = cancel
        with self.assertRaises(CancelledError):
            f.session.dispatch(r)
        self.assertEqual(Phase.RECOVERY_REQUIRED, f.session.phase)
        self.assertTrue(f.session.rollback_retained)
        with self.assertRaises(ValueError):
            f.session.prepare_apply()
        self.assertEqual(1, len(f.calls))

    def test_deadline_crossing_after_read_is_refused_before_writer(self):
        f = Fixture()
        r = f.prepare()
        f.now = 109.9
        f.observe()
        times = iter((109.9, 110.0, 110.0))
        f.session._clock = lambda: next(times)
        with self.assertRaises(ValueError):
            f.session.dispatch(r)
        self.assertEqual([], f.calls)


if __name__ == "__main__":
    unittest.main()
