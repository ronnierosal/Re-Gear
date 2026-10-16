import unittest
from unittest.mock import Mock,patch
from regear.delivery.usb4_native_diagnostic import read_usb4_native_diagnostic, unavailable
from regear.application.usb4_native_evidence import EvidenceReport
from regear.ports.usb4_native_evidence import Fact,NativeSnapshot

class DiagnosticTests(unittest.TestCase):
    def test_categories_only_no_private_identity_or_eligibility(self):
        collector=Mock(return_value=EvidenceReport('evidence.observed',NativeSnapshot(captured_at=10,api=Fact.OBSERVED)))
        result=read_usb4_native_diagnostic(collector=collector)
        self.assertEqual('observed',result['api']);self.assertEqual('unknown',result['static_permission'])
        self.assertEqual('observed',result['plugin_context']);self.assertFalse(result['hardware_write']);self.assertFalse(result['mutation_allowed'])
        self.assertNotIn('captured_at',result);self.assertNotIn('uid',result);self.assertNotIn('token',result)
    def test_import_or_reader_error_is_categorical_not_startup_failure(self):
        with patch('regear.delivery.usb4_native_diagnostic.create_reader',side_effect=ImportError('private path')):
            result=read_usb4_native_diagnostic()
        self.assertEqual('evidence.error',result['code']);self.assertNotIn('private',repr(result))
    def test_unavailable_never_constructs_reader(self):
        with patch('regear.delivery.usb4_native_diagnostic.create_reader') as factory:
            result=unavailable();factory.assert_not_called()
        self.assertFalse(result['available']);self.assertEqual('unknown',result['plugin_context'])
    def test_context_category_never_becomes_static_grant_permission(self):
        collector=Mock(return_value=EvidenceReport('evidence.observed',NativeSnapshot(captured_at=10)))
        for uid,expected in ((0,'root'),(1000,'nonroot'),(None,'unknown')):
            with patch('regear.delivery.usb4_native_diagnostic.os.geteuid',return_value=uid,create=True):
                result=read_usb4_native_diagnostic(collector=collector)
            self.assertEqual(expected,result['process_identity']);self.assertEqual('unknown',result['static_permission'])
    def test_concurrent_request_never_constructs_another_reader(self):
        from regear.delivery.usb4_native_diagnostic import _READ_LOCK
        with _READ_LOCK,patch('regear.delivery.usb4_native_diagnostic.create_reader') as factory:
            self.assertEqual('usb4_diagnostic.busy',read_usb4_native_diagnostic()['code']);factory.assert_not_called()

if __name__=='__main__':unittest.main()
