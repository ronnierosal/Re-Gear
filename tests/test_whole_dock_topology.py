"""Synthetic sysfs topology; no mutation of a hardware tree."""
import shutil
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from regear.adapters.steamos import whole_dock_topology as m


@unittest.skipUnless(sys.platform == "linux", "Linux sysfs symlink fixtures")
class TopologyTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        mocked = patch.object(m, "SYSFS_ROOT", self.root)
        mocked.start()
        self.addCleanup(mocked.stop)
        self.pci = self.root / "bus/pci/devices"
        self.tb = self.root / "bus/thunderbolt/devices"
        self.links = self.root / "devices/virtual/devlink"
        for path in (self.pci, self.tb, self.links):
            path.mkdir(parents=True)
        pci_root = self.root / "devices/pci0000:00"
        self.branch = self.device(pci_root, "0000:00:03.1", "0x060400")
        self.nhi = self.device(pci_root, "0000:66:00.5", "0x0c0340")
        self.link(self.nhi, self.branch)
        switch = self.device(self.branch, "0000:04:00.0", "0x060400")
        gpu_port = self.device(switch, "0000:05:01.0", "0x060400")
        usb_port = self.device(switch, "0000:05:02.0", "0x060400")
        self.gpu = self.device(gpu_port, "0000:08:00.0", "0x030000")
        self.audio = self.device(gpu_port, "0000:08:00.1", "0x040300")
        self.usb = self.device(usb_port, "0000:09:00.0", "0x0c0330")
        self.domain = self.nhi / "domain0"
        self.domain.mkdir()
        (self.domain / "deauthorization").write_text("1")
        (self.tb / "domain0").symlink_to(self.domain)
        self.host = self.router(self.domain, "0-0")
        self.external = self.router(self.host, "0-2")

    def device(self, parent, name, category):
        node = parent / name
        node.mkdir(parents=True)
        (node / "class").write_text(category)
        (self.pci / name).symlink_to(node)
        return node

    def link(self, supplier, consumer):
        link = self.links / ("pci:" + supplier.name + "--pci:" + consumer.name)
        link.mkdir()
        (link / "supplier").symlink_to(supplier)
        (link / "consumer").symlink_to(consumer)
        (consumer / ("supplier:pci:" + supplier.name)).symlink_to(link)
        (supplier / ("consumer:pci:" + consumer.name)).symlink_to(link)

    def router(self, parent, name):
        node = parent / name
        node.mkdir()
        (node / "authorized").write_text("1")
        (node / "unique_id").write_text("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        (self.tb / name).symlink_to(node)
        return node

    def resolve(self):
        return m.resolve_whole_dock(self.gpu.name)

    def remove_fixture_pci(self, path):
        (self.pci / path.name).unlink()
        shutil.rmtree(path)

    def test_complete_binding_and_revalidation(self):
        binding = self.resolve()
        self.assertEqual(binding.gpu_bdf, self.gpu.name)
        self.assertEqual(binding.audio_bdf, self.audio.name)
        self.assertEqual(binding.usb_bdf, self.usb.name)
        self.assertEqual(binding.router_id, "0-2")
        self.assertTrue(m.revalidate_retained(binding))
        self.assertNotIn("aaaaaaaa", repr(binding))

    def test_duplicate_router_refused(self):
        self.router(self.host, "0-3")
        with self.assertRaises(m.TopologyRefused):
            self.resolve()

    def test_cascade_refused(self):
        self.router(self.external, "0-202")
        with self.assertRaises(m.TopologyRefused):
            self.resolve()

    def test_duplicate_nhi_consumer_refused(self):
        other = self.device(self.branch.parent, "0000:00:04.1", "0x060400")
        self.link(self.nhi, other)
        with self.assertRaises(m.TopologyRefused):
            self.resolve()

    def test_unrelated_devlink_without_endpoints_ignored(self):
        (self.links / "platform:PNP0C14:00--wmi:unrelated").mkdir()
        self.assertTrue(m.revalidate_retained(self.resolve()))

    def test_nhi_consumer_missing_endpoint_refused(self):
        link = next(self.links.iterdir())
        (link / "supplier").unlink()
        with self.assertRaises(m.TopologyRefused):
            self.resolve()

    def test_wrong_consumer_link_refused(self):
        link = next(self.links.iterdir())
        (link / "consumer").unlink()
        (link / "consumer").symlink_to(self.nhi)
        with self.assertRaises(m.TopologyRefused):
            self.resolve()

    def test_wrong_host_domain_refused(self):
        other = self.device(self.nhi.parent, "0000:67:00.5", "0x0c0340")
        moved = other / "domain0"
        self.domain.rename(moved)
        (self.tb / "domain0").unlink()
        (self.tb / "domain0").symlink_to(moved)
        with self.assertRaises(m.TopologyRefused):
            self.resolve()

    def test_extra_endpoint_refused(self):
        self.device(self.usb.parent, "0000:09:00.1", "0x020000")
        with self.assertRaises(m.TopologyRefused):
            self.resolve()

    def test_missing_supplier_evidence_refused(self):
        next(self.branch.glob("supplier:*" )).unlink()
        with self.assertRaises(m.TopologyRefused):
            self.resolve()

    def test_unreadable_class_refused(self):
        original = m._read
        def denied(path):
            if path == self.usb / "class":
                raise PermissionError("fixture denied")
            return original(path)
        with patch.object(m, "_read", side_effect=denied):
            with self.assertRaises(m.TopologyRefused):
                self.resolve()

    def test_router_replacement_refused(self):
        binding = self.resolve()
        old = self.external.with_name("old-router")
        self.external.rename(old)
        shutil.copytree(old, self.external)
        with self.assertRaises(m.TopologyRefused):
            m.revalidate_retained(binding)

    def test_usb_replacement_refused(self):
        binding = self.resolve()
        old = self.usb.with_name("old-usb")
        self.usb.rename(old)
        shutil.copytree(old, self.usb)
        with self.assertRaises(m.TopologyRefused):
            m.revalidate_retained(binding)

    def test_authorized_expected_removal(self):
        binding = self.resolve()
        self.remove_fixture_pci(self.audio)
        self.remove_fixture_pci(self.gpu)
        self.assertTrue(m.revalidate_retained(binding, gpu_removed=True))
        self.remove_fixture_pci(self.usb)
        self.assertTrue(m.revalidate_retained(binding, gpu_removed=True, usb_removed=True))
        with self.assertRaises(m.TopologyRefused):
            m.revalidate_retained(binding)

    def test_missing_router_not_success(self):
        binding = self.resolve()
        (self.tb / self.external.name).unlink()
        shutil.rmtree(self.external)
        with self.assertRaises(m.TopologyRefused):
            m.revalidate_retained(binding, gpu_removed=True, usb_removed=True, tunnel_down=True)

    def test_retained_pci_refuses_final_down(self):
        binding = self.resolve()
        (self.external / "authorized").write_text("0")
        with self.assertRaises(m.TopologyRefused):
            m.revalidate_retained(binding, tunnel_down=True)

    def test_complete_final_software_down(self):
        binding = self.resolve()
        for target in binding.pci_targets:
            (self.pci / target.parts[-1]).unlink()
        shutil.rmtree(self.branch / "0000:04:00.0")
        (self.external / "authorized").write_text("0")
        self.assertTrue(m.revalidate_retained(binding, gpu_removed=True,
                                             usb_removed=True, tunnel_down=True))

    def test_router_identity_content_changed(self):
        binding = self.resolve()
        (self.external / "unique_id").write_text("ffffffff-bbbb-cccc-dddd-eeeeeeeeeeee")
        with self.assertRaises(m.TopologyRefused):
            m.revalidate_retained(binding)


if __name__ == "__main__":
    unittest.main()
