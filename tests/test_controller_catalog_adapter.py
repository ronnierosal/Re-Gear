from __future__ import annotations

import dataclasses
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from regear.adapters.steamos.controller_catalog import (  # noqa: E402
    COMPOSITE, DBUS, EVENT, MANAGER, UDEV, CatalogLimits,
    InputPlumberCatalogAdapter, parse_provider_frame,
)
from regear.domain.controller_catalog import CatalogCode, DeviceKind, EvidenceState, RelationState  # noqa: E402
from regear.ports.controller_catalog import PropertyRead, ProviderReadFrame  # noqa: E402


def known(value):
    return PropertyRead(EvidenceState.KNOWN, value)


def fixture():
    return ProviderReadFrame("connection:1", {
        "/manager": {MANAGER: {"Version": known("0.77.6"), "GamepadOrder": known(["/composite0"])}},
        "/source0": {EVENT: {"Name": known("Identical controller"), "SupportedKeys": known([304, 305, 316]),
                             "IdBustype": known("0003"), "UniqueId": known("private serial")},
                     UDEV: {"Name": known("Identical controller"), "Properties": known({"ID_BUS": "usb", "HOME": "/home/private"})}},
        "/composite0": {COMPOSITE: {"Name": known("Identical controller"), "PersistentId": known("private persistent id"),
                                   "ProfileName": known("private profile"), "ProfilePath": known("/home/private/profile.yaml"),
                                   "SourceDevicePaths": known(["/source0"]), "TargetDevices": known(["/target0"]),
                                   "DbusDevices": known([]), "Capabilities": known(["Gamepad:Button:South"]),
                                   "TargetCapabilities": known(["Gamepad:Button:Guide"]), "OutputCapabilities": known(["ForceFeedback"])}},
        "/target0": {"org.shadowblip.Input.Gamepad": {"Name": known("Xbox Elite")}},
    }, enumeration_complete=True)


def device(catalog, path):
    return next(d for d in catalog.devices if d.path == path)


class FixtureReader:
    def __init__(self, *values):
        self.values = list(values)
        self.calls = 0

    def read_snapshot(self):
        self.calls += 1
        value = self.values.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    def set_target_devices(self, *args):
        raise AssertionError("writes are forbidden")


class ControllerCatalogAdapterTests(unittest.TestCase):
    def test_injected_public_properties_keep_roles_and_capabilities_distinct(self):
        catalog = parse_provider_frame(fixture())
        self.assertTrue(catalog.enumeration_complete)
        self.assertEqual(len(catalog.devices), 3)
        self.assertEqual(catalog.version.value, "0.77.6")
        source = device(catalog, "/source0")
        composite = device(catalog, "/composite0")
        self.assertIs(source.kind, DeviceKind.SOURCE)
        self.assertEqual(source.supported_keys.value, (304, 305, 316))
        self.assertIs(source.input_capabilities.state, EvidenceState.UNKNOWN)
        self.assertEqual(composite.input_capabilities.value, ("Gamepad:Button:South",))
        self.assertEqual(composite.target_capabilities.value, ("Gamepad:Button:Guide",))
        self.assertEqual(composite.output_capabilities.value, ("ForceFeedback",))
        self.assertEqual(source.transport.value, "usb")
        self.assertIsNone(catalog.public_projection()["steam_player_order"])

    def test_multiple_interfaces_merge_by_path_identical_names_do_not_merge_devices(self):
        frame = fixture()
        frame.objects["/source1"] = {EVENT: {"Name": known("Identical controller")}}
        frame.objects["/composite1"] = {COMPOSITE: {"SourceDevicePaths": known(["/source1"])}}
        catalog = parse_provider_frame(frame)
        self.assertEqual(sum(d.kind is DeviceKind.SOURCE for d in catalog.devices), 2)
        self.assertEqual(sum(d.kind is DeviceKind.COMPOSITE for d in catalog.devices), 2)

    def test_duplicate_virtual_views_do_not_add_a_controller_slot(self):
        frame = fixture()
        frame.objects["/target0"] = {DBUS: {"Name": known("virtual dbus")}}
        frame.objects["/composite0"][COMPOSITE]["DbusDevices"] = known(["/target0"])
        catalog = parse_provider_frame(frame)
        self.assertEqual(len(catalog.devices), 3)
        self.assertTrue(all(r.state is RelationState.RESOLVED for r in catalog.relationships()))

    def test_missing_objects_and_unknown_interfaces_are_retained_as_evidence_gaps(self):
        frame = fixture()
        del frame.objects["/source0"]
        frame.objects["/unknown"] = {"org.example.Future": {"Name": known("private")}}
        catalog = parse_provider_frame(frame)
        self.assertIs(catalog.relationships()[0].state, RelationState.MISSING)
        self.assertIs(device(catalog, "/unknown").kind, DeviceKind.UNMANAGED)

    def test_conflicting_roles_and_shared_source_cannot_be_silently_bound(self):
        frame = fixture()
        frame.objects["/composite1"] = {COMPOSITE: {"SourceDevicePaths": known(["/source0"])}}
        self.assertTrue(all(r.state is RelationState.AMBIGUOUS for r in parse_provider_frame(frame).relationships() if r.device_path == "/source0"))
        frame.objects["/source0"]["org.shadowblip.Input.Gamepad"] = {}
        self.assertIs(device(parse_provider_frame(frame), "/source0").kind, DeviceKind.UNMANAGED)

    def test_missing_unsupported_and_denied_properties_do_not_become_empty_or_supported(self):
        for state in (EvidenceState.UNKNOWN, EvidenceState.UNSUPPORTED, EvidenceState.ERROR):
            frame = fixture()
            frame.objects["/composite0"][COMPOSITE]["TargetCapabilities"] = PropertyRead(state)
            result = device(parse_provider_frame(frame), "/composite0").target_capabilities
            self.assertIs(result.state, state)
            self.assertIsNone(result.value)

    def test_known_empty_capabilities_and_profile_path_remain_known(self):
        frame = fixture()
        frame.objects["/composite0"][COMPOSITE].update({"Capabilities": known([]), "ProfilePath": known("")})
        node = device(parse_provider_frame(frame), "/composite0")
        self.assertEqual(node.input_capabilities.value, ())
        self.assertEqual(node.profile_path.value, "")
        self.assertIs(node.profile_path.state, EvidenceState.KNOWN)

    def test_malformed_property_values_are_categorical_and_do_not_replace_other_evidence(self):
        cases = {"SourceDevicePaths": ["not a path"], "TargetDevices": ["/target0", "/target0"],
                 "Capabilities": True, "ProfileName": 123, "PersistentId": ["serial"]}
        for prop, value in cases.items():
            with self.subTest(prop=prop):
                frame = fixture()
                frame.objects["/composite0"][COMPOSITE][prop] = known(value)
                catalog = parse_provider_frame(frame)
                self.assertIn(CatalogCode.MALFORMED, catalog.issues)
                self.assertFalse(catalog.enumeration_complete)
                self.assertEqual(device(catalog, "/source0").supported_keys.value, (304, 305, 316))

    def test_supported_keys_reject_bool_out_of_range_and_wrong_types(self):
        for keys in ([True], [-1], [65536], ["BTN_SOUTH"]):
            frame = fixture()
            frame.objects["/source0"][EVENT]["SupportedKeys"] = known(keys)
            self.assertIs(device(parse_provider_frame(frame), "/source0").supported_keys.state, EvidenceState.ERROR)

    def test_provider_order_is_observed_order_and_not_discovery_order(self):
        frame = fixture()
        frame.objects["/manager"][MANAGER]["GamepadOrder"] = known(["/missing", "/composite0"])
        catalog = parse_provider_frame(frame)
        self.assertEqual(catalog.provider_order.value, ("/missing", "/composite0"))
        self.assertIsNone(catalog.public_projection()["steam_player_order"])

    def test_conflicting_manager_or_name_reads_are_not_arbitrarily_selected(self):
        frame = fixture()
        frame.objects["/manager2"] = {MANAGER: {"Version": known("other")}}
        self.assertIs(parse_provider_frame(frame).version.state, EvidenceState.ERROR)
        frame = fixture()
        frame.objects["/source0"][UDEV]["Name"] = known("different")
        self.assertIs(device(parse_provider_frame(frame), "/source0").name.state, EvidenceState.ERROR)

    def test_bus_code_alone_does_not_prove_transport(self):
        frame = fixture()
        del frame.objects["/source0"][UDEV]
        node = device(parse_provider_frame(frame), "/source0")
        self.assertEqual(node.bus_type.value, "0003")
        self.assertIs(node.transport.state, EvidenceState.UNKNOWN)

    def test_partial_enumeration_is_explicit(self):
        catalog = parse_provider_frame(dataclasses.replace(fixture(), enumeration_complete=False))
        self.assertFalse(catalog.enumeration_complete)
        self.assertIn(CatalogCode.PARTIAL, catalog.issues)
        self.assertEqual(len(catalog.devices), 3)

    def test_provider_loss_discards_supplied_stale_objects(self):
        for state in (EvidenceState.UNKNOWN, EvidenceState.UNSUPPORTED, EvidenceState.ERROR):
            catalog = parse_provider_frame(dataclasses.replace(fixture(), availability=state))
            self.assertIs(catalog.availability, state)
            self.assertEqual(catalog.devices, ())
            self.assertIsNone(catalog.version.value)
            self.assertIsNone(catalog.provider_order.value)

    def test_explicit_interface_failure_is_not_hidden_by_other_properties(self):
        frame = dataclasses.replace(fixture(), interface_states={COMPOSITE: EvidenceState.ERROR})
        self.assertIs(next(i for i in parse_provider_frame(frame).interfaces if i.name == COMPOSITE).state, EvidenceState.ERROR)
        frame = dataclasses.replace(fixture(), interface_states={COMPOSITE: EvidenceState.UNSUPPORTED})
        self.assertIn(CatalogCode.CONFLICT, parse_provider_frame(frame).issues)

    def test_snapshot_owns_immutable_copies_and_epoch_changes_invalidate_keys(self):
        frame = fixture()
        catalog = parse_provider_frame(frame)
        frame.objects["/composite0"][COMPOSITE]["Capabilities"].value.append("Keyboard:Escape")
        self.assertEqual(device(catalog, "/composite0").input_capabilities.value, ("Gamepad:Button:South",))
        self.assertNotEqual(catalog.public_projection()["connection_epoch"],
                            parse_provider_frame(dataclasses.replace(fixture(), connection_epoch="connection:2")).public_projection()["connection_epoch"])

    def test_input_bounds_and_cycles_fail_without_partial_claims(self):
        frames = [(fixture(), CatalogLimits(max_objects=1)), (fixture(), CatalogLimits(max_nodes=5)),
                  (fixture(), CatalogLimits(max_depth=2)), (fixture(), CatalogLimits(max_string=5)),
                  (fixture(), CatalogLimits(max_text_bytes=32))]
        cycle = []
        cycle.append(cycle)
        frame = fixture()
        frame.objects["/composite0"][COMPOSITE]["Capabilities"] = known(cycle)
        frames.append((frame, CatalogLimits()))
        for frame, limits in frames:
            catalog = parse_provider_frame(frame, limits=limits)
            self.assertIs(catalog.availability, EvidenceState.ERROR)
            self.assertEqual(catalog.devices, ())
            self.assertIn(CatalogCode.BOUNDS, catalog.issues)

    def test_limits_cannot_be_amplified_and_invalid_utf8_is_not_retained(self):
        for limits in ({"max_depth": 9}, {"max_items": 257}, {"max_nodes": True}):
            with self.assertRaises(ValueError):
                CatalogLimits(**limits)
        frame = fixture()
        frame.objects["/source0"][EVENT]["Name"] = known("\ud800")
        self.assertIs(parse_provider_frame(frame).availability, EvidenceState.ERROR)

    def test_invalid_frame_metadata_and_non_data_objects_fail_closed(self):
        for frame in (None, dataclasses.replace(fixture(), connection_epoch=""),
                      dataclasses.replace(fixture(), enumeration_complete=1),
                      dataclasses.replace(fixture(), objects={"/source": {EVENT: {"Name": known(object())}}})):
            self.assertIs(parse_provider_frame(frame).availability, EvidenceState.ERROR)

    def test_unused_finite_dbus_numeric_metadata_does_not_erase_other_devices(self):
        frame = fixture()
        frame.objects["/source0"][EVENT]["FutureNumericProperty"] = known(120.5)
        self.assertEqual(len(parse_provider_frame(frame).devices), 3)
        frame.objects[1] = {}
        catalog = parse_provider_frame(frame)
        self.assertEqual(len(catalog.devices), 3)
        self.assertIn(CatalogCode.MALFORMED, catalog.issues)
        frame.objects[2**20000] = {}
        self.assertIn(CatalogCode.BOUNDS, parse_provider_frame(frame).issues)

    def test_collector_reads_once_and_never_caches_prior_success_after_failure(self):
        reader = FixtureReader(fixture(), RuntimeError("private /home/serial"), fixture())
        adapter = InputPlumberCatalogAdapter(reader)
        first = adapter.collect_catalog()
        failed = adapter.collect_catalog()
        third = adapter.collect_catalog()
        self.assertEqual(reader.calls, 3)
        self.assertTrue(first.devices and third.devices)
        self.assertEqual(failed.devices, ())
        self.assertIn(CatalogCode.READER_FAILED, failed.issues)
        self.assertNotIn("private", json.dumps(failed.public_projection()))

    def test_injected_collection_uses_no_file_process_or_network_io(self):
        reader = FixtureReader(fixture())
        with mock.patch("builtins.open", side_effect=AssertionError("file I/O")), \
             mock.patch("subprocess.run", side_effect=AssertionError("process I/O")), \
             mock.patch("socket.create_connection", side_effect=AssertionError("network I/O")):
            catalog = InputPlumberCatalogAdapter(reader).collect_catalog()
        self.assertEqual(reader.calls, 1)
        self.assertEqual(len(catalog.devices), 3)


if __name__ == "__main__":
    unittest.main()
