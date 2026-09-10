from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.adapters.game_runtime import (  # noqa: E402
    CgroupProcGameRuntimeAdapter,
)
from regear.domain.game_runtime import (  # noqa: E402
    ActiveGameRuntimeObservation,
    GameProcessInstance,
    GameRuntimeKind,
)
from regear.domain.game_session import ActiveGameIdentity  # noqa: E402


UID = 1000
SCOPE = "app-steam-app1234-test.scope"
IDENTITY = ActiveGameIdentity("1234", (SCOPE,))


def stat_line(pid: int, parent_pid: int, start_time_ticks: int) -> str:
    fields = ["S", str(parent_pid), *("0" for _ in range(48))]
    fields[19] = str(start_time_ticks)
    return f"{pid} (game process) {' '.join(fields)}\n"


class RuntimeFixture:
    def __init__(self, root: Path) -> None:
        self.cgroup = root / "cgroup"
        self.proc = root / "proc"
        self.service = (
            self.cgroup
            / "user.slice"
            / f"user-{UID}.slice"
            / f"user@{UID}.service"
        )
        self.scope = self.service / SCOPE
        self.scope.mkdir(parents=True)
        self.proc.mkdir()
        self.executables: dict[str, str] = {}

    def add_process(
        self,
        pid: int,
        *,
        parent_pid: int,
        start_time_ticks: int,
        executable: str,
        environment: bytes = b"",
    ) -> None:
        directory = self.proc / str(pid)
        directory.mkdir()
        (directory / "stat").write_text(
            stat_line(pid, parent_pid, start_time_ticks), encoding="utf-8"
        )
        (directory / "environ").write_bytes(environment)
        self.executables[str(directory / "exe")] = executable

    def finish(self, pids: tuple[int, ...]) -> None:
        (self.scope / "cgroup.procs").write_text(
            "".join(f"{pid}\n" for pid in pids), encoding="ascii"
        )

    def adapter(self) -> CgroupProcGameRuntimeAdapter:
        return CgroupProcGameRuntimeAdapter(
            cgroup_root=self.cgroup,
            proc_root=self.proc,
            readlink=lambda path: self.executables[str(path)],
        )


class GameRuntimeAdapterTests(unittest.TestCase):
    def test_exact_native_process_graph_has_stable_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(Path(directory))
            fixture.add_process(
                20,
                parent_pid=10,
                start_time_ticks=200,
                executable="/games/launcher",
                environment=b"SteamAppId=1234\0",
            )
            fixture.add_process(
                21,
                parent_pid=20,
                start_time_ticks=210,
                executable="/games/game",
                environment=b"SteamGameId=1234\0",
            )
            fixture.finish((20, 21))
            adapter = fixture.adapter()

            first = adapter.observe(IDENTITY, user_uid=UID)
            second = adapter.observe(IDENTITY, user_uid=UID)

        self.assertTrue(first.exact)
        self.assertEqual(first.runtime_kind, GameRuntimeKind.NATIVE)
        self.assertEqual([value.pid for value in first.processes], [20, 21])
        self.assertEqual([value.pid for value in first.root_processes], [20])
        self.assertEqual(first.generation, second.generation)
        self.assertNotEqual(first.sample_id, second.sample_id)

    def test_any_exact_proton_marker_classifies_the_session(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(Path(directory))
            fixture.add_process(
                30,
                parent_pid=1,
                start_time_ticks=300,
                executable="/runtime/wine64-preloader",
                environment=(
                    b"SteamAppId=1234\0"
                    b"STEAM_COMPAT_DATA_PATH=/private/path\0"
                    b"IGNORED_SECRET=do-not-retain\0"
                ),
            )
            fixture.finish((30,))
            result = fixture.adapter().observe(IDENTITY, user_uid=UID)

        self.assertTrue(result.exact)
        self.assertEqual(result.runtime_kind, GameRuntimeKind.PROTON)
        self.assertTrue(result.processes[0].proton_marker)
        self.assertNotIn("private", repr(result))
        self.assertNotIn("IGNORED_SECRET", repr(result))

    def test_changed_app_identity_or_missing_proc_evidence_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(Path(directory))
            fixture.add_process(
                40,
                parent_pid=1,
                start_time_ticks=400,
                executable="/games/game",
                environment=b"SteamAppId=9999\0",
            )
            fixture.finish((40,))
            changed = fixture.adapter().observe(IDENTITY, user_uid=UID)
            fixture.finish((41,))
            missing = fixture.adapter().observe(IDENTITY, user_uid=UID)

        self.assertFalse(changed.exact)
        self.assertEqual(changed.error_code, "game_runtime.app_identity_changed")
        self.assertEqual(changed.runtime_kind, GameRuntimeKind.UNKNOWN)
        self.assertEqual(changed.processes, ())
        self.assertEqual(missing.error_code, "game_runtime.process_unavailable")

    def test_missing_scope_invalid_user_and_unbounded_pid_set_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(Path(directory))
            fixture.finish(tuple(range(1, 130)))
            adapter = fixture.adapter()
            unbounded = adapter.observe(IDENTITY, user_uid=UID)
            invalid_user = adapter.observe(IDENTITY, user_uid=0)
            missing = adapter.observe(
                ActiveGameIdentity("1234", ("app-steam-app1234-other.scope",)),
                user_uid=UID,
            )

        self.assertEqual(unbounded.error_code, "game_runtime.process_limit")
        self.assertEqual(invalid_user.error_code, "game_runtime.user_invalid")
        self.assertEqual(missing.error_code, "game_runtime.scope_missing")

    def test_malformed_cgroup_pid_is_categorical_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(Path(directory))
            (fixture.scope / "cgroup.procs").write_text(
                "12\nnot-a-pid\n", encoding="utf-8"
            )
            result = fixture.adapter().observe(IDENTITY, user_uid=UID)

        self.assertFalse(result.exact)
        self.assertEqual(result.error_code, "game_runtime.pid_invalid")


class GameRuntimeDomainTests(unittest.TestCase):
    def test_complete_classification_must_match_private_process_evidence(self):
        process = GameProcessInstance(10, 20, 1, "game", proton_marker=True)
        with self.assertRaisesRegex(ValueError, "classification"):
            ActiveGameRuntimeObservation(
                "1234",
                (SCOPE,),
                (process,),
                GameRuntimeKind.NATIVE,
                "a" * 64,
                "b" * 64,
                True,
            )

    def test_incomplete_observation_cannot_carry_process_identity(self):
        process = GameProcessInstance(10, 20, 1, "game", proton_marker=False)
        with self.assertRaisesRegex(ValueError, "fail closed"):
            ActiveGameRuntimeObservation(
                "1234",
                (SCOPE,),
                (process,),
                GameRuntimeKind.UNKNOWN,
                "a" * 64,
                "b" * 64,
                False,
                "game_runtime.unavailable",
            )


if __name__ == "__main__":
    unittest.main()
