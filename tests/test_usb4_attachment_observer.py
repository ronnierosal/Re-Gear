import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from regear.adapters.steamos.usb4_attachment_observer import Usb4AttachmentObserver

class ObserverRegression(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.root=self.base/'bus';self.root.mkdir()
        self.devices=self.base/'devices';self.devices.mkdir()
        self.observer=Usb4AttachmentObserver(self.root,devices_root=self.devices)
    def router(self,name='0-1',auth='0',uuid='11111111-1111-1111-1111-111111111111'):
        p=self.devices/name;p.mkdir();(p/'authorized').write_text(auth);(p/'unique_id').write_text(uuid)
        (self.root/name).symlink_to(p,target_is_directory=True);return p
    def test_host_excluded_and_coherent_absence(self):
        self.router('0-0'); self.assertEqual(self.observer.observe().state,'none')
    def test_single_unauthorized_and_authorized(self):
        p=self.router(); self.assertEqual(self.observer.observe().state,'unauthorized')
        (p/'authorized').write_text('1');self.assertEqual(self.observer.observe().state,'authorized')
    def test_two_routers_ambiguous(self):
        self.router();self.router('0-2');self.assertEqual(self.observer.observe().state,'ambiguous')
    def test_unknown_auth_uuid_and_missing(self):
        p=self.router()
        for text in ('2','', 'false','0'*129):
            (p/'authorized').write_text(text);self.assertEqual(self.observer.observe().state,'unknown')
        (p/'authorized').write_text('0');(p/'unique_id').unlink();self.assertEqual(self.observer.observe().state,'unknown')
    def test_missing_tree_not_absent(self):
        self.assertEqual(Usb4AttachmentObserver(self.base/'missing').observe().state,'unknown')
    def test_escape_attribute_symlink_and_entry_bounds(self):
        p=self.router();(p/'authorized').unlink();(p/'authorized').symlink_to(self.base/'outside')
        self.assertEqual(self.observer.observe().state,'unknown')
        (self.root/'0-1').unlink();outside=self.base/'outside-dir';outside.mkdir();(self.root/'0-1').symlink_to(outside)
        self.assertEqual(self.observer.observe().state,'unknown')
        (self.root/'0-1').unlink()
        for i in range(65): (self.root/f'domain{i}').mkdir()
        self.assertEqual(self.observer.observe().state,'unknown')
    def test_change_between_scans_withdraws(self):
        p=self.router();real=self.observer._scan;calls=0
        def scan(deadline):
            nonlocal calls
            result=real(deadline);calls+=1
            if calls==1:(p/'authorized').write_text('1')
            return result
        with patch.object(self.observer,'_scan',side_effect=scan):self.assertEqual(self.observer.observe().state,'unknown')
    def test_no_writes_or_command_side_effects(self):
        p=self.router();before={x.name:x.read_bytes() for x in p.iterdir()}
        with patch('subprocess.Popen',side_effect=AssertionError('command')):
            self.assertEqual(self.observer.observe().state,'unauthorized')
        self.assertEqual(before,{x.name:x.read_bytes() for x in p.iterdir()})
