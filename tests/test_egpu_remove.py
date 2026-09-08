from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from hdm import egpu_remove  # noqa: E402
from hdm.domain.device_removal import (  # noqa: E402
    RemovalFunctionKind,
    compose_removal_plan,
)
from hdm.domain.removal_safety import RemovalSafety, RemovalSafetyState  # noqa: E402
from hdm.domain.safe_undock_readiness import SafeUndockRevalidation  # noqa: E402
from hdm.ports.device_removal import (  # noqa: E402
    RemovalOutcome,
    RemovalResult,
    RescanOutcome,
    RescanResult,
)


GPU_BDF = "0000:08:00.0"
AUDIO_BDF = "0000:08:00.1"
BINDING = "egpu-stable-id"


def ready(
    sample: str = "sample-1", generation: str = "generation-1"
) -> RemovalSafety:
    """A readiness verdict whose sample differs per call, as real ones do."""
    return RemovalSafety(
        RemovalSafetyState.READY_FOR_SUPERVISED_REMOVAL,
        "removal_safety.ready_for_supervised_removal",
        SafeUndockRevalidation(BINDING, generation, sample),
    )


def blocked() -> RemovalSafety:
    return RemovalSafety(
        RemovalSafetyState.NOT_READY, "removal_safety.clients_active_or_protected"
    )


class RecordingRemoval:
    """A removal port that records calls instead of writing to sysfs."""

    def __init__(self, failures: dict[str, RemovalOutcome] | None = None) -> None:
        self.removed: list[str] = []
        self.rescanned: list[tuple[str, ...]] = []
        self._failures = failures or {}

    def remove(self, address: str) -> RemovalResult:
        self.removed.append(address)
        outcome = self._failures.get(address, RemovalOutcome.REMOVED)
        return RemovalResult(address, outcome, "" if outcome is RemovalOutcome.REMOVED else "x")

    def rescan(self, expected: tuple[str, ...]) -> RescanResult:
        self.rescanned.append(expected)
        return RescanResult(RescanOutcome.RESTORED, expected)


class FunctionDerivationTests(unittest.TestCase):
    def test_audio_is_derived_as_function_one(self) -> None:
        self.assertEqual(egpu_remove.egpu_functions(GPU_BDF), (GPU_BDF, AUDIO_BDF))

    def test_both_kinds_are_named_for_the_planner(self) -> None:
        functions = egpu_remove.removal_functions(GPU_BDF, AUDIO_BDF)
        self.assertEqual(
            {function.kind for function in functions},
            {RemovalFunctionKind.GPU, RemovalFunctionKind.AUDIO},
        )


class ExecutionOrderTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.object(egpu_remove, "report", lambda text="": None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def plan(self):
        return compose_removal_plan(
            ready(), egpu_remove.removal_functions(GPU_BDF, AUDIO_BDF)
        )

    def test_audio_is_detached_before_the_gpu(self) -> None:
        removal = RecordingRemoval()
        self.assertEqual(egpu_remove.execute(self.plan(), removal), 0)
        self.assertEqual(removal.removed, [AUDIO_BDF, GPU_BDF])

    def test_a_failed_detach_stops_before_the_next_function(self) -> None:
        removal = RecordingRemoval({AUDIO_BDF: RemovalOutcome.STILL_PRESENT})
        self.assertEqual(egpu_remove.execute(self.plan(), removal), 1)
        # The GPU function is never touched, so a stopped run leaves exactly
        # one function detached rather than an unknown number.
        self.assertEqual(removal.removed, [AUDIO_BDF])


class MainTests(unittest.TestCase):
    def run_main(self, argv, observations, *, root=True, removal=None):
        """Run `main` with observation and write capability under test control."""
        removal = removal or RecordingRemoval()
        with (
            mock.patch.object(egpu_remove, "SnapshotService", mock.Mock()),
            mock.patch.object(egpu_remove, "SteamOsDiscovery", mock.Mock()),
            mock.patch.object(
                egpu_remove, "SteamOsPeripheralObservationAdapter", mock.Mock()
            ),
            mock.patch.object(egpu_remove, "SysfsDeviceRemoval", lambda: removal),
            mock.patch.object(
                egpu_remove.os, "geteuid", lambda: 0 if root else 1000, create=True
            ),
            mock.patch.object(egpu_remove, "observe", side_effect=observations),
            mock.patch.object(egpu_remove, "report", lambda text="": None),
        ):
            return egpu_remove.main(argv), removal

    def test_the_default_run_writes_nothing(self) -> None:
        status, removal = self.run_main([], [(ready(), BINDING)])
        self.assertEqual(status, 0)
        self.assertEqual(removal.removed, [])

    def test_a_blocked_observation_reports_failure_and_writes_nothing(self) -> None:
        status, removal = self.run_main([], [(blocked(), BINDING)])
        self.assertEqual(status, 1)
        self.assertEqual(removal.removed, [])

    def test_remove_and_rescan_together_are_refused(self) -> None:
        status, removal = self.run_main(["--remove", "--rescan"], [])
        self.assertEqual(status, 2)
        self.assertEqual(removal.removed, [])
        self.assertEqual(removal.rescanned, [])

    def test_writing_without_root_is_refused_before_observing(self) -> None:
        status, removal = self.run_main(["--remove"], [], root=False)
        self.assertEqual(status, 2)
        self.assertEqual(removal.removed, [])

    def test_remove_detaches_both_functions_in_order(self) -> None:
        status, removal = self.run_main(
            ["--remove"], [(ready("sample-1"), BINDING), (ready("sample-2"), BINDING)]
        )
        self.assertEqual(status, 0)
        # A fresh observation carries a new sample, which must not by itself
        # invalidate the plan; only the device identity has to hold.
        self.assertEqual(removal.removed, [AUDIO_BDF, GPU_BDF])

    def test_a_changed_generation_refuses_the_removal(self) -> None:
        """The binding can stay identical while the observed set changes.

        The attachment binding identifies which eGPU is attached and the
        addresses are derived from the argument, so both are unchanged by
        construction across a recompose. The generation is the value that
        actually moves when the observation changes underneath.
        """
        status, removal = self.run_main(
            ["--remove"],
            [
                (ready("sample-1", "generation-1"), BINDING),
                (ready("sample-2", "generation-2"), BINDING),
            ],
        )
        self.assertEqual(status, 1)
        self.assertEqual(removal.removed, [])

    def test_a_changed_attachment_refuses_the_removal(self) -> None:
        status, removal = self.run_main(
            ["--remove"], [(ready(), BINDING), (ready("sample-2"), "a-different-egpu")]
        )
        self.assertEqual(status, 1)
        self.assertEqual(removal.removed, [])

    def test_readiness_lost_on_revalidation_refuses_the_removal(self) -> None:
        status, removal = self.run_main(
            ["--remove"], [(ready(), BINDING), (blocked(), BINDING)]
        )
        self.assertEqual(status, 1)
        self.assertEqual(removal.removed, [])

    def test_rescan_restores_both_functions_without_observing(self) -> None:
        status, removal = self.run_main(["--rescan"], [])
        self.assertEqual(status, 0)
        self.assertEqual(removal.rescanned, [(AUDIO_BDF, GPU_BDF)])
        self.assertEqual(removal.removed, [])


class BoundaryTests(unittest.TestCase):
    """This is the tool that detaches hardware, so the boundary is load bearing.

    `check_architecture.py` constrains the adapter; nothing stops a later edit
    to this module from opening a sysfs path directly, which is exactly the
    thing the single-writer boundary exists to prevent. The equivalent
    assertions guard `hdm.egpu_release`, which does strictly less than this.
    """

    TOOL = ROOT / "backend/hdm/egpu_remove.py"

    def test_the_tool_never_spawns_a_process(self) -> None:
        source = self.TOOL.read_text(encoding="utf-8")
        for line in source.splitlines():
            stripped = line.strip()
            self.assertFalse(
                stripped.startswith(("import subprocess", "from subprocess")),
                "the tool must not import subprocess",
            )
        self.assertNotIn("os.system", source)
        self.assertNotIn("Popen", source)

    def test_every_write_goes_through_the_port(self) -> None:
        source = self.TOOL.read_text(encoding="utf-8")
        self.assertNotIn("write_text", source)
        self.assertNotIn("/sys/bus/pci", source)

    def test_the_tool_states_that_this_is_not_clearance_to_unplug(self) -> None:
        source = self.TOOL.read_text(encoding="utf-8")
        self.assertIn("NOT clearance to unplug", source)


if __name__ == "__main__":
    unittest.main()
