from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.domain.game_adapter import (  # noqa: E402
    GameAdapterDescriptor,
    GameAdapterSupport,
    GameConfigChange,
    GameConfigChangeStage,
    GameConfigEffect,
    GameConfigEffectKind,
    GameSettingChange,
    begin_game_config_change,
    record_game_config_effect,
)


OLD = "a" * 64
NEW = "b" * 64


def change(support: GameAdapterSupport = GameAdapterSupport.REVIEWED) -> GameConfigChange:
    return GameConfigChange(
        "change-1",
        GameAdapterDescriptor("game.adapter", "12345", support, ("graphics.preset",)),
        OLD,
        (GameSettingChange("graphics.preset", "quality"),),
    )


def effect(kind: GameConfigEffectKind, revision: str = NEW) -> GameConfigEffect:
    return GameConfigEffect("change-1", kind, revision)


class GameAdapterContractTests(unittest.TestCase):
    def test_reviewed_adapter_requires_backup_atomic_stage_validation_and_commit(self):
        current = begin_game_config_change(change())
        self.assertEqual(current.stage, GameConfigChangeStage.BACKUP_REQUIRED)
        current = record_game_config_effect(
            current, effect(GameConfigEffectKind.BACKUP_CREATED, OLD)
        )
        self.assertEqual(current.stage, GameConfigChangeStage.STAGING_REQUIRED)
        current = record_game_config_effect(current, effect(GameConfigEffectKind.ATOMIC_STAGE_WRITTEN))
        self.assertEqual(current.stage, GameConfigChangeStage.VALIDATION_REQUIRED)
        current = record_game_config_effect(
            current, effect(GameConfigEffectKind.STAGED_CONFIG_VALIDATED)
        )
        self.assertEqual(current.stage, GameConfigChangeStage.COMMIT_REQUIRED)
        current = record_game_config_effect(current, effect(GameConfigEffectKind.COMMIT_CONFIRMED))
        self.assertEqual(current.stage, GameConfigChangeStage.COMMITTED)

    def test_unreviewed_adapter_and_out_of_order_effect_fail_closed(self):
        blocked = begin_game_config_change(change(GameAdapterSupport.UNKNOWN))
        self.assertEqual(blocked.stage, GameConfigChangeStage.ACTION_REQUIRED)
        self.assertEqual(blocked.reason, "game_config.adapter_unreviewed")

        invalid = record_game_config_effect(
            begin_game_config_change(change()), effect(GameConfigEffectKind.COMMIT_CONFIRMED)
        )
        self.assertEqual(invalid.stage, GameConfigChangeStage.ACTION_REQUIRED)
        self.assertEqual(invalid.reason, "game_config.effect_out_of_order")

    def test_failure_after_backup_requires_verified_rollback(self):
        current = begin_game_config_change(change())
        current = record_game_config_effect(current, effect(GameConfigEffectKind.BACKUP_CREATED, OLD))
        failed = record_game_config_effect(
            current,
            GameConfigEffect("change-1", GameConfigEffectKind.FAILURE, reason="game_config.stage_failed"),
        )
        self.assertEqual(failed.stage, GameConfigChangeStage.ROLLBACK_REQUIRED)
        restored = record_game_config_effect(
            failed, effect(GameConfigEffectKind.ROLLBACK_CONFIRMED, OLD)
        )
        self.assertEqual(restored.stage, GameConfigChangeStage.ROLLED_BACK)

    def test_constructor_rejects_unknown_settings_and_duplicate_changes(self):
        with self.assertRaisesRegex(ValueError, "adapter-supported"):
            GameConfigChange(
                "change-1",
                GameAdapterDescriptor("game.adapter", "12345", GameAdapterSupport.REVIEWED, ("graphics.preset",)),
                OLD,
                (GameSettingChange("graphics.fov", "90"),),
            )
        with self.assertRaisesRegex(ValueError, "unique"):
            GameConfigChange(
                "change-1",
                GameAdapterDescriptor("game.adapter", "12345", GameAdapterSupport.REVIEWED, ("graphics.preset",)),
                OLD,
                (
                    GameSettingChange("graphics.preset", "quality"),
                    GameSettingChange("graphics.preset", "balanced"),
                ),
            )


if __name__ == "__main__":
    unittest.main()
