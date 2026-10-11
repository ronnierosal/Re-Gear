import unittest
from dataclasses import replace
from backend.regear.domain.display_modes import Binding, Mode
from backend.regear.domain.display_mode_cycle import CycleController, Receipt
from tests.test_display_modes import evidence


class ControllerTests(unittest.TestCase):
    def start(self):
        c=CycleController();e=evidence();op=c.begin(e,'resolution','request',10);return c,e,op
    def test_revalidate_before_dispatch_and_singleflight(self):
        c,e,o=self.start()
        with self.assertRaises(ValueError):c.begin(e,'refresh','second',10)
        with self.assertRaises(ValueError):c.dispatch(replace(e,binding=Binding('other','session','provider',1)),10)
        self.assertEqual(c.operation.state,'revoked')
    def test_current_change_revokes(self):
        c,e,o=self.start()
        with self.assertRaises(ValueError):c.dispatch(replace(e,current=e.modes[1]),10)
    def test_acceptance_is_not_commit_and_verified_readback(self):
        c,e,o=self.start();c.dispatch(e,10);self.assertEqual(c.operation.state,'pending')
        r=Receipt('request',e.binding,o.target,11,2)
        self.assertEqual(c.readback(replace(e,current=o.target,observed_at=11,sequence=2),r,11).state,'committed')
    def test_wrong_request_or_readback_is_recovery(self):
        for request in ['wrong',None]:
            c,e,o=self.start();c.dispatch(e,10)
            with self.assertRaises(ValueError):c.readback(replace(e,current=o.target,observed_at=11,sequence=2),Receipt(request,e.binding,o.target,11,2),11)
            self.assertEqual(c.operation.state,'recovery_required')
    def test_old_receipt_and_external_change(self):
        c,e,o=self.start();c.dispatch(e,10)
        with self.assertRaises(ValueError):c.readback(e,Receipt('request',e.binding,o.target,10,1),10)
        self.assertEqual(c.operation.state,'recovery_required')
    def test_loss_and_ambiguous_submission(self):
        c,e,o=self.start();c.dispatch(e,10);c.uncertain()
        self.assertEqual(c.operation.state,'recovery_required')
        with self.assertRaises(ValueError):c.rollback(replace(e,current=o.target),10)
    def test_verified_rollback_requires_qualified_fresh_ownership(self):
        c,e,o=self.start();c.dispatch(e,10);after=replace(e,current=o.target,observed_at=11,sequence=2)
        c.readback(after,Receipt('request',e.binding,o.target,11,2),11)
        with self.assertRaises(ValueError):c.rollback(replace(after,rollback_qualified=False),11)
        self.assertEqual(c.rollback(after,11).state,'rollback_pending')
        back=replace(e,observed_at=12,sequence=3)
        self.assertEqual(c.readback(back,Receipt('request',e.binding,o.previous,12,3),12).state,'rolled_back')
    def test_blind_restore_refused_after_external_change(self):
        c,e,o=self.start();c.dispatch(e,10);after=replace(e,current=o.target,observed_at=11,sequence=2)
        c.readback(after,Receipt('request',e.binding,o.target,11,2),11)
        with self.assertRaises(ValueError):c.rollback(replace(after,current=e.modes[1]),11)
    def test_cancel_before_and_after_dispatch(self):
        c,e,o=self.start();self.assertEqual(c.cancel().state,'cancelled')
        with self.assertRaises(ValueError):c.dispatch(e,10)
        c,e,o=self.start();c.dispatch(e,10);self.assertEqual(c.cancel().state,'recovery_required')
    def test_request_replay_denied(self):
        c,e,o=self.start();c.cancel()
        with self.assertRaises(ValueError):c.begin(e,'resolution','request',10)

    def test_ambiguous_rollback_retains_restore_intent(self):
        c,e,o=self.start();c.dispatch(e,10);after=replace(e,current=o.target,observed_at=11,sequence=2)
        c.readback(after,Receipt('request',e.binding,o.target,11,2),11);c.rollback(after,11);c.uncertain()
        with self.assertRaises(ValueError):c.readback(replace(after,observed_at=12,sequence=3),Receipt('request',e.binding,o.target,12,3),12)
        back=replace(e,observed_at=12,sequence=3)
        self.assertEqual(c.readback(back,Receipt('request',e.binding,o.previous,12,3),12).state,'rolled_back')
    def test_rollback_loss_cannot_be_rearmed_by_external_aba(self):
        c,e,o=self.start();c.dispatch(e,10);after=replace(e,current=o.target,observed_at=11,sequence=2)
        c.readback(after,Receipt('request',e.binding,o.target,11,2),11)
        with self.assertRaises(ValueError):c.rollback(replace(after,current=e.modes[1]),11)
        with self.assertRaises(ValueError):c.rollback(after,11)
    def test_unknown_rollback_qualification_blocks_plan(self):
        with self.assertRaises(ValueError):CycleController().begin(replace(evidence(),rollback_qualified=None),'resolution','r',10)
    def test_dispatch_revalidates_all_gates_and_modes(self):
        for changes in ({'available':False},{'game_idle':None},{'lifecycle_idle':False},{'admitted':False},{'observed_at':0},{'rollback_qualified':None}):
            c,e,o=self.start()
            with self.subTest(changes=changes),self.assertRaises(ValueError):c.dispatch(replace(e,**changes),10)
            self.assertEqual(c.operation.state,'revoked')
    def test_provider_loss_during_readback_requires_recovery(self):
        c,e,o=self.start();c.dispatch(e,10)
        with self.assertRaises(ValueError):c.readback(replace(e,available=False),Receipt('request',e.binding,o.target,11,2),11)
        self.assertEqual(c.operation.state,'recovery_required')
    def test_external_change_cannot_rearm_through_new_receipt(self):
        c,e,o=self.start();c.dispatch(e,10);after=replace(e,current=o.target,observed_at=11,sequence=2)
        c.readback(after,Receipt('request',e.binding,o.target,11,2),11)
        with self.assertRaises(ValueError):c.rollback(replace(after,current=e.modes[1],sequence=3),11)
        later=replace(after,observed_at=12,sequence=4)
        with self.assertRaises(ValueError):c.readback(later,Receipt('request',e.binding,o.target,12,4),12)
        with self.assertRaises(ValueError):c.rollback(later,12)

    def test_external_readback_and_provider_loss_revoke_receipt_recovery(self):
        for changes in ({'current':evidence().modes[1]},{'available':False},{'binding':Binding('output','new-session','provider',1)}):
            c,e,o=self.start();c.dispatch(e,10)
            with self.assertRaises(ValueError):c.readback(replace(e,observed_at=11,sequence=2,**changes),Receipt('request',e.binding,o.target,11,2),11)
            later=replace(e,current=o.target,observed_at=12,sequence=3)
            with self.assertRaises(ValueError):c.readback(later,Receipt('request',e.binding,o.target,12,3),12)
    def test_ambiguous_submission_can_only_resolve_by_owned_committed_readback(self):
        c,e,o=self.start();c.dispatch(e,10);c.uncertain()
        after=replace(e,current=o.target,observed_at=11,sequence=2)
        self.assertEqual(c.readback(after,Receipt('request',e.binding,o.target,11,2),11).state,'committed')
