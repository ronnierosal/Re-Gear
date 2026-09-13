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
    _bitmap_has,
    peripheral_status_to_public_payload,
)
from regear.domain.peripheral_handoff import (  # noqa: E402
    PeripheralMappingEvidence,
    PeripheralMappingEvidenceKind,
)


BTN_GAMEPAD = 0x130
KEY_MAX = 0x2FF
ULONG_BITS = 64


def write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def capabilities_key(*bits: int) -> str:
    """Render ``capabilities/key`` the way a 64-bit SteamOS reader sees it.

    Linux v6.12 ``drivers/input/input.c`` ``input_print_bitmap`` walks the
    ``unsigned long`` array from the most significant word down, prints each
    word with an unpadded ``%lx`` via ``input_bits_to_string``, separates words
    with single spaces, and skips leading all-zero words. Word positions are
    therefore carried by the spaces, not by the digit count.
    """
    words = [0] * ((KEY_MAX // ULONG_BITS) + 1)
    for bit in bits:
        words[bit // ULONG_BITS] |= 1 << (bit % ULONG_BITS)
    rendered = [f"{word:x}" for word in reversed(words)]
    while len(rendered) > 1 and rendered[0] == "0":
        rendered.pop(0)
    return " ".join(rendered) + "\n"


class CapabilityBitmapTests(unittest.TestCase):
    def test_fixture_matches_the_kernel_rendering_of_a_gamepad_only_device(self):
        self.assertEqual(capabilities_key(BTN_GAMEPAD).strip(), "1000000000000 0 0 0 0")

    def test_native_word_bitmap_locates_btn_gamepad(self):
        self.assertTrue(_bitmap_has("1000000000000 0 0 0 0", BTN_GAMEPAD))

    def test_word_position_comes_from_spacing_not_digit_count(self):
        # The same digits in the most significant printed word mean a different
        # bit once a lower word is appended.
        self.assertTrue(_bitmap_has("1 0 0 0 0", 4 * ULONG_BITS))
        self.assertFalse(_bitmap_has("1 0 0 0 0", 5 * ULONG_BITS))
        self.assertTrue(_bitmap_has("1 0 0 0 0 0", 5 * ULONG_BITS))

    def test_low_word_bits_survive_leading_words(self):
        self.assertTrue(_bitmap_has(capabilities_key(1, BTN_GAMEPAD), 1))
        self.assertTrue(_bitmap_has(capabilities_key(1, BTN_GAMEPAD), BTN_GAMEPAD))

    def test_neighbouring_bits_are_not_confused_with_btn_gamepad(self):
        for neighbour in (BTN_GAMEPAD - 1, BTN_GAMEPAD + 1, ULONG_BITS, KEY_MAX):
            with self.subTest(neighbour=neighbour):
                self.assertFalse(_bitmap_has(capabilities_key(neighbour), BTN_GAMEPAD))
                self.assertTrue(_bitmap_has(capabilities_key(neighbour), neighbour))

    def test_zero_and_empty_bitmaps_report_absent(self):
        for text in ("0", "0 0 0 0 0", "", "   ", "\n"):
            with self.subTest(text=text):
                self.assertFalse(_bitmap_has(text, BTN_GAMEPAD))

    def test_malformed_bitmap_text_fails_closed(self):
        for text in ("zz 0 0 0 0", "0x1 0 0 0 0", "-1 0 0 0 0", "1000000000000, 0", "?"):
            with self.subTest(text=text):
                self.assertFalse(_bitmap_has(text, BTN_GAMEPAD))

    def test_single_oversized_word_is_read_as_one_absolute_value(self):
        # Not kernel output, but a lone word wider than an unsigned long stays
        # readable rather than silently dropping its high bits.
        self.assertTrue(_bitmap_has(f"{1 << BTN_GAMEPAD:x}", BTN_GAMEPAD))
        self.assertFalse(_bitmap_has(f"{1 << BTN_GAMEPAD:x}", BTN_GAMEPAD + 1))


class PeripheralInventoryTests(unittest.TestCase):
    def _inventory(self, root: Path):
        return SteamOsPeripheralInventory(
            input_root=root / "input", sound_root=root / "sound"
        )

    def test_real_scan_recognises_gamepad_in_native_sysfs_bitmap_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write(
                root / "input" / "event7" / "device" / "capabilities" / "key",
                capabilities_key(BTN_GAMEPAD),
            )
            write(
                root / "input" / "event2" / "device" / "capabilities" / "key",
                capabilities_key(BTN_GAMEPAD - 1, BTN_GAMEPAD + 1),
            )
            write(
                root / "input" / "event3" / "device" / "capabilities" / "key",
                capabilities_key(),
            )
            write(
                root / "input" / "event4" / "device" / "capabilities" / "key",
                "not-a-bitmap\n",
            )
            (root / "sound").mkdir()
            inventory = self._inventory(root).scan()
            self.assertTrue(inventory.controller_complete)
            self.assertEqual(inventory.controller_error, "")
            self.assertEqual(len(inventory.controller_bindings), 1)
            self.assertNotIn(str(root), repr(inventory))

    def test_read_only_inventory_hashes_gamepad_and_sound_nodes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write(root / "input" / "event7" / "device" / "capabilities" / "key", capabilities_key(BTN_GAMEPAD))
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
            write(root / "input" / "event1" / "device" / "capabilities" / "key", capabilities_key(BTN_GAMEPAD))
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
            write(root / "input" / "event1" / "device" / "capabilities" / "key", capabilities_key(BTN_GAMEPAD))
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
            write(root / "input" / "event1" / "device" / "capabilities" / "key", capabilities_key(BTN_GAMEPAD))
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
            write(root / "input" / "event9" / "device" / "capabilities" / "key", capabilities_key(BTN_GAMEPAD))
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
            write(root / "input" / "event1" / "device" / "capabilities" / "key", capabilities_key(BTN_GAMEPAD))
            (root / "sound" / "card0").mkdir(parents=True)
            adapter = SteamOsPeripheralObservationAdapter(self._inventory(root))
            first = adapter.observe()
            second = adapter.observe()
            self.assertEqual(first.generation, second.generation)
            self.assertNotEqual(first.sample_id, second.sample_id)
            write(root / "input" / "event9" / "device" / "capabilities" / "key", capabilities_key(BTN_GAMEPAD))
            changed = adapter.observe()
            self.assertNotEqual(first.generation, changed.generation)

    def test_public_status_omits_private_bindings_and_observation_ids(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write(root / "input" / "event1" / "device" / "capabilities" / "key", capabilities_key(BTN_GAMEPAD))
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
