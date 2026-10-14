import unittest
from dataclasses import replace
from fractions import Fraction
from backend.regear.domain.display_modes import Binding, Mode, Observation, cycle


def evidence(**kw):
    modes=(Mode('a',1280,720,60,1),Mode('b',1280,720,60000,1001),Mode('c',1920,1080,60,1))
    return replace(Observation(Binding('output','session','provider',1),modes,modes[0],10,1,True,True,True,True,True),**kw)


class ModeTests(unittest.TestCase):
    def test_exact_refresh_not_rounded(self):
        e=evidence(); self.assertNotEqual(e.modes[0].hz,e.modes[1].hz)
        self.assertEqual(e.modes[1].hz,Fraction(60000,1001))
        self.assertEqual(cycle(e,'refresh',10),e.modes[1])
    def test_resolution_selects_supported_tuple(self):
        e=evidence(); self.assertEqual(cycle(e,'resolution',10),e.modes[2])
        self.assertIn(cycle(e,'resolution',10),e.modes)
    def test_order_is_deterministic(self):
        e=evidence(); self.assertEqual(cycle(e,'resolution',10),cycle(replace(e,modes=tuple(reversed(e.modes))),'resolution',10))
    def test_unavailable_evidence_denies(self):
        e=evidence()
        for changes in ({'modes':()}, {'current':None},{'available':False},{'game_idle':None},{'lifecycle_idle':False},{'admitted':False},{'observed_at':0},{'observed_at':11},{'modes':e.modes+(e.modes[0],)},{'modes':e.modes+(Mode('x',1280,720,120,2),)}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):cycle(replace(e,**changes),'refresh',10)
    def test_no_cartesian_product_or_defaults(self):
        e=evidence(modes=(Mode('a',1280,720,60,1),Mode('c',1920,1080,120,1)))
        self.assertEqual(cycle(e,'resolution',10),e.modes[1])
        with self.assertRaises(ValueError):cycle(e,'refresh',10)
    def test_malformed_modes(self):
        for args in [('a',True,720,60,1),('a',1280,720,60,0),('',1280,720,60,1),('a',1280,720,60.0,1)]:
            with self.assertRaises(ValueError):Mode(*args)
    def test_unknown_axis_and_nonfinite_time(self):
        for axis,now in [('fps',10),('refresh',float('nan')),('refresh',True)]:
            with self.assertRaises(ValueError):cycle(evidence(),axis,now)
