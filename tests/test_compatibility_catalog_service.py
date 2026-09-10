from __future__ import annotations

import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.application.compatibility_catalog import CompatibilityCatalogService  # noqa: E402
from regear.delivery.compatibility_catalog_store import FileCompatibilityCatalogStore  # noqa: E402
from regear.domain.game_compatibility import (  # noqa: E402
    CompatibilityEvidence,
    CompatibilityEvidenceKind,
    EgpuHandoffStatus,
    GameCompatibilityRecord,
    ObservedRenderGpu,
)
from regear.domain.hardware_compatibility import (  # noqa: E402
    HardwareCapability,
    HardwareCatalogStatus,
    HardwareCompatibilityRecord,
    HardwareEvidence,
    HardwareEvidenceKind,
)


def game():
    return GameCompatibilityRecord(
        "game-1", "Fixture Game", "test-host", "test-egpu", "1234"
    )


def game_evidence(**changes):
    value = CompatibilityEvidence(
        "game-evidence-1",
        "game-1",
        "1234",
        CompatibilityEvidenceKind.HARDWARE_TEST,
        True,
        True,
        "test-host",
        "test-egpu",
        "0.2.0",
        "steamos-2026",
        "2026-08-31T12:00:00Z",
        ObservedRenderGpu.EXTERNAL,
    )
    return replace(value, **changes)


def hardware():
    return HardwareCompatibilityRecord("hardware-1", "test-host", "test-egpu")


def hardware_evidence():
    return HardwareEvidence(
        "hardware-evidence-1",
        HardwareCapability.EGPU_DETECTION,
        HardwareCatalogStatus.VERIFIED,
        HardwareEvidenceKind.READ_ONLY_HARDWARE_TEST,
        True,
        True,
        "test-host",
        "test-egpu",
        "0.2.0",
        "steamos-2026",
        "2026-08-31T12:00:00Z",
    )


class CompatibilityCatalogServiceTests(unittest.TestCase):
    def service(self, root: str) -> tuple[CompatibilityCatalogService, FileCompatibilityCatalogStore]:
        store = FileCompatibilityCatalogStore(Path(root).resolve())
        return CompatibilityCatalogService(store), store

    def test_registers_untested_records_then_persists_reviewed_promotions(self):
        with tempfile.TemporaryDirectory() as directory:
            service, store = self.service(directory)
            service.register_game(game())
            service.register_hardware(hardware())

            promoted_game = service.promote_game_egpu(
                "game-1", EgpuHandoffStatus.VERIFIED, game_evidence()
            )
            promoted_hardware = service.promote_hardware_capability(
                "hardware-1",
                HardwareCapability.EGPU_DETECTION,
                HardwareCatalogStatus.VERIFIED,
                hardware_evidence(),
            )

            self.assertEqual(promoted_game.egpu_handoff, EgpuHandoffStatus.VERIFIED)
            self.assertEqual(
                promoted_hardware.status_for(HardwareCapability.EGPU_DETECTION),
                HardwareCatalogStatus.VERIFIED,
            )
            self.assertEqual(store.load_games(), (promoted_game,))
            self.assertEqual(store.load_hardware(), (promoted_hardware,))

    def test_simulation_or_unknown_record_never_mutates_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            service, store = self.service(directory)
            service.register_game(game())
            simulated = game_evidence(kind=CompatibilityEvidenceKind.SIMULATION)

            with self.assertRaisesRegex(ValueError, "simulation"):
                service.promote_game_egpu(
                    "game-1", EgpuHandoffStatus.VERIFIED, simulated
                )
            with self.assertRaisesRegex(ValueError, "unknown"):
                service.promote_game_egpu(
                    "missing", EgpuHandoffStatus.VERIFIED, game_evidence()
                )

            self.assertEqual(store.load_games(), (game(),))

    def test_registration_cannot_replace_existing_or_prepromoted_records(self):
        with tempfile.TemporaryDirectory() as directory:
            service, _store = self.service(directory)
            service.register_game(game())
            with self.assertRaisesRegex(ValueError, "already exists"):
                service.register_game(game())
            promoted = service.promote_game_egpu(
                "game-1", EgpuHandoffStatus.VERIFIED, game_evidence()
            )
            with self.assertRaisesRegex(ValueError, "must be untested"):
                service.register_game(promoted)


if __name__ == "__main__":
    unittest.main()
