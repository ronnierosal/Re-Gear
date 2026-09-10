from __future__ import annotations

import dataclasses
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.application.game_gpu_client import (  # noqa: E402
    GameEgpuClientEvidenceService,
)
from regear.domain.game_gpu_client import GameEgpuClientStatus  # noqa: E402
from regear.domain.game_runtime import (  # noqa: E402
    ActiveGameRuntimeObservation,
    GameProcessInstance,
    GameRuntimeKind,
)
from regear.domain.game_session import ActiveGameIdentity  # noqa: E402
from regear.domain.models import (  # noqa: E402
    EgpuClientKind,
    EgpuClientObservation,
    EgpuResourceKind,
    GameState,
)
from regear.domain.serialization import snapshot_from_dict  # noqa: E402
from regear.ports.transition import VersionedObservation  # noqa: E402


FIXTURES = ROOT / "tests" / "fixtures"
IDENTITY = ActiveGameIdentity("1234", ("app-steam-app1234-test.scope",))


def runtime(*, generation="a" * 64, sample="b" * 64):
    return ActiveGameRuntimeObservation(
        "1234",
        IDENTITY.scopes,
        (GameProcessInstance(101, 500, 1, "game", False),),
        GameRuntimeKind.NATIVE,
        generation,
        sample,
        True,
    )


def client(*, start="500", kind=EgpuClientKind.GAME, resources=None):
    return EgpuClientObservation(
        "private-instance",
        101,
        "game",
        kind,
        resources or (EgpuResourceKind.DRM_RENDER,),
        False,
        "Steam game scope",
        start,
    )


def snapshot(*, clients=()):
    value = json.loads((FIXTURES / "tv-docked.json").read_text(encoding="utf-8"))
    result = snapshot_from_dict(value)
    return dataclasses.replace(
        result,
        game_state=GameState.RUNNING,
        disconnect_readiness=dataclasses.replace(
            result.disconnect_readiness,
            clients=tuple(clients),
            ready=not clients,
        ),
    )


class RuntimePort:
    def __init__(self, *values):
        self.values = list(values)

    def observe(self, identity, *, user_uid):
        self.identity = identity
        self.user_uid = user_uid
        return self.values.pop(0)


class SnapshotPort:
    def __init__(self, value):
        self.value = value

    def observe(self):
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


def service(before, after, value):
    return GameEgpuClientEvidenceService(
        runtime=RuntimePort(before, after),
        snapshots=SnapshotPort(VersionedObservation("snapshot", value, "sample")),
    )


class GameEgpuClientEvidenceTests(unittest.TestCase):
    def test_stable_exact_game_render_client_is_present_but_not_render_proof(self):
        result = service(
            runtime(sample="b" * 64),
            runtime(sample="c" * 64),
            snapshot(clients=(client(),)),
        ).observe(IDENTITY, user_uid=1000)

        self.assertEqual(result.status, GameEgpuClientStatus.PRESENT)
        self.assertEqual(result.matched_process_count, 1)
        self.assertEqual(result.runtime_kind, GameRuntimeKind.NATIVE)
        self.assertFalse(result.proves_rendering_gpu)

    def test_complete_exact_scan_can_prove_render_client_absent(self):
        result = service(
            runtime(sample="b" * 64),
            runtime(sample="c" * 64),
            snapshot(clients=()),
        ).observe(IDENTITY, user_uid=1000)

        self.assertEqual(result.status, GameEgpuClientStatus.ABSENT)
        self.assertFalse(result.proves_rendering_gpu)

    def test_runtime_change_or_pid_reuse_fails_closed(self):
        changed = service(
            runtime(generation="a" * 64, sample="b" * 64),
            runtime(generation="d" * 64, sample="c" * 64),
            snapshot(clients=(client(),)),
        ).observe(IDENTITY, user_uid=1000)
        reused = service(
            runtime(sample="b" * 64),
            runtime(sample="c" * 64),
            snapshot(clients=(client(start="999"),)),
        ).observe(IDENTITY, user_uid=1000)

        self.assertEqual(changed.status, GameEgpuClientStatus.UNKNOWN)
        self.assertEqual(changed.reason_code, "game_gpu.runtime_changed")
        self.assertEqual(reused.status, GameEgpuClientStatus.UNKNOWN)
        self.assertEqual(reused.reason_code, "game_gpu.process_identity_changed")

    def test_incomplete_scan_or_classification_conflict_fails_closed(self):
        incomplete_snapshot = dataclasses.replace(
            snapshot(clients=(client(),)),
            disconnect_readiness=dataclasses.replace(
                snapshot().disconnect_readiness, scan_complete=False
            ),
        )
        incomplete = service(
            runtime(sample="b" * 64),
            runtime(sample="c" * 64),
            incomplete_snapshot,
        ).observe(IDENTITY, user_uid=1000)
        conflict = service(
            runtime(sample="b" * 64),
            runtime(sample="c" * 64),
            snapshot(clients=(client(kind=EgpuClientKind.USER),)),
        ).observe(IDENTITY, user_uid=1000)

        self.assertEqual(incomplete.status, GameEgpuClientStatus.UNKNOWN)
        self.assertEqual(incomplete.reason_code, "game_gpu.egpu_scan_unverified")
        self.assertEqual(conflict.status, GameEgpuClientStatus.UNKNOWN)
        self.assertEqual(
            conflict.reason_code, "game_gpu.client_classification_conflict"
        )

    def test_audio_only_client_does_not_count_as_render_client(self):
        result = service(
            runtime(sample="b" * 64),
            runtime(sample="c" * 64),
            snapshot(
                clients=(client(resources=(EgpuResourceKind.AUDIO_PCM,)),)
            ),
        ).observe(IDENTITY, user_uid=1000)

        self.assertEqual(result.status, GameEgpuClientStatus.ABSENT)

    def test_invalid_user_or_runtime_identity_fails_closed(self):
        valid_before = runtime(sample="b" * 64)
        valid_after = runtime(sample="c" * 64)
        invalid_user = service(
            valid_before, valid_after, snapshot()
        ).observe(IDENTITY, user_uid=0)
        other_identity = dataclasses.replace(
            valid_before,
            steam_app_id="9999",
        )
        changed_identity = service(
            other_identity, valid_after, snapshot()
        ).observe(IDENTITY, user_uid=1000)

        self.assertEqual(invalid_user.reason_code, "game_gpu.user_invalid")
        self.assertEqual(
            changed_identity.reason_code, "game_gpu.runtime_unavailable"
        )


if __name__ == "__main__":
    unittest.main()
