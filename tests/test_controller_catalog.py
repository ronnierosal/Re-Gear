from __future__ import annotations

import dataclasses
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from regear.domain.controller_catalog import (  # noqa: E402
    CatalogCode, ControllerCatalog, DeviceKind, DeviceObservation, EvidenceState,
    Observation, ProviderInterface, RelationKind, RelationState,
)


def known(value):
    return Observation(EvidenceState.KNOWN, value, CatalogCode.OBSERVED)


def source(path="/source0"):
    return DeviceObservation(path, DeviceKind.SOURCE, ("private.interface",),
                             name=known("private serial 123"), supported_keys=known((304, 305)))


def composite(path="/composite0", sources=("/source0",), targets=("/target0",), dbus=()):
    return DeviceObservation(path, DeviceKind.COMPOSITE, (),
                             persistent_id=known("private persistent serial"),
                             profile_name=known("private profile"),
                             profile_path=known("/home/private/profile.yaml"),
                             source_paths=known(sources), target_paths=known(targets), dbus_paths=known(dbus),
                             input_capabilities=known(("private capability",)),
                             target_capabilities=known(("Gamepad:Button:South",)),
                             output_capabilities=known(("ForceFeedback",)))


class ControllerCatalogTests(unittest.TestCase):
    def catalog(self, *devices, **changes):
        return ControllerCatalog(EvidenceState.KNOWN, "private:epoch:1", True,
                                 devices=devices, **changes)

    def test_known_empty_is_distinct_from_unknown_unsupported_and_error(self):
        self.assertEqual(known(()).value, ())
        for state in (EvidenceState.UNKNOWN, EvidenceState.UNSUPPORTED, EvidenceState.ERROR):
            observation = Observation(state, code=CatalogCode.READ_UNAVAILABLE)
            self.assertIsNone(observation.value)
            self.assertNotEqual(observation, known(()))

    def test_unavailable_cannot_retain_an_old_or_mutable_value(self):
        for state, value, code in ((EvidenceState.UNKNOWN, ("old",), CatalogCode.MISSING),
                                   (EvidenceState.KNOWN, ["mutable"], CatalogCode.OBSERVED),
                                   (EvidenceState.KNOWN, None, CatalogCode.OBSERVED),
                                   (EvidenceState.KNOWN, "yes", CatalogCode.MISSING)):
            with self.subTest(state=state, value=value):
                with self.assertRaises(ValueError):
                    Observation(state, value, code)

    def test_domain_observations_are_frozen(self):
        with self.assertRaises(dataclasses.FrozenInstanceError):
            source().path = "/other"

    def test_source_composite_target_relationships_are_separate(self):
        target = DeviceObservation("/target0", DeviceKind.TARGET, ())
        catalog = self.catalog(source(), composite(), target)
        self.assertEqual({r.kind for r in catalog.relationships()}, {RelationKind.SOURCE, RelationKind.TARGET})
        self.assertTrue(all(r.state is RelationState.RESOLVED for r in catalog.relationships()))
        self.assertEqual(len(catalog.devices), 3)

    def test_missing_reference_does_not_create_a_physical_or_virtual_device(self):
        catalog = self.catalog(composite())
        self.assertEqual(len(catalog.devices), 1)
        self.assertTrue(all(r.state is RelationState.MISSING for r in catalog.relationships()))

    def test_shared_source_is_ambiguous_without_selecting_a_composite(self):
        catalog = self.catalog(source(), composite(targets=()), composite("/composite1", targets=()))
        self.assertEqual(len(catalog.relationships()), 2)
        self.assertTrue(all(r.state is RelationState.AMBIGUOUS for r in catalog.relationships()))

    def test_wrong_reference_kind_is_not_resolved(self):
        catalog = self.catalog(source("/target0"), composite(sources=()))
        self.assertIs(catalog.relationships()[0].state, RelationState.AMBIGUOUS)

    def test_dbus_target_has_two_views_and_one_device_identity(self):
        dbus = DeviceObservation("/dbus0", DeviceKind.DBUS, ())
        catalog = self.catalog(composite(sources=(), targets=("/dbus0",), dbus=("/dbus0",)), dbus)
        self.assertEqual(len(catalog.devices), 2)
        self.assertEqual(len(catalog.relationships()), 2)
        self.assertTrue(all(r.state is RelationState.RESOLVED for r in catalog.relationships()))

    def test_capabilities_and_supported_key_metadata_do_not_grant_mapping_support(self):
        catalog = self.catalog(source(), composite(targets=()))
        projection = catalog.public_projection()
        self.assertIsNone(projection["steam_player_order"])
        self.assertFalse(projection["effective_targets_verified"])
        for device in projection["devices"]:
            self.assertIsNone(device["physical_origin"])
            self.assertIsNone(device["builtin"])
            self.assertIsNone(device["external"])

    def test_private_identifiers_labels_paths_and_capability_text_never_project(self):
        catalog = self.catalog(source(), composite(), version=known("private version"),
                               interfaces=(ProviderInterface("private.interface", EvidenceState.KNOWN),),
                               provider_order=known(("/composite0", "/missing0")))
        public = catalog.public_projection()
        encoded = json.dumps(public)
        for private in ("private", "/source0", "/target0", "/composite0", "/missing0", "123", "yaml"):
            self.assertNotIn(private, encoded)
        self.assertEqual([x["composite_present"] for x in public["provider_order"]["entries"]], [True, False])

    def test_keys_are_scoped_to_epoch_and_paths_not_friendly_names(self):
        first = self.catalog(source(), source("/source1"))
        keys = [d["key"] for d in first.public_projection()["devices"]]
        self.assertEqual(len(set(keys)), 2)
        second = dataclasses.replace(first, connection_epoch="private:epoch:2")
        self.assertNotEqual(keys, [d["key"] for d in second.public_projection()["devices"]])
        self.assertEqual(keys, [d["key"] for d in first.public_projection()["devices"]])

    def test_unreferenced_source_stays_explicit_without_external_inference(self):
        public = self.catalog(source()).public_projection()["devices"][0]
        self.assertFalse(public["referenced_in_snapshot"])
        self.assertIsNone(public["external"])


if __name__ == "__main__":
    unittest.main()
