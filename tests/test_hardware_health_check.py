import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from regear.domain.hardware_health_check import *
class T(unittest.TestCase):
 def test_categorical_calm_results(self):
  self.assertEqual(assess_health_check(HealthCheckInput('link',False,None))[0],HealthCheckState.UNKNOWN)
  self.assertEqual(assess_health_check(HealthCheckInput('link',True,True))[0],HealthCheckState.HEALTHY)
  self.assertEqual(assess_health_check(HealthCheckInput('link',True,False))[0],HealthCheckState.ATTENTION)
