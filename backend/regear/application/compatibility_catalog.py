"""Backend-only catalog transactions for intentionally reviewed evidence."""

from __future__ import annotations

from ..domain.game_compatibility import (
    CompatibilityEvidence,
    EgpuHandoffStatus,
    GameCompatibilityRecord,
    GameSaveCapability,
    promote_egpu_handoff,
    promote_save_sleep,
)
from ..domain.hardware_compatibility import (
    HardwareCapability,
    HardwareCatalogStatus,
    HardwareCompatibilityRecord,
    HardwareEvidence,
    promote_hardware_capability,
    promote_hardware_combination,
)
from ..ports.compatibility_catalog import CompatibilityCatalogPort


class CompatibilityCatalogService:
    """Never constructs evidence, reviews it, or exposes a delivery endpoint."""

    def __init__(self, catalogs: CompatibilityCatalogPort) -> None:
        self._catalogs = catalogs

    def register_game(self, record: GameCompatibilityRecord) -> GameCompatibilityRecord:
        if record.promotions or record.egpu_handoff is not EgpuHandoffStatus.UNTESTED or record.save_sleep is not GameSaveCapability.UNTESTED:
            raise ValueError("new game compatibility record must be untested")
        self._catalogs.update_games(
            lambda current: self._append_game(current, record)
        )
        return record

    def promote_game_egpu(
        self,
        catalog_id: str,
        status: EgpuHandoffStatus,
        evidence: CompatibilityEvidence,
    ) -> GameCompatibilityRecord:
        updated = self._catalogs.update_games(
            lambda current: self._replace_game(
                current,
                catalog_id,
                lambda record: promote_egpu_handoff(record, status, evidence),
            )
        )
        return self._find_game(updated, catalog_id)

    def promote_game_save_sleep(
        self,
        catalog_id: str,
        status: GameSaveCapability,
        evidence: CompatibilityEvidence,
    ) -> GameCompatibilityRecord:
        updated = self._catalogs.update_games(
            lambda current: self._replace_game(
                current,
                catalog_id,
                lambda record: promote_save_sleep(record, status, evidence),
            )
        )
        return self._find_game(updated, catalog_id)

    def register_hardware(
        self, record: HardwareCompatibilityRecord
    ) -> HardwareCompatibilityRecord:
        if record.promotions or record.claims or record.combination_status is not HardwareCatalogStatus.UNTESTED:
            raise ValueError("new hardware compatibility record must be untested")
        self._catalogs.update_hardware(
            lambda current: self._append_hardware(current, record)
        )
        return record

    def promote_hardware_combination(
        self,
        catalog_id: str,
        status: HardwareCatalogStatus,
        evidence: HardwareEvidence,
    ) -> HardwareCompatibilityRecord:
        updated = self._catalogs.update_hardware(
            lambda current: self._replace_hardware(
                current,
                catalog_id,
                lambda record: promote_hardware_combination(record, status, evidence),
            )
        )
        return self._find_hardware(updated, catalog_id)

    def promote_hardware_capability(
        self,
        catalog_id: str,
        capability: HardwareCapability,
        status: HardwareCatalogStatus,
        evidence: HardwareEvidence,
    ) -> HardwareCompatibilityRecord:
        updated = self._catalogs.update_hardware(
            lambda current: self._replace_hardware(
                current,
                catalog_id,
                lambda record: promote_hardware_capability(
                    record, capability, status, evidence
                ),
            )
        )
        return self._find_hardware(updated, catalog_id)

    @staticmethod
    def _append_game(
        current: tuple[GameCompatibilityRecord, ...], record: GameCompatibilityRecord
    ) -> tuple[GameCompatibilityRecord, ...]:
        if any(item.catalog_id == record.catalog_id for item in current):
            raise ValueError("game compatibility catalog record already exists")
        return (*current, record)

    @staticmethod
    def _append_hardware(
        current: tuple[HardwareCompatibilityRecord, ...], record: HardwareCompatibilityRecord
    ) -> tuple[HardwareCompatibilityRecord, ...]:
        if any(item.catalog_id == record.catalog_id for item in current):
            raise ValueError("hardware compatibility catalog record already exists")
        return (*current, record)

    @classmethod
    def _replace_game(cls, current, catalog_id, change):
        cls._find_game(current, catalog_id)
        return tuple(change(item) if item.catalog_id == catalog_id else item for item in current)

    @classmethod
    def _replace_hardware(cls, current, catalog_id, change):
        cls._find_hardware(current, catalog_id)
        return tuple(change(item) if item.catalog_id == catalog_id else item for item in current)

    @staticmethod
    def _find_game(
        records: tuple[GameCompatibilityRecord, ...], catalog_id: str
    ) -> GameCompatibilityRecord:
        for item in records:
            if item.catalog_id == catalog_id:
                return item
        raise ValueError("game compatibility catalog record is unknown")

    @staticmethod
    def _find_hardware(
        records: tuple[HardwareCompatibilityRecord, ...], catalog_id: str
    ) -> HardwareCompatibilityRecord:
        for item in records:
            if item.catalog_id == catalog_id:
                return item
        raise ValueError("hardware compatibility catalog record is unknown")
