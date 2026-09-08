from __future__ import annotations

import contextlib
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import hdm.egpu_remove as module  # noqa: E402
from hdm.domain.device_removal import (  # noqa: E402
    RemovalPlanState,
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


TOOL = ROOT / "backend/hdm/egpu_remove.py"


def ready(binding: str = "bind", generation: str = "gen", sample: str = "s1"):
    return RemovalSafety(
        RemovalSafetyState.READY_FOR_SUPERVISED_REMOVAL,
        "removal_safety.ready_for_supervised_removal",
        SafeUndockRevalidation(binding, generation, sample),
    )


def composed_plan(readiness=None, gpu: str = "0000:08:00.0"):
    return compose_removal_plan(readiness or ready(), module.egpu_functions(gpu))


class FunctionDerivationTests(unittest.TestCase):
    """Audio is derived from the GPU address so the two cannot disagree."""

    def test_both_functions_are_derived(self) -> None:
        functions = module.egpu_functions("0000:08:00.0")
        self.assertEqual(
            tuple(function.address for function in functions),
            ("0000:08:00.0", "0000:08:00.1"),
        )

    def test_a_non_zero_gpu_function_still_derives(self) -> None:
        functions = module.egpu_functions("0000:64:00.5")
        self.assertEqual(functions[1].address, "0000:64:00.6")


class PlanCompositionTests(unittest.TestCase):
    def test_a_ready_verdict_composes_audio_first(self) -> None:
        plan = composed_plan()
        self.assertEqual(plan.state, RemovalPlanState.COMPOSED)
        self.assertEqual(plan.addresses, ("0000:08:00.1", "0000:08:00.0"))

    def test_an_unready_verdict_composes_nothing(self) -> None:
        plan = composed_plan(
            RemovalSafety(RemovalSafetyState.NOT_READY, "removal_safety.game_running")
        )
        self.assertIs(plan.usable, False)


class ConfirmationTests(unittest.TestCase):
    """The confirming read guards identity, not the per-observation sample."""

    def test_an_unchanged_device_confirms_despite_a_new_sample(self) -> None:
        plan = composed_plan(ready(sample="s1"))
        self.assertTrue(module.confirm_unchanged(plan, ready(sample="s2")))

    def test_a_changed_generation_refuses(self) -> None:
        plan = composed_plan(ready(generation="gen"))
        self.assertFalse(
            module.confirm_unchanged(plan, ready(generation="other", sample="s2"))
        )

    def test_a_changed_attachment_refuses(self) -> None:
        plan = composed_plan(ready(binding="bind"))
        self.assertFalse(module.confirm_unchanged(plan, ready(binding="other")))

    def test_a_confirming_read_that_is_no_longer_ready_refuses(self) -> None:
        plan = composed_plan()
        self.assertFalse(
            module.confirm_unchanged(
                plan,
                RemovalSafety(
                    RemovalSafetyState.NOT_READY,
                    "removal_safety.clients_active_or_protected",
                ),
            )
        )

    def test_an_unusable_plan_never_confirms(self) -> None:
        plan = composed_plan(
            RemovalSafety(RemovalSafetyState.NOT_READY, "removal_safety.game_running")
        )
        self.assertFalse(module.confirm_unchanged(plan, ready()))


class FakeRemoval:
    """Records what was asked of the port, and answers as scripted."""

    def __init__(self, outcomes=None, rescan=None) -> None:
        self.removed: list[str] = []
        self.rescanned: list[tuple[str, ...]] = []
        self._outcomes = dict(outcomes or {})
        self._rescan = rescan

    def remove(self, address: str) -> RemovalResult:
        self.removed.append(address)
        outcome = self._outcomes.get(address, RemovalOutcome.REMOVED)
        code = "" if outcome is RemovalOutcome.REMOVED else f"device_removal.{outcome}"
        return RemovalResult(address, outcome, code)

    def rescan(self, expected: tuple[str, ...]) -> RescanResult:
        self.rescanned.append(expected)
        return self._rescan or RescanResult(RescanOutcome.RESTORED, expected)


class ExecutionTests(unittest.TestCase):
    def test_functions_are_detached_in_plan_order(self) -> None:
        removal = FakeRemoval()
        with contextlib.redirect_stdout(io.StringIO()):
            code = module.execute(composed_plan(), removal)
        self.assertEqual(code, 0)
        self.assertEqual(removal.removed, ["0000:08:00.1", "0000:08:00.0"])

    def test_a_function_that_stays_present_stops_the_removal(self) -> None:
        removal = FakeRemoval({"0000:08:00.1": RemovalOutcome.STILL_PRESENT})
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = module.execute(composed_plan(), removal)
        self.assertEqual(code, 1)
        # The GPU function is never touched once audio did not detach.
        self.assertEqual(removal.removed, ["0000:08:00.1"])
        self.assertIn("part-detached", buffer.getvalue())


class RestoreTests(unittest.TestCase):
    def test_a_full_restore_reports_success(self) -> None:
        removal = FakeRemoval()
        with contextlib.redirect_stdout(io.StringIO()):
            code = module.restore(("0000:08:00.1", "0000:08:00.0"), removal)
        self.assertEqual(code, 0)
        self.assertEqual(removal.rescanned, [("0000:08:00.1", "0000:08:00.0")])

    def test_an_incomplete_restore_is_a_report_not_a_verdict(self) -> None:
        removal = FakeRemoval(
            rescan=RescanResult(
                RescanOutcome.INCOMPLETE,
                ("0000:08:00.0",),
                "device_removal.rescan_incomplete",
            )
        )
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = module.restore(("0000:08:00.1", "0000:08:00.0"), removal)
        self.assertEqual(code, 1)
        self.assertIn("re-run --restore", buffer.getvalue())


class BoundaryTests(unittest.TestCase):
    def test_the_tool_never_spawns_a_process(self) -> None:
        source = TOOL.read_text(encoding="utf-8")
        for line in source.splitlines():
            stripped = line.strip()
            self.assertFalse(
                stripped.startswith(("import subprocess", "from subprocess")),
                "the tool must not import subprocess",
            )
        self.assertNotIn("os.system", source)
        self.assertNotIn("Popen", source)

    def test_the_tool_writes_only_through_the_port(self) -> None:
        """Every write goes through the one adapter architecture permits."""
        source = TOOL.read_text(encoding="utf-8")
        self.assertNotIn("write_text", source)
        self.assertNotIn("/sys/bus/pci", source)

    def test_the_tool_states_that_this_is_not_clearance_to_unplug(self) -> None:
        source = TOOL.read_text(encoding="utf-8")
        self.assertIn("invariant 10", source)


class MainTests(unittest.TestCase):
    def _run(self, argv, *, euid=0, observations=None, removal=None):
        observations = list(observations or [ready(), ready(sample="s2")])
        removal = removal or FakeRemoval()
        buffer = io.StringIO()
        with patch.object(module.os, "geteuid", return_value=euid, create=True), \
             patch.object(module, "snapshot_service", lambda: object()), \
             patch.object(module, "observe", lambda _service: observations.pop(0)), \
             patch.object(module, "SysfsDeviceRemoval", lambda: removal), \
             contextlib.redirect_stdout(buffer):
            code = module.main(argv)
        return code, buffer.getvalue(), removal

    def test_the_default_is_a_plan_and_writes_nothing(self) -> None:
        code, output, removal = self._run([])
        self.assertEqual(code, 0)
        self.assertIn("nothing was written", output)
        self.assertEqual(removal.removed, [])

    def test_an_unready_observation_composes_no_plan(self) -> None:
        code, output, removal = self._run(
            [],
            observations=[
                RemovalSafety(
                    RemovalSafetyState.NOT_READY, "removal_safety.game_running"
                )
            ],
        )
        self.assertEqual(code, 1)
        self.assertIn("removal_safety.game_running", output)
        self.assertEqual(removal.removed, [])

    def test_removing_without_root_is_refused(self) -> None:
        code, output, removal = self._run(["--remove"], euid=1000)
        self.assertEqual(code, 2)
        self.assertIn("needs root", output)
        self.assertEqual(removal.removed, [])

    def test_remove_and_restore_together_are_refused(self) -> None:
        code, output, _ = self._run(["--remove", "--restore"])
        self.assertEqual(code, 2)
        self.assertIn("pick one", output)

    def test_the_remove_path_detaches_both_functions(self) -> None:
        code, output, removal = self._run(["--remove"])
        self.assertEqual(code, 0)
        self.assertEqual(removal.removed, ["0000:08:00.1", "0000:08:00.0"])
        self.assertIn("invariant 10", output)

    def test_a_device_that_changed_between_reads_is_refused(self) -> None:
        code, output, removal = self._run(
            ["--remove"],
            observations=[ready(generation="gen"), ready(generation="other")],
        )
        self.assertEqual(code, 1)
        self.assertIn("refusing to remove", output)
        self.assertEqual(removal.removed, [])

    def test_restore_rescans_without_observing(self) -> None:
        code, _, removal = self._run(["--restore"], observations=[])
        self.assertEqual(code, 0)
        self.assertEqual(removal.rescanned, [("0000:08:00.0", "0000:08:00.1")])


if __name__ == "__main__":
    unittest.main()
