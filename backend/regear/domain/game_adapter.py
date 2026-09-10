"""Pure, fail-closed contract for future per-game settings adapters.

No production adapter is constructed from this module. It intentionally carries
only opaque revision digests and typed setting names/values: paths, file bytes,
commands, and game process identity stay outside the domain and must never be
provided by a frontend request.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from enum import StrEnum

from .game_compatibility import STEAM_APP_ID_RE


TOKEN_RE = re.compile(r"^[A-Za-z0-9_.-]{1,96}$")
SETTING_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_CHANGE_OPERATIONS = 32


class GameAdapterSupport(StrEnum):
    UNKNOWN = "unknown"
    REVIEWED = "reviewed"


class GameConfigChangeStage(StrEnum):
    PREVIEW = "preview"
    BACKUP_REQUIRED = "backup_required"
    STAGING_REQUIRED = "staging_required"
    VALIDATION_REQUIRED = "validation_required"
    COMMIT_REQUIRED = "commit_required"
    COMMITTED = "committed"
    ROLLBACK_REQUIRED = "rollback_required"
    ROLLED_BACK = "rolled_back"
    ACTION_REQUIRED = "action_required"


class GameConfigEffectKind(StrEnum):
    BACKUP_CREATED = "backup_created"
    ATOMIC_STAGE_WRITTEN = "atomic_stage_written"
    STAGED_CONFIG_VALIDATED = "staged_config_validated"
    COMMIT_CONFIRMED = "commit_confirmed"
    ROLLBACK_CONFIRMED = "rollback_confirmed"
    FAILURE = "failure"


@dataclass(frozen=True, slots=True)
class GameAdapterDescriptor:
    adapter_id: str
    steam_app_id: str
    support: GameAdapterSupport
    supported_settings: tuple[str, ...]

    def __post_init__(self) -> None:
        if not TOKEN_RE.fullmatch(self.adapter_id):
            raise ValueError("game adapter ID is invalid")
        if not STEAM_APP_ID_RE.fullmatch(self.steam_app_id):
            raise ValueError("game adapter Steam AppID is invalid")
        if not self.supported_settings or len(self.supported_settings) > 128:
            raise ValueError("game adapter settings are invalid")
        if len(self.supported_settings) != len(set(self.supported_settings)) or any(
            not SETTING_RE.fullmatch(setting) for setting in self.supported_settings
        ):
            raise ValueError("game adapter setting names are invalid")


@dataclass(frozen=True, slots=True)
class GameSettingChange:
    setting: str
    value: str

    def __post_init__(self) -> None:
        if not SETTING_RE.fullmatch(self.setting):
            raise ValueError("game setting name is invalid")
        if not self.value or len(self.value) > 256 or "\x00" in self.value:
            raise ValueError("game setting value is invalid")


@dataclass(frozen=True, slots=True)
class GameConfigChange:
    change_id: str
    adapter: GameAdapterDescriptor
    expected_revision_sha256: str
    changes: tuple[GameSettingChange, ...]
    stage: GameConfigChangeStage = GameConfigChangeStage.PREVIEW
    backup_revision_sha256: str = ""
    staged_revision_sha256: str = ""
    reason: str = "game_config.preview"

    def __post_init__(self) -> None:
        if not TOKEN_RE.fullmatch(self.change_id):
            raise ValueError("game configuration change ID is invalid")
        if not DIGEST_RE.fullmatch(self.expected_revision_sha256):
            raise ValueError("game configuration expected revision is invalid")
        if not self.changes or len(self.changes) > MAX_CHANGE_OPERATIONS:
            raise ValueError("game configuration changes are invalid")
        settings = tuple(change.setting for change in self.changes)
        if len(settings) != len(set(settings)):
            raise ValueError("game configuration settings must be unique")
        if any(setting not in self.adapter.supported_settings for setting in settings):
            raise ValueError("game configuration change is not adapter-supported")
        if not TOKEN_RE.fullmatch(self.reason):
            raise ValueError("game configuration reason is invalid")
        if self.stage is GameConfigChangeStage.PREVIEW:
            if self.backup_revision_sha256 or self.staged_revision_sha256:
                raise ValueError("game configuration preview contains effect evidence")
        if self.backup_revision_sha256 and not DIGEST_RE.fullmatch(
            self.backup_revision_sha256
        ):
            raise ValueError("game configuration backup revision is invalid")
        if self.staged_revision_sha256 and not DIGEST_RE.fullmatch(
            self.staged_revision_sha256
        ):
            raise ValueError("game configuration staged revision is invalid")


@dataclass(frozen=True, slots=True)
class GameConfigEffect:
    change_id: str
    kind: GameConfigEffectKind
    revision_sha256: str = ""
    reason: str = ""

    def __post_init__(self) -> None:
        if not TOKEN_RE.fullmatch(self.change_id):
            raise ValueError("game configuration effect ID is invalid")
        if self.kind is GameConfigEffectKind.FAILURE:
            if not TOKEN_RE.fullmatch(self.reason):
                raise ValueError("game configuration failure reason is invalid")
            if self.revision_sha256:
                raise ValueError("game configuration failure cannot carry a revision")
        elif not DIGEST_RE.fullmatch(self.revision_sha256):
            raise ValueError("game configuration effect revision is invalid")


def begin_game_config_change(change: GameConfigChange) -> GameConfigChange:
    """Require reviewed adapter metadata before any future mechanism is invoked."""
    if change.stage is not GameConfigChangeStage.PREVIEW:
        return _action_required(change, "game_config.begin_out_of_order")
    if change.adapter.support is not GameAdapterSupport.REVIEWED:
        return _action_required(change, "game_config.adapter_unreviewed")
    return replace(change, stage=GameConfigChangeStage.BACKUP_REQUIRED)


def record_game_config_effect(
    change: GameConfigChange, effect: GameConfigEffect
) -> GameConfigChange:
    """Advance one bounded backup/stage/validate/commit/rollback effect.

    A mechanism must compare the expected revision before every write, create a
    backup before staging, write atomically, validate the staged configuration,
    and confirm the final revision. Any failure routes to rollback rather than
    silently treating a partial game configuration update as success.
    """
    if effect.change_id != change.change_id:
        return _action_required(change, "game_config.effect_identity_changed")
    if change.stage in {
        GameConfigChangeStage.COMMITTED,
        GameConfigChangeStage.ROLLED_BACK,
        GameConfigChangeStage.ACTION_REQUIRED,
    }:
        return _action_required(change, "game_config.effect_after_terminal")
    if effect.kind is GameConfigEffectKind.FAILURE:
        if change.backup_revision_sha256:
            return replace(
                change,
                stage=GameConfigChangeStage.ROLLBACK_REQUIRED,
                reason=effect.reason,
            )
        return _action_required(change, effect.reason)
    if (
        change.stage is GameConfigChangeStage.BACKUP_REQUIRED
        and effect.kind is GameConfigEffectKind.BACKUP_CREATED
        and effect.revision_sha256 == change.expected_revision_sha256
    ):
        return replace(
            change,
            stage=GameConfigChangeStage.STAGING_REQUIRED,
            backup_revision_sha256=effect.revision_sha256,
            reason="game_config.backup_created",
        )
    if (
        change.stage is GameConfigChangeStage.STAGING_REQUIRED
        and effect.kind is GameConfigEffectKind.ATOMIC_STAGE_WRITTEN
        and effect.revision_sha256 != change.expected_revision_sha256
    ):
        return replace(
            change,
            stage=GameConfigChangeStage.VALIDATION_REQUIRED,
            staged_revision_sha256=effect.revision_sha256,
            reason="game_config.atomic_stage_written",
        )
    if (
        change.stage is GameConfigChangeStage.VALIDATION_REQUIRED
        and effect.kind is GameConfigEffectKind.STAGED_CONFIG_VALIDATED
        and effect.revision_sha256 == change.staged_revision_sha256
    ):
        return replace(
            change,
            stage=GameConfigChangeStage.COMMIT_REQUIRED,
            reason="game_config.staged_validated",
        )
    if (
        change.stage is GameConfigChangeStage.COMMIT_REQUIRED
        and effect.kind is GameConfigEffectKind.COMMIT_CONFIRMED
        and effect.revision_sha256 == change.staged_revision_sha256
    ):
        return replace(
            change,
            stage=GameConfigChangeStage.COMMITTED,
            reason="game_config.committed",
        )
    if (
        change.stage is GameConfigChangeStage.ROLLBACK_REQUIRED
        and effect.kind is GameConfigEffectKind.ROLLBACK_CONFIRMED
        and effect.revision_sha256 == change.backup_revision_sha256
    ):
        return replace(
            change,
            stage=GameConfigChangeStage.ROLLED_BACK,
            reason="game_config.rolled_back",
        )
    return _action_required(change, "game_config.effect_out_of_order")


def _action_required(change: GameConfigChange, reason: str) -> GameConfigChange:
    return replace(change, stage=GameConfigChangeStage.ACTION_REQUIRED, reason=reason)
