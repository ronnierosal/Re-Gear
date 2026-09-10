from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.adapters.steamos.peripherals import (  # noqa: E402
    PeripheralIdentityHints,
    SteamOsPeripheralInventory,
    SteamOsPeripheralObservationAdapter,
    peripheral_status_to_public_payload,
)
from regear.domain.peripheral_handoff import (  # noqa: E402
    PeripheralMappingEvidence,
    PeripheralMappingEvidenceKind,
)


def write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


class PeripheralInventoryTests(unittest.TestCase):
    def _inventory(self, root: Path):
        return SteamOsPeripheralInventory(
            input_root=root / "input", sound_root=root / "sound"
        )

    def test_read_only_inventory_hashes_gamepad_and_sound_nodes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write(root / "input" / "event7" / "device" / "capabilities" / "key", f"{1 << 0x130:x}\n")
            write(root / "input" / "event2" / "device" / "capabilities" / "key", "0\n")
            (root / "sound" / "card3").mkdir(parents=True)
            inventory = self._inventory(root).scan()
            self.assertTrue(inventory.controller_complete)
            self.assertTrue(inventory.audio_complete)
            self.assertEqual(len(inventory.controller_bindings), 1)
            self.assertEqual(len(inventory.audio_bindings), 1)
            self.assertNotIn(str(root), repr(inventory))

    def test_unreadable_sources_fail_closed(self):
        inventory = SteamOsPeripheralInventory(
            input_root=Path("missing-input"), sound_root=Path("missing-sound")
        ).scan()
        self.assertFalse(inventory.controller_complete)
        self.assertFalse(inventory.audio_complete)
        self.assertEqual(inventory.controller_error, "controller.input_root_unreadable")
        self.assertEqual(inventory.audio_error, "audio.sound_root_unreadable")

    def test_default_adapter_exposes_no_actionable_identity_or_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write(root / "input" / "event1" / "device" / "capabilities" / "key", f"{1 << 0x130:x}\n")
            (root / "sound" / "card0").mkdir(parents=True)
            observed = SteamOsPeripheralObservationAdapter(
                self._inventory(root),
                generation_factory=lambda: "peripheral-generation-a",
                sample_factory=lambda: "peripheral-sample-a",
            ).observe()
            self.assertFalse(observed.controller.exact)
            self.assertFalse(observed.audio.exact)
            self.assertFalse(observed.controller.external_input_verified)
            self.assertFalse(observed.audio.external_output_verified)

    def test_reviewed_exact_controller_mapping_still_never_claims_input_verified(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write(root / "input" / "event1" / "device" / "capabilities" / "key", f"{1 << 0x130:x}\n")
            (root / "sound").mkdir()
            inventory = self._inventory(root)
            binding = inventory.scan().controller_bindings[0]
            mapping = PeripheralMappingEvidence(
                "peripheral-mapping-a",
                SteamOsPeripheralObservationAdapter.inventory_generation(inventory.scan()),
                "2026-08-31T12:00:00Z",
                PeripheralMappingEvidenceKind.SUPERVISED_HARDWARE_TEST,
                True,
                True,
                PeripheralIdentityHints(builtin_controller_binding=binding),
            )
            observed = SteamOsPeripheralObservationAdapter(
                inventory,
                mapping,
                generation_factory=lambda: "peripheral-generation-a",
                sample_factory=lambda: "peripheral-sample-a",
            ).observe()
            self.assertTrue(observed.controller.exact)
            self.assertTrue(observed.controller.builtin_available)
            self.assertFalse(observed.controller.builtin_input_verified)
            self.assertFalse(observed.controller.builtin_restore_verified)

    def test_stale_reviewed_mapping_fails_closed_for_all_subsystems(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write(root / "input" / "event1" / "device" / "capabilities" / "key", f"{1 << 0x130:x}\n")
            (root / "sound" / "card0").mkdir(parents=True)
            inventory = self._inventory(root)
            scanned = inventory.scan()
            mapping = PeripheralMappingEvidence(
                "peripheral-mapping-a",
                SteamOsPeripheralObservationAdapter.inventory_generation(scanned),
                "2026-08-31T12:00:00Z",
                PeripheralMappingEvidenceKind.SUPERVISED_HARDWARE_TEST,
                True,
                True,
                PeripheralIdentityHints(
                    builtin_controller_binding=scanned.controller_bindings[0],
                    current_audio_binding=scanned.audio_bindings[0],
                ),
            )
            write(root / "input" / "event9" / "device" / "capabilities" / "key", f"{1 << 0x130:x}\n")
            observed = SteamOsPeripheralObservationAdapter(inventory, mapping).observe()

            self.assertFalse(observed.controller.exact)
            self.assertEqual(observed.controller.failure_code, "peripheral.mapping_stale")
            self.assertEqual(observed.audio.failure_code, "peripheral.mapping_stale")

    def test_mapping_evidence_requires_reviewed_supervised_nonempty_identity(self):
        with self.assertRaisesRegex(ValueError, "requires intentional review"):
            PeripheralMappingEvidence(
                "peripheral-mapping-a",
                "inventory-generation-a",
                "2026-08-31T12:00:00Z",
                PeripheralMappingEvidenceKind.SUPERVISED_HARDWARE_TEST,
                True,
                False,
                PeripheralIdentityHints(builtin_controller_binding="controller-private-a"),
            )
        with self.assertRaisesRegex(ValueError, "requires a binding"):
            PeripheralMappingEvidence(
                "peripheral-mapping-a",
                "inventory-generation-a",
                "2026-08-31T12:00:00Z",
                PeripheralMappingEvidenceKind.SUPERVISED_HARDWARE_TEST,
                True,
                True,
                PeripheralIdentityHints(),
            )

    def test_default_semantic_generation_is_stable_but_samples_are_fresh(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write(root / "input" / "event1" / "device" / "capabilities" / "key", f"{1 << 0x130:x}\n")
            (root / "sound" / "card0").mkdir(parents=True)
            adapter = SteamOsPeripheralObservationAdapter(self._inventory(root))
            first = adapter.observe()
            second = adapter.observe()
            self.assertEqual(first.generation, second.generation)
            self.assertNotEqual(first.sample_id, second.sample_id)
            write(root / "input" / "event9" / "device" / "capabilities" / "key", f"{1 << 0x130:x}\n")
            changed = adapter.observe()
            self.assertNotEqual(first.generation, changed.generation)

    def test_public_status_omits_private_bindings_and_observation_ids(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write(root / "input" / "event1" / "device" / "capabilities" / "key", f"{1 << 0x130:x}\n")
            (root / "sound" / "card0").mkdir(parents=True)
            observed = SteamOsPeripheralObservationAdapter(self._inventory(root)).observe()
            payload = peripheral_status_to_public_payload(observed)
            encoded = repr(payload)
            self.assertNotIn("controller-", encoded)
            self.assertNotIn("audio-", encoded)
            self.assertNotIn(observed.generation, encoded)
            self.assertNotIn(observed.sample_id, encoded)


if __name__ == "__main__":
    unittest.main()
