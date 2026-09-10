import unittest
from dataclasses import replace

from backend.hdm.adapters.steamos.host import HostRecord
from backend.hdm.adapters.steamos.drm import DrmCardRecord, DrmConnectorRecord
from backend.hdm.adapters.steamos.pci import PciDeviceRecord
from backend.hdm.profiles.ally_x_audio import match_ally_x_analog_audio


class AllyXAudioTests(unittest.TestCase):
    def setUp(self):
        self.host = HostRecord('ASUSTeK COMPUTER INC.', 'ROG Ally X RC72LA', 'RC72LA')
        self.gpu = PciDeviceRecord('0000:64:00.0', '0x1002', '0x15bf', '0x030000',
            'amdgpu', ('0000:00:08.1', '0000:64:00.0'))
        self.audio = PciDeviceRecord('0000:64:00.6', '0x1022', '0x15e3', '0x040300',
            'snd_hda_intel', ('0000:00:08.1', '0000:64:00.6'))
        self.card = DrmCardRecord('card4', self.gpu.bdf, self.gpu.vendor, self.gpu.device,
            True, 'amdgpu', (DrmConnectorRecord('card4', 'eDP-3', 'connected', 'enabled'),))

    def match(self, host=None, cards=None, devices=None):
        return match_ally_x_analog_audio(self.host if host is None else host,
            (self.card,) if cards is None else cards,
            (self.gpu, self.audio) if devices is None else devices)

    def test_observed_relationship(self):
        result = self.match()
        self.assertEqual(result.audio_bdf, self.audio.bdf)
        self.assertEqual(result.gpu_bdf, self.gpu.bdf)
        self.assertEqual(result.upstream, self.gpu.ancestry[:-1])
        self.assertFalse(hasattr(result, 'disconnect_clearance'))

    def test_addresses_and_function_numbers_are_not_hardcoded(self):
        gpu = replace(self.gpu, bdf='0001:45:03.2', ancestry=('0001:00:01.0', '0001:45:03.2'))
        audio = replace(self.audio, bdf='0001:45:03.4', ancestry=('0001:00:01.0', '0001:45:03.4'))
        result = self.match(cards=(replace(self.card, pci_bdf=gpu.bdf),), devices=(gpu,audio))
        self.assertEqual(result.audio_bdf, audio.bdf)

    def test_other_host_missing_gpu_and_unknown_boot_reject(self):
        self.assertIsNone(self.match(host=replace(self.host, product_name='unknown')))
        for card in (replace(self.card, boot_vga=None), replace(self.card, boot_vga=1),
                     replace(self.card, connectors=()), replace(self.card, device='0xffff')):
            self.assertIsNone(self.match(cards=(card,)))
        self.assertIsNone(self.match(devices=(self.audio,)))

    def test_same_vendor_or_not_external_is_insufficient(self):
        for audio in (replace(self.audio, device='0x1640'),
                      replace(self.audio, driver=''), replace(self.audio, class_code='0x030000'),
                      replace(self.audio, bdf='0000:65:00.6', ancestry=('0000:00:08.1','0000:65:00.6')),
                      replace(self.audio, ancestry=('0000:00:09.1', self.audio.bdf))):
            self.assertIsNone(self.match(devices=(self.gpu, audio)))

    def test_ambiguous_and_malformed_inventory_reject(self):
        other = replace(self.audio, bdf='0000:64:00.5', ancestry=('0000:00:08.1','0000:64:00.5'))
        for devices in ((self.gpu,self.audio,self.audio), (self.gpu,self.audio,other), (),
                        (replace(self.gpu, ancestry=()),self.audio),
                        (replace(self.gpu, ancestry=(self.gpu.bdf,)),self.audio)):
            self.assertIsNone(self.match(devices=devices))
        self.assertIsNone(self.match(cards=(self.card,self.card)))
        self.assertIsNone(self.match(cards=(self.card,replace(self.card,pci_bdf='0000:65:00.0'))))

    def test_hdmi_sibling_does_not_replace_analog(self):
        hdmi = replace(self.audio,bdf='0000:64:00.1',vendor='0x1002',device='0x1640',
                       ancestry=('0000:00:08.1','0000:64:00.1'))
        self.assertIsNone(self.match(devices=(self.gpu,hdmi)))
        self.assertEqual(self.match(devices=(self.gpu,hdmi,self.audio)).audio_bdf,self.audio.bdf)

    def test_wrong_connector_card_and_gpu_pci_identity_reject(self):
        card=replace(self.card,connectors=(replace(self.card.connectors[0],card='other'),))
        self.assertIsNone(self.match(cards=(card,)))
        self.assertIsNone(self.match(devices=(replace(self.gpu,driver='vfio-pci'),self.audio)))

    def test_malformed_dataclass_fields_fail_closed(self):
        self.assertIsNone(self.match(cards=(replace(self.card,pci_bdf=[]),)))
        connector=replace(self.card.connectors[0],name=None)
        self.assertIsNone(self.match(cards=(replace(self.card,connectors=(connector,)),)))
