"""Guarded restoration, using the same inert fixture as Apply contracts."""

import unittest

from test_controller_target_session import Fixture
from backend.regear.domain.controller_target_session import Authority, Manager, Phase
from backend.regear.ports.controller_targets import Dispatch


class RestoreTests(unittest.TestCase):
    def test_restore_is_requested_then_separately_verified(self):
        f = Fixture()
        self.assertEqual(Phase.EFFECTIVE, f.effective())
        r = f.session.prepare_restore()
        self.assertEqual(("keys", "pad-a", "keys", "pointer"), r.desired)
        self.assertEqual(Phase.RESTORE_REQUESTED, f.session.dispatch(r))
        self.assertTrue(f.session.rollback_retained)
        f.observe(targets=r.desired)
        self.assertEqual(Phase.RESTORED, f.session.verify())
        self.assertFalse(f.session.rollback_retained)
        self.assertEqual(2, len(f.calls))

    def test_takeover_reconnect_withdrawal_or_external_targets_prohibit_rollback(self):
        for changes in ({"epoch": "new"}, {"composite": "new"},
                        {"generation": 2},
                        {"authority": Authority(Manager.OS, "grant")},
                        {"authority": Authority(Manager.REGEAR, "replacement")},
                        {"targets": ("pad-a",)}, {"idle": False},
                        {"visible": False}):
            with self.subTest(changes=changes):
                f = Fixture()
                f.effective()
                f.observe(**changes)
                self.assertEqual(Phase.RECOVERY_REQUIRED, f.session.close())
                self.assertTrue(f.session.rollback_retained)
                self.assertEqual(1, len(f.calls))

    def test_close_needs_readback_and_failed_restore_keeps_evidence(self):
        for result in (Dispatch.REFUSED, None):
            f = Fixture()
            f.effective()
            f.dispatch = result
            self.assertEqual(Phase.RECOVERY_REQUIRED, f.session.close())
            self.assertTrue(f.session.rollback_retained)
        f = Fixture()
        f.effective()
        self.assertEqual(Phase.RESTORE_REQUESTED, f.session.close())
        self.assertTrue(f.session.rollback_retained)
        self.assertEqual(Phase.RECOVERY_REQUIRED, f.session.verify())
        self.assertTrue(f.session.rollback_retained)

    def test_restore_rechecks_after_preparation_and_is_single_use(self):
        f = Fixture()
        f.effective()
        r = f.session.prepare_restore()
        f.observe(targets=("pad-a",))
        with self.assertRaises(ValueError):
            f.session.dispatch(r)
        self.assertEqual(1, len(f.calls))
        with self.assertRaises(ValueError):
            f.session.dispatch(r)

    def test_close_before_apply_is_local_and_cancels_prepared_request(self):
        f = Fixture()
        r = f.prepare()
        self.assertEqual(Phase.CLOSED, f.session.close())
        with self.assertRaises(ValueError):
            f.session.dispatch(r)
        self.assertEqual([], f.calls)

    def test_restore_timeout_is_uncertain_and_cannot_be_retried(self):
        f = Fixture()
        f.effective()
        def partial_submission():
            raise TimeoutError()
        f.on_write = partial_submission
        self.assertEqual(Phase.RECOVERY_REQUIRED, f.session.close())
        self.assertTrue(f.session.rollback_retained)
        self.assertEqual(Phase.RECOVERY_REQUIRED, f.session.close())
        self.assertEqual(2, len(f.calls))

    def test_restore_rejects_changed_kind_or_missing_original_type_evidence(self):
        from test_controller_target_session import TYPES
        from backend.regear.domain.controller_target_session import TargetType
        for types in (TYPES[1:], (TargetType("pad-a", False),) + TYPES[1:]):
            f = Fixture()
            f.effective()
            f.observe(supported=types, compatible=("pad-b",))
            self.assertEqual(Phase.RECOVERY_REQUIRED, f.session.close())
            self.assertEqual(1, len(f.calls))

    def test_restore_callback_cannot_reenter_apply_restore_verify_or_close(self):
        f = Fixture()
        f.effective()
        r = f.session.prepare_restore()
        def reenter():
            for action in (f.session.prepare_apply, f.session.prepare_restore,
                           f.session.verify, f.session.close):
                with self.assertRaises(RuntimeError):
                    action()
        f.on_write = reenter
        self.assertEqual(Phase.RESTORE_REQUESTED, f.session.dispatch(r))
        self.assertEqual(2, len(f.calls))

    def test_restore_request_expires_without_another_write(self):
        f = Fixture()
        f.effective()
        r = f.session.prepare_restore()
        f.now += 10
        f.observe()
        with self.assertRaises(ValueError):
            f.session.dispatch(r)
        self.assertEqual(Phase.RECOVERY_REQUIRED, f.session.phase)
        self.assertTrue(f.session.rollback_retained)
        self.assertEqual(1, len(f.calls))


if __name__ == "__main__":
    unittest.main()
