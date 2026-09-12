"""Synthetic sysfs topology; no mutation of a hardware tree."""
import shutil
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from dataclasses import replace
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
        for field, value in (("vendor", "0x1002"), ("device", "0x1234"),
                             ("subsystem_vendor", "0x1002"), ("subsystem_device", "0x5678")):
            (node / field).write_text(value)
        (self.pci / name).symlink_to(node)
        driver = {"0x030000": "amdgpu", "0x030200": "amdgpu",
                  "0x040300": "snd_hda_intel", "0x0c0330": "xhci_hcd"}.get(category, "pcieport")
        driver_root = self.root / "bus/pci/drivers" / driver
        driver_root.mkdir(parents=True, exist_ok=True)
        (node / "driver").symlink_to(driver_root)
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

    def absent_transport(self):
        binding = self.resolve()
        for node in (self.gpu, self.audio, self.usb):
            self.remove_fixture_pci(node)
        return binding

    def test_transport_all_endpoints_absent_preserves_retained_binding(self):
        previous = self.absent_transport()
        observed = m.resolve_transport(previous.binding)
        self.assertEqual(observed.binding, previous.binding)
        self.assertEqual(observed.generation, previous.generation)
        self.assertEqual(observed.branch_target, previous.branch_target)
        self.assertEqual(observed.router_target, previous.router_target)
        self.assertEqual(len(observed.bridge_targets), 3)
        self.assertNotIn('aaaaaaaa-bbbb', repr(observed))

    def test_transport_fully_absent_pci_branch_supported(self):
        previous = self.absent_transport()
        for path in sorted([node for node in self.pci.iterdir()
                            if self.branch in node.resolve().parents], key=lambda node: len(node.resolve().parts), reverse=True):
            self.remove_fixture_pci(path.resolve())
        self.assertEqual(m.resolve_transport(previous.binding).bridge_targets, ())

    def test_transport_full_or_partial_endpoints_refused(self):
        binding = self.resolve()
        with self.assertRaises(m.TopologyRefused):
            m.resolve_transport(binding.binding)
        self.remove_fixture_pci(self.gpu)
        with self.assertRaises(m.TopologyRefused):
            m.resolve_transport(binding.binding)
        self.remove_fixture_pci(self.audio)
        with self.assertRaises(m.TopologyRefused):
            m.resolve_transport(binding.binding)

    def test_transport_unindexed_endpoint_refused(self):
        binding = self.resolve()
        for path in (self.gpu, self.audio, self.usb):
            (self.pci / path.name).unlink()
        with self.assertRaises(m.TopologyRefused):
            m.resolve_transport(binding.binding)

    def test_transport_wrong_binding_deauthorized_and_router_ambiguity_refused(self):
        binding = self.absent_transport()
        with self.assertRaises(m.TopologyRefused):
            m.resolve_transport('f' * 64)
        (self.external / 'authorized').write_text('0')
        with self.assertRaises(m.TopologyRefused):
            m.resolve_transport(binding.binding)
        (self.external / 'authorized').write_text('1')
        self.router(self.host, '0-3')
        with self.assertRaises(m.TopologyRefused):
            m.resolve_transport(binding.binding)

    def test_transport_changed_second_observation_refused(self):
        binding = self.absent_transport()
        observed = m.resolve_transport(binding.binding)
        with patch.object(m, '_resolve_transport', side_effect=[observed, replace(observed, generation='changed')]):
            with self.assertRaises(m.TopologyRefused):
                m.resolve_transport(binding.binding)

    def test_transport_invalid_expected_binding_refused(self):
        for value in (None, '', 'not-a-binding', 'A' * 64):
            with self.assertRaises(m.TopologyRefused):
                m.resolve_transport(value)

    def deauthorized_fixture(self):
        previous = self.absent_transport()
        for path in sorted([node for node in self.pci.iterdir()
                            if self.branch in node.resolve().parents], key=lambda node: len(node.resolve().parts), reverse=True):
            self.remove_fixture_pci(path.resolve())
        (self.external / 'authorized').write_text('0')
        (self.domain / 'security').write_text('user')
        return previous

    def test_deauthorized_transport_requires_exact_generation_and_no_descendants(self):
        previous = self.deauthorized_fixture()
        result = m.resolve_deauthorized_transport(previous.binding, previous.generation)
        self.assertEqual((result.binding, result.generation), (previous.binding, previous.generation))
        self.assertEqual(result.bridge_targets, ())
        with self.assertRaises(m.TopologyRefused):
            m.resolve_deauthorized_transport(previous.binding, 'f' * 64)
        with self.assertRaises(m.TopologyRefused):
            m.resolve_transport(previous.binding)

    def test_deauthorized_transport_retained_bridge_refuses(self):
        previous = self.absent_transport()
        (self.external / 'authorized').write_text('0')
        (self.domain / 'security').write_text('user')
        with self.assertRaisesRegex(m.TopologyRefused, 'pci_branch_remains'):
            m.resolve_deauthorized_transport(previous.binding, previous.generation)

    def test_deauthorized_transport_hidden_bridge_refuses(self):
        previous = self.deauthorized_fixture()
        hidden = self.device(self.branch, '0000:04:00.0', '0x060400')
        (self.pci / hidden.name).unlink()
        with self.assertRaisesRegex(m.TopologyRefused, 'pci_branch_remains'):
            m.resolve_deauthorized_transport(previous.binding, previous.generation)

    def test_deauthorized_transport_security_authorization_and_capability_refuse(self):
        previous = self.deauthorized_fixture()
        for path, bad, restored in ((self.domain / 'security', 'none', 'user'),
                (self.domain / 'deauthorization', '0', '1'),
                (self.external / 'authorized', '1', '0')):
            with self.subTest(path=path.name):
                path.write_text(bad)
                with self.assertRaises(m.TopologyRefused):
                    m.resolve_deauthorized_transport(previous.binding, previous.generation)
                path.write_text(restored)

    def test_deauthorized_transport_second_observation_change_refuses(self):
        previous = self.deauthorized_fixture()
        observed = m.resolve_deauthorized_transport(previous.binding, previous.generation)
        with patch.object(m, '_resolve_transport', side_effect=[observed, replace(observed, generation='changed')]):
            with self.assertRaises(m.TopologyRefused):
                m.resolve_deauthorized_transport(previous.binding, previous.generation)

    def test_deauthorized_transport_invalid_identity_refuses(self):
        for binding, generation in ((None, 'a' * 64), ('a' * 64, None), ('a' * 64, 'short')):
            with self.assertRaises(m.TopologyRefused):
                m.resolve_deauthorized_transport(binding, generation)

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
        shutil.copytree(old, self.usb, symlinks=True)
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

    def test_reconnect_new_addresses_and_inodes(self):
        binding = self.resolve()
        gpu_parent, usb_parent = self.gpu.parent, self.usb.parent
        for node in (self.gpu, self.audio, self.usb):
            self.remove_fixture_pci(node)
        self.device(gpu_parent, "0000:18:00.0", "0x030000")
        self.device(gpu_parent, "0000:18:00.1", "0x040300")
        self.device(usb_parent, "0000:19:00.0", "0x0c0330")
        fresh = m.observe_reconnected(binding)
        self.assertEqual(fresh.gpu_bdf, "0000:18:00.0")
        self.assertEqual(fresh.usb_bdf, "0000:19:00.0")
        self.assertEqual(fresh.function_identities, binding.function_identities)
        self.assertEqual(fresh.router_target, binding.router_target)

    def test_reconnect_same_address_new_inode(self):
        binding = self.resolve()
        old = self.gpu.with_name("old-gpu")
        self.gpu.rename(old)
        shutil.copytree(old, self.gpu, symlinks=True)
        fresh = m.observe_reconnected(binding)
        self.assertEqual(fresh.gpu_bdf, binding.gpu_bdf)
        self.assertNotEqual(fresh.pci_targets, binding.pci_targets)

    def test_reconnect_changed_hardware_refused(self):
        binding = self.resolve()
        (self.gpu / "device").write_text("0x9876")
        with self.assertRaisesRegex(m.TopologyRefused, "hardware_changed"):
            m.observe_reconnected(binding)

    def test_reconnect_missing_old_identity_refused(self):
        binding = replace(self.resolve(), function_identities=())
        with self.assertRaisesRegex(m.TopologyRefused, "identity_missing"):
            m.observe_reconnected(binding)

    def test_reconnect_missing_new_identity_refused(self):
        binding = self.resolve()
        (self.usb / "vendor").unlink()
        with self.assertRaises(m.TopologyRefused) as failure:
            m.observe_reconnected(binding)
        self.assertNotIsInstance(failure.exception, m.ReconnectPending)

    def test_reconnect_enumeration_pending(self):
        binding = self.resolve()
        self.remove_fixture_pci(self.usb)
        with self.assertRaises(m.ReconnectPending):
            m.observe_reconnected(binding)

    def test_reconnect_authorization_pending(self):
        binding = self.resolve()
        (self.external / "authorized").write_text("0")
        with self.assertRaises(m.ReconnectPending):
            m.observe_reconnected(binding)

    def test_reconnect_changed_uuid_never_pending(self):
        binding = self.resolve()
        (self.external / "authorized").write_text("0")
        (self.external / "unique_id").write_text("ffffffff-bbbb-cccc-dddd-eeeeeeeeeeee")
        with self.assertRaises(m.TopologyRefused) as failure:
            m.observe_reconnected(binding)
        self.assertNotIsInstance(failure.exception, m.ReconnectPending)

    def test_reconnect_duplicate_gpu_refused(self):
        binding = self.resolve()
        self.device(self.gpu.parent, "0000:18:00.0", "0x030000")
        with self.assertRaises(m.TopologyRefused) as failure:
            m.observe_reconnected(binding)
        self.assertNotIsInstance(failure.exception, m.ReconnectPending)

    def test_reconnect_driver_pending_then_bound(self):
        binding = self.resolve()
        driver = (self.gpu / "driver").resolve()
        (self.gpu / "driver").unlink()
        with self.assertRaises(m.ReconnectPending):
            m.observe_reconnected(binding)
        (self.gpu / "driver").symlink_to(driver)
        self.assertEqual(m.observe_reconnected(binding).function_identities,
                         binding.function_identities)

    def test_reconnect_wrong_driver_refused(self):
        binding = self.resolve()
        other = self.root / "bus/pci/drivers/vfio-pci"
        other.mkdir()
        (self.gpu / "driver").unlink()
        (self.gpu / "driver").symlink_to(other)
        with self.assertRaises(m.TopologyRefused) as failure:
            m.observe_reconnected(binding)
        self.assertNotIsInstance(failure.exception, m.ReconnectPending)

    def test_missing_initial_driver_refused(self):
        (self.usb / "driver").unlink()
        with self.assertRaises(m.TopologyRefused) as failure:
            self.resolve()
        self.assertNotIsInstance(failure.exception, m.ReconnectPending)

    def test_missing_previous_driver_evidence_refused(self):
        binding = self.resolve()
        identity = replace(binding.function_identities[0], driver="")
        binding = replace(binding, function_identities=(identity,) + binding.function_identities[1:])
        with self.assertRaisesRegex(m.TopologyRefused, "identity_missing"):
            m.observe_reconnected(binding)

    def test_driver_link_outside_driver_tree_refused(self):
        binding = self.resolve()
        (self.audio / "driver").unlink()
        (self.audio / "driver").symlink_to(self.usb)
        with self.assertRaises(m.TopologyRefused) as failure:
            m.observe_reconnected(binding)
        self.assertNotIsInstance(failure.exception, m.ReconnectPending)




    def hub(self, parent, name):
        node = parent / name
        node.mkdir()
        for key, value in [('bDeviceClass','09'),('bConfigurationValue','1'),('bNumInterfaces','1')]:
            (node / key).write_text(value)
        prefix = name[3:] + '-0' if name.startswith('usb') else name
        interface = node / (prefix + ':1.0')
        interface.mkdir()
        (interface / 'bInterfaceClass').write_text('09')
        driver = self.root / 'bus/usb/drivers/hub'
        driver.mkdir(parents=True, exist_ok=True)
        (interface / 'driver').symlink_to(driver)
        return node

    def test_hub_only_branch_strict_descriptors(self):
        from regear.adapters.steamos.dock_branch import DockUsbReading, DockUsbDevice
        binding = m.resolve_whole_dock(self.gpu.name)
        root = self.hub(self.usb, 'usb1')
        hub = self.hub(root, '1-1')
        reading = DockUsbReading(self.usb.name, True, True,
            (DockUsbDevice('1-1', 'Untrusted name', '', ()),))
        self.assertTrue(m.usb_branch_is_hub_only(binding, reading))
        for field, value in [('bDeviceClass','00'),('bConfigurationValue','0'),('bNumInterfaces','2'),('bNumInterfaces','bad')]:
            path = hub / field
            original = path.read_text()
            path.write_text(value)
            self.assertFalse(m.usb_branch_is_hub_only(binding, reading), field)
            path.write_text(original)
        interface = hub / '1-1:1.0'
        for value in ('08','03','ff',''):
            (interface / 'bInterfaceClass').write_text(value)
            self.assertFalse(m.usb_branch_is_hub_only(binding, reading))
        (interface / 'bInterfaceClass').write_text('09')
        (interface / 'driver').unlink()
        self.assertFalse(m.usb_branch_is_hub_only(binding, reading))

    def test_hub_children_and_incomplete_inventory_refuse(self):
        from regear.adapters.steamos.dock_branch import DockUsbReading, DockUsbDevice
        binding = m.resolve_whole_dock(self.gpu.name)
        root = self.hub(self.usb, 'usb1')
        hub = self.hub(root, '1-1')
        child = self.hub(hub, '1-1.1')
        devices = tuple(DockUsbDevice(n, '', '', ()) for n in ('1-1','1-1.1'))
        reading = DockUsbReading(self.usb.name, True, True, devices)
        self.assertTrue(m.usb_branch_is_hub_only(binding, reading))
        self.assertFalse(m.usb_branch_is_hub_only(binding, replace(reading, devices=devices[:1])))
        self.assertFalse(m.usb_branch_is_hub_only(binding, replace(reading, complete=False)))
        (child / 'bDeviceClass').write_text('08')
        self.assertFalse(m.usb_branch_is_hub_only(binding, reading))

    def test_hub_composite_and_replaced_controller_refuse(self):
        from regear.adapters.steamos.dock_branch import DockUsbReading, DockUsbDevice
        binding = self.resolve()
        root = self.hub(self.usb, 'usb1')
        hub = self.hub(root, '1-1')
        reading = DockUsbReading(self.usb.name, True, True, (DockUsbDevice('1-1', '', '', ()),))
        (hub / 'bNumInterfaces').write_text('2')
        extra = hub / '1-1:1.1'
        extra.mkdir()
        (extra / 'bInterfaceClass').write_text('03')
        self.assertFalse(m.usb_branch_is_hub_only(binding, reading))
        shutil.rmtree(extra)
        (hub / 'bNumInterfaces').write_text('1')
        changed = replace(binding.usb_target, identities=())
        self.assertFalse(m.usb_branch_is_hub_only(replace(binding, usb_target=changed), reading))
        (hub / 'bNumInterfaces').unlink()
        self.assertFalse(m.usb_branch_is_hub_only(binding, reading))

if __name__ == "__main__":
    unittest.main()
