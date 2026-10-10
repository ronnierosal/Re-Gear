import json
import unittest
from unittest.mock import Mock
from regear.adapters.steamos.usb4_attachment_observer import Usb4AttachmentObservation as Observation
from regear.delivery.usb4_waiting_observation import Usb4WaitingObservation
class ProjectionTests(unittest.TestCase):
    def test_nonce_private_dedup_and_transient_withdrawal(self):
        observer=Mock();service=Usb4WaitingObservation(observer)
        identity=('private-uuid','private-path')
        observer.observe.return_value=Observation('unauthorized',identity);first=service.observe()
        self.assertRegex(first['notice_key'],r'^uw-[0-9a-f]{32}$')
        self.assertEqual(set(first),{'schema_version','state','notice_key'})
        self.assertNotIn('private',json.dumps(first))
        for state in ('unknown','ambiguous'):
            observer.observe.return_value=Observation(state);self.assertIsNone(service.observe()['notice_key'])
            observer.observe.return_value=Observation('unauthorized',identity);self.assertEqual(service.observe(),first)
    def test_authorized_absence_and_change_retire(self):
        observer=Mock();service=Usb4WaitingObservation(observer)
        observer.observe.return_value=Observation('unauthorized',('one',));first=service.observe()['notice_key']
        for state in ('none','authorized'):
            observer.observe.return_value=Observation(state);self.assertIsNone(service.observe()['notice_key'])
            observer.observe.return_value=Observation('unauthorized',('one',));new=service.observe()['notice_key'];self.assertNotEqual(first,new);first=new
        observer.observe.return_value=Observation('unauthorized',('two',));self.assertNotEqual(first,service.observe()['notice_key'])
    def test_missing_malformed_error_fail_closed(self):
        observer=Mock();service=Usb4WaitingObservation(observer)
        for value in (None,{},Observation('invalid'),Observation('unauthorized')):
            observer.observe.return_value=value;self.assertEqual(service.observe(),{'schema_version':1,'state':'unknown','notice_key':None})
        observer.observe.side_effect=RuntimeError('private secret');self.assertEqual(service.observe()['state'],'unknown')
