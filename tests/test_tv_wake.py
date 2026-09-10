import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'backend'))
from regear.domain.tv_wake import TvWakeEvidence, TvWakeState, TvWakeTrigger, TvWakeRequestEvidence, assess_tv_wake, request_tv_wake
class TvWakeTests(unittest.TestCase):
 def test_fail_closed_states_and_verified_postcheck(self):
  self.assertEqual(assess_tv_wake(TvWakeEvidence(False,True,True)),TvWakeState.UNSUPPORTED)
  self.assertEqual(assess_tv_wake(TvWakeEvidence(None,True,True)),TvWakeState.UNAVAILABLE)
  self.assertEqual(assess_tv_wake(TvWakeEvidence(True,True,True)),TvWakeState.ATTEMPT_ELIGIBLE)
  self.assertEqual(assess_tv_wake(TvWakeEvidence(True,True,True,True,False,True)),TvWakeState.ATTEMPTED_UNVERIFIED)
  self.assertEqual(assess_tv_wake(TvWakeEvidence(True,True,True,True,True,True)),TvWakeState.VERIFIED_AWAKE)
 def test_request_intents_require_idle_freshness_and_deduplicate(self):
  attach=TvWakeRequestEvidence(TvWakeTrigger.ELIGIBLE_ATTACH,True,True,True)
  self.assertTrue(request_tv_wake(attach))
  self.assertFalse(request_tv_wake(TvWakeRequestEvidence(TvWakeTrigger.VERIFIED_CONTROLLER,True,True,True)))
  self.assertTrue(request_tv_wake(TvWakeRequestEvidence(TvWakeTrigger.VERIFIED_CONTROLLER,True,True,True,True)))
  self.assertFalse(request_tv_wake(TvWakeRequestEvidence(TvWakeTrigger.ELIGIBLE_ATTACH,False,True,True)))
  self.assertFalse(request_tv_wake(TvWakeRequestEvidence(TvWakeTrigger.ELIGIBLE_ATTACH,True,True,True,False,True)))
if __name__=='__main__': unittest.main()
