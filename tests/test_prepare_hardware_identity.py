import hashlib
from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from backend.hdm.adapters.steamos import prepare_hardware_identity as hardware


class HardwareIdentityTests(unittest.TestCase):
    def setUp(self):
        self.boot='12345678-1234-1234-1234-123456789abc'
        self.internal=SimpleNamespace(gpu_bdf='0000:64:00.0')
        self.external=SimpleNamespace(gpu_bdf='0000:08:00.0',verified=True,stable_id='gpd-g1:exact')
        self.targets=(hardware.RenderTarget('/dev/dri/renderD128',1,0,self.internal.gpu_bdf),
                      hardware.RenderTarget('/dev/dri/renderD129',2,1,self.external.gpu_bdf))
        self.drm=Mock(scan=Mock(return_value=(SimpleNamespace(name='card0',pci_bdf=self.internal.gpu_bdf),
                                             SimpleNamespace(name='card1',pci_bdf=self.external.gpu_bdf))))
        self.pci=Mock(scan_pci=Mock(return_value=()),scan_usb4_checked=Mock(return_value=((),True)))
        self.nodes=Mock(return_value=self.targets)
        self.boot_source=Mock(return_value=self.boot)
        self.source=hardware.PrepareHardwareIdentitySource(drm=self.drm,pci=self.pci,
            host=Mock(scan=Mock(return_value='host')),resolve_nodes=self.nodes,boot=self.boot_source,clock=lambda:1)

    def collect(self):
        with patch.object(hardware,'match_ally_x_analog_audio',return_value=self.internal), \
             patch.object(hardware,'match_gpd_g1',return_value=self.external):
            return self.source.collect(deadline=10)

    def test_double_inventory_and_wrapper_compatible_hash(self):
        result=self.collect()
        self.assertEqual(result.topology_hash,hashlib.sha256((self.boot+':gpd-g1:exact').encode()).hexdigest())
        self.assertEqual(result.boot_hash,hashlib.sha256(self.boot.encode()).hexdigest())
        self.assertEqual(result.internal,self.targets[0])
        self.assertEqual(self.nodes.call_count,2);self.assertEqual(self.drm.scan.call_count,2)
        self.assertEqual(self.boot_source.call_count,2)

    def test_hash_matches_existing_wrapper_with_stripped_raw_boot(self):
        from backend.hdm.delivery.gamescope_wrapper import _verified_egpu_binding_sha256
        raw=(self.boot+'\n').strip()  # Same normalization as wrapper _boot_identity.
        with patch('backend.hdm.adapters.steamos.drm.DrmDiscovery',return_value=self.drm), \
             patch('backend.hdm.adapters.steamos.pci.PciUsb4Discovery',return_value=self.pci), \
             patch('backend.hdm.profiles.gpd_g1.match_gpd_g1',return_value=self.external):
            expected=_verified_egpu_binding_sha256(raw)
        self.assertEqual(self.collect().topology_hash,expected)
        self.boot_source.return_value=self.boot+'\n'
        with self.assertRaises(ValueError):self.collect()

    def test_changed_boot_nodes_and_inventory_refused(self):
        self.boot_source.side_effect=[self.boot,'aaaaaaaa-1234-1234-1234-123456789abc']
        with self.assertRaises(ValueError):self.collect()
        self.boot_source.side_effect=None
        self.nodes.side_effect=[self.targets,(replace(self.targets[0],device=9),self.targets[1])]
        with self.assertRaises(ValueError):self.collect()
        self.nodes.side_effect=None
        self.pci.scan_usb4_checked.return_value=((),False)
        with self.assertRaises(ValueError):self.collect()

    def test_deadline_after_slow_final_boot_refused(self):
        now=[1]
        self.source.clock=lambda:now[0]
        calls=[0]
        def boot():
            calls[0]+=1
            if calls[0]==2:now[0]=11
            return self.boot
        self.boot_source.side_effect=boot
        with self.assertRaises(ValueError):self.collect()

    def test_invalid_deadline_or_clock_no_inventory(self):
        for deadline in (True,float('nan'),float('inf'),-1):
            with self.assertRaises(ValueError):self.source.collect(deadline=deadline)
        self.drm.scan.assert_not_called()
        self.source.clock=lambda:float('nan')
        with self.assertRaises(ValueError):self.collect()

    def test_unknown_and_unbounded_inventory_refused(self):
        self.pci.scan_pci.return_value=tuple(range(4097))
        with self.assertRaises(ValueError):self.collect()
        self.pci.scan_pci.return_value=()
        self.external.verified=False
        with self.assertRaises(ValueError):self.collect()


if __name__=='__main__':unittest.main()
