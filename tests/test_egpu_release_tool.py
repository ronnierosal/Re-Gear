from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from hdm.egpu_release import (  # noqa: E402
    scan_holders,
    egpu_functions,
    HolderScan,
    main,
    restart_commands,
)


TOOL = ROOT / "backend/hdm/egpu_release.py"


class FunctionDerivationTests(unittest.TestCase):
    """Audio is derived from the GPU address so the two cannot disagree."""

    def test_audio_is_the_next_function(self) -> None:
        self.assertEqual(
            egpu_functions("0000:08:00.0"), ("0000:08:00.0", "0000:08:00.1")
        )

    def test_a_non_zero_gpu_function_still_derives(self) -> None:
        self.assertEqual(
            egpu_functions("0000:64:00.5"), ("0000:64:00.5", "0000:64:00.6")
        )


class RestartCommandTests(unittest.TestCase):
    def test_commands_are_produced_in_plan_order(self) -> None:
        commands = restart_commands(
            ("wireplumber.service", "gamescope-session.target"), 1000
        )
        self.assertEqual(len(commands), 2)
        self.assertIn("wireplumber.service", commands[0])
        self.assertIn("gamescope-session.target", commands[1])

    def test_commands_target_the_given_session_user(self) -> None:
        self.assertIn("/run/user/1042", restart_commands(("a.service",), 1042)[0])

    def test_no_units_produces_no_commands(self) -> None:
        self.assertEqual(restart_commands((), 1000), ())


class HolderScanTests(unittest.TestCase):
    """A scan that could not finish looking is not evidence of absence.

    Every case below returned an empty tuple before, and an empty tuple was
    read as `clients_clear`. The device could be held throughout.
    """

    NODE = "/dev/dri/renderD129"

    @contextlib.contextmanager
    def _proc(self, processes, links=None):
        """Build a fake /proc and resolve descriptors through `links`.

        Descriptors are resolved by patching `os.readlink` rather than by
        creating symlinks, which need privileges on some platforms.
        """
        import hdm.egpu_release as module
        from unittest.mock import patch

        links = links or {}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for pid, spec in processes.items():
                entry = root / pid
                entry.mkdir()
                if spec.get("fd_is_file"):
                    (entry / "fd").write_text("", encoding="utf-8")
                else:
                    (entry / "fd").mkdir()
                    for name in spec.get("fds", ()):
                        (entry / "fd" / name).write_text("", encoding="utf-8")
                if "cgroup" in spec:
                    (entry / "cgroup").write_text(spec["cgroup"], encoding="utf-8")

            def readlink(path):
                key = Path(path).name
                pid = Path(path).parent.parent.name
                target = links.get((pid, key))
                if target is None:
                    raise OSError(13, "permission denied")
                return target

            with patch.object(module.os, "readlink", readlink):
                yield root

    def test_a_proc_tree_without_holders_is_clear(self) -> None:
        with self._proc({"1": {"cgroup": "0::/init.scope"}}) as root:
            scan = scan_holders((self.NODE,), proc_root=root)
        self.assertEqual(scan.units, ())
        self.assertTrue(scan.complete)
        self.assertTrue(scan.clear)

    def test_non_numeric_entries_are_skipped(self) -> None:
        with self._proc({}) as root:
            (root / "self").mkdir()
            scan = scan_holders(("/dev/dri/card1",), proc_root=root)
        self.assertTrue(scan.clear)

    def test_a_process_whose_descriptors_cannot_be_listed_blocks_clear(self) -> None:
        with self._proc({"1": {"fd_is_file": True}}) as root:
            scan = scan_holders((self.NODE,), proc_root=root)
        self.assertEqual(scan.units, ())
        self.assertEqual(scan.unreadable_processes, 1)
        self.assertFalse(scan.complete)
        self.assertFalse(scan.clear)

    def test_a_descriptor_that_cannot_be_resolved_blocks_clear(self) -> None:
        # The unresolvable descriptor may be the eGPU node itself.
        with self._proc({"1": {"fds": ["3"], "cgroup": "0::/x.service"}}) as root:
            scan = scan_holders((self.NODE,), proc_root=root)
        self.assertEqual(scan.unreadable_descriptors, 1)
        self.assertFalse(scan.clear)

    def test_a_holder_without_a_readable_cgroup_blocks_clear(self) -> None:
        processes = {"1": {"fds": ["3"]}}
        links = {("1", "3"): self.NODE}
        with self._proc(processes, links) as root:
            scan = scan_holders((self.NODE,), proc_root=root)
        self.assertEqual(scan.units, ())
        self.assertEqual(scan.unattributed_holders, 1)
        self.assertFalse(scan.clear)

    def test_a_scope_holder_is_reported_rather_than_dropped(self) -> None:
        """The defect: a .scope holder was found, attributed, then discarded."""
        processes = {"1": {"fds": ["3"], "cgroup": "0::/app.slice/app-steam.scope"}}
        links = {("1", "3"): self.NODE}
        with self._proc(processes, links) as root:
            scan = scan_holders((self.NODE,), proc_root=root)
        self.assertEqual(scan.units, ("app-steam.scope",))
        self.assertTrue(scan.complete)
        self.assertFalse(scan.clear)

    def test_a_service_holder_is_still_reported(self) -> None:
        processes = {"1": {"fds": ["3"], "cgroup": "0::/wireplumber.service"}}
        links = {("1", "3"): self.NODE}
        with self._proc(processes, links) as root:
            scan = scan_holders((self.NODE,), proc_root=root)
        self.assertEqual(scan.units, ("wireplumber.service",))

    def test_an_incomplete_node_set_blocks_clear(self) -> None:
        # Fewer nodes were searched than the device exposes, so a holder of the
        # missing node is invisible to this scan.
        with self._proc({"1": {"cgroup": "0::/init.scope"}}) as root:
            scan = scan_holders((self.NODE,), proc_root=root, nodes_incomplete=True)
        self.assertEqual(scan.units, ())
        self.assertFalse(scan.complete)
        self.assertFalse(scan.clear)

    def test_a_vanished_process_is_not_counted_as_missed(self) -> None:
        # Exiting between listing and reading loses nothing: a process that no
        # longer exists holds nothing.
        with self._proc({"1": {"cgroup": "0::/init.scope"}}) as root:
            (root / "2").mkdir()
            scan = scan_holders((self.NODE,), proc_root=root)
        self.assertTrue(scan.clear)

    def test_the_reasons_name_every_gap(self) -> None:
        scan = HolderScan(("a.scope",), 1, 2, 3, True)
        reasons = " | ".join(scan.why_not_clear())
        for fragment in ("a.scope", "process", "descriptor", "attributable", "node set"):
            self.assertIn(fragment, reasons)


class BoundaryTests(unittest.TestCase):
    """The tool must not open a second process-spawning path."""

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

    def test_the_tool_never_removes_a_device(self) -> None:
        """Clearing holders is not removal authority."""
        source = TOOL.read_text(encoding="utf-8")
        self.assertNotIn("device_removal", source)
        self.assertNotIn("/remove", source)
        self.assertNotIn("rescan", source)

    def test_the_tool_states_that_recovery_is_not_durable(self) -> None:
        source = TOOL.read_text(encoding="utf-8")
        self.assertIn("not durable recovery", source)


class DryRunTests(unittest.TestCase):
    """Without --arm nothing is loaded or attached, on any hardware."""

    def _run(self, argv: list[str]) -> tuple[int, str]:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = main(argv)
        return code, buffer.getvalue()

    def test_absent_hardware_reports_incomplete_discovery(self) -> None:
        code, output = self._run(["--gpu", "0000:ff:00.0"])
        self.assertEqual(code, 1)
        self.assertIn("discovery incomplete", output)

    def test_arming_without_root_is_refused(self) -> None:
        import os
        from unittest.mock import patch

        # geteuid is POSIX-only; create it so this runs on any platform.
        with patch.object(os, "geteuid", return_value=1000, create=True):
            code, output = self._run(["--arm"])
        self.assertEqual(code, 2)
        self.assertIn("needs root", output)

    def test_default_is_a_plan_not_an_action(self) -> None:
        source = TOOL.read_text(encoding="utf-8")
        self.assertIn('"--arm"', source)
        self.assertIn("action=\"store_true\"", source)


if __name__ == "__main__":
    unittest.main()


class ArmPathTests(unittest.TestCase):
    """Exercise the --arm path end to end with fakes.

    Shipped in 0.3.57 with a NameError at the restart step: a string
    replacement had silently failed to match, deleting the function while
    leaving its call site. Nothing executed that path, so syntax checks,
    the boundary tests and CI all passed and the defect reached a release.
    """

    def _arm(self, *, holders_after=(), enforced=True, extra_argv=()):
        import os
        from pathlib import Path as _Path
        from unittest.mock import patch

        import hdm.egpu_release as module
        from hdm.domain.egpu_device_policy import EgpuDeviceNode
        from hdm.domain.models import EgpuResourceKind as Kind

        nodes = (
            EgpuDeviceNode(Kind.DRM_CARD, 226, 1),
            EgpuDeviceNode(Kind.DRM_RENDER, 226, 129),
            EgpuDeviceNode(Kind.AUDIO_CONTROL, 116, 15),
            EgpuDeviceNode(Kind.AUDIO_HARDWARE, 116, 14),
            EgpuDeviceNode(Kind.AUDIO_PCM, 116, 10),
        )
        scan = module.SteamOsEgpuDeviceNodeDiscovery
        holders = [
            ("gamescope-session.service", "steam-launcher.service",
             "wireplumber.service"),
            tuple(holders_after),
        ]

        class FakeScan:
            complete = True
            error = ""
            nodes = None

        class FakeDiscovery:
            def scan(self, **_):
                result = FakeScan()
                result.nodes = nodes
                return result

        class FakeLink:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def load(self, program):
                return 3

            def program_id(self):
                return 496

            def attach(self, fd):
                return 4

            def query_program_ids(self, fd):
                return (496,) if enforced else ()

        def observe(_nodes, **__):
            units = holders.pop(0) if len(holders) > 1 else holders[0]
            return HolderScan(tuple(units))

        buffer = io.StringIO()
        with patch.object(module, "SteamOsEgpuDeviceNodeDiscovery", FakeDiscovery), \
             patch.object(module, "CgroupDeviceLink", FakeLink), \
             patch.object(module, "scan_holders", observe), \
             patch.object(
                 module, "node_paths", lambda *a: (("/dev/dri/card1",), True)
             ), \
             patch.object(os, "geteuid", return_value=0, create=True), \
             patch.object(os, "O_DIRECTORY", 0, create=True), \
             patch.object(os, "O_CLOEXEC", 0, create=True), \
             patch.object(os, "open", return_value=99), \
             patch.object(os, "close", lambda fd: None), \
             patch.object(_Path, "is_dir", lambda self: True), \
             contextlib.redirect_stdout(buffer):
            code = module.main(["--arm", "--hold", "0", *extra_argv])
        return code, buffer.getvalue()

    def test_the_arm_path_runs_without_a_missing_name(self) -> None:
        """The regression: this raised NameError: restart_unit."""
        code, output = self._arm(holders_after=())
        self.assertIn("enforcement verified", output)
        self.assertEqual(code, 0, output)

    def test_arming_prints_the_restart_commands_rather_than_running_them(self) -> None:
        _, output = self._arm(holders_after=())
        self.assertIn("systemctl --user restart wireplumber.service", output)
        self.assertIn("systemctl --user restart gamescope-session.target", output)

    def test_a_cleared_device_reports_success_without_removal(self) -> None:
        code, output = self._arm(holders_after=())
        self.assertIn("clients_clear: every holder released", output)
        self.assertIn("NOT removal clearance", output)
        self.assertEqual(code, 0)

    def test_remaining_holders_fail_and_are_named(self) -> None:
        code, output = self._arm(holders_after=("wireplumber.service",))
        self.assertIn("holders remain", output)
        self.assertEqual(code, 1)

    def test_unverified_enforcement_stops_before_restart_instructions(self) -> None:
        code, output = self._arm(enforced=False)
        self.assertIn("enforcement unverified", output)
        # The restore commands in the detach block still appear; what must not
        # appear is the step-6 instruction to apply the plan.
        self.assertNotIn("run these, as the session user", output)
        self.assertNotIn("clients_clear", output)
        self.assertEqual(code, 1)

    def test_the_filter_is_always_reported_detached(self) -> None:
        for kwargs in ({"holders_after": ()}, {"holders_after": ("a.service",)},
                       {"enforced": False}):
            _, output = self._arm(**kwargs)
            self.assertIn("detached", output)


class HoldOpenTests(unittest.TestCase):
    """The window a supervised removal has to act inside.

    `clients_clear` is a property of the filter being attached, not a state the
    device settles into. Before `--hold-open`, the tool reported every holder
    released and detached in the same breath, so the condition it reported had
    already stopped being true and nothing could act on it.
    """

    def _hold(self, observations, seconds=9, interval=3.0):
        import hdm.egpu_release as module
        from unittest.mock import patch

        seen = list(observations)
        calls = []
        clock = {"now": 0.0}

        def scan(*_args, **_kwargs):
            calls.append(clock["now"])
            units = seen.pop(0) if seen else ()
            return HolderScan(tuple(units))

        def sleep(duration):
            # Always advance, so a zero-length sleep cannot spin forever.
            clock["now"] += max(duration, 1.0)

        with patch.object(module, "scan_holders", scan), \
             patch.object(module.time, "monotonic", lambda: clock["now"]), \
             patch.object(module.time, "sleep", sleep):
            return module.hold_open(("/dev/dri/card1",), seconds, interval), calls

    def test_a_device_that_stays_clear_reports_no_holders(self) -> None:
        returned, calls = self._hold([(), (), ()])
        self.assertIsNone(returned)
        self.assertEqual(len(calls), 3)

    def test_a_holder_that_returns_is_reported(self) -> None:
        returned, _ = self._hold([(), ("wireplumber.service",), ()])
        self.assertEqual(returned.units, ("wireplumber.service",))

    def test_a_returning_holder_ends_the_window_at_once(self) -> None:
        # Waiting the window out would end by reporting a device that stopped
        # being clear partway through, which is the case this exists to catch.
        _, calls = self._hold([("wireplumber.service",), (), ()])
        self.assertEqual(len(calls), 1)

    def test_a_zero_length_window_checks_nothing(self) -> None:
        returned, calls = self._hold([("wireplumber.service",)], seconds=0)
        self.assertIsNone(returned)
        self.assertEqual(calls, [])

    def test_a_scan_that_stops_being_complete_ends_the_window(self) -> None:
        """Losing the ability to check ends the window, as a holder does.

        An operator inside this window is about to remove the device. A
        scan that can no longer see everywhere is not a clear device.
        """
        import hdm.egpu_release as module
        from unittest.mock import patch

        clock = {"now": 0.0}
        seen = [HolderScan(()), HolderScan((), unreadable_processes=1)]

        def scan(*_args, **_kwargs):
            return seen.pop(0) if seen else HolderScan(())

        def sleep(duration):
            clock["now"] += max(duration, 1.0)

        with patch.object(module, "scan_holders", scan), \
             patch.object(module.time, "monotonic", lambda: clock["now"]), \
             patch.object(module.time, "sleep", sleep):
            ended = module.hold_open(("/dev/dri/card1",), 9, 3.0)
        self.assertIsNotNone(ended)
        self.assertEqual(ended.unreadable_processes, 1)


class HoldOpenArmPathTests(ArmPathTests):
    """`--hold-open` as the arm path actually reaches it."""

    def _arm_holding(self, *, window_result=None, seconds=180):
        import hdm.egpu_release as module
        from unittest.mock import patch

        recorded = {}

        def fake_hold_open(nodes, hold_seconds, *args, **kwargs):
            recorded["seconds"] = hold_seconds
            return window_result

        with patch.object(module, "hold_open", fake_hold_open):
            code, output = self._arm(
                holders_after=(), extra_argv=["--hold-open", str(seconds)]
            )
        return code, output, recorded

    def test_the_default_still_detaches_immediately(self) -> None:
        # No --hold-open: behaviour is exactly as before, no window at all.
        _, output = self._arm(holders_after=())
        self.assertNotIn("hold the filter open", output)

    def test_holding_open_names_the_removal_command(self) -> None:
        code, output, recorded = self._arm_holding()
        self.assertIn("hold the filter open", output)
        self.assertIn("hdm.egpu_remove", output)
        self.assertEqual(recorded["seconds"], 180)
        self.assertEqual(code, 0)

    def test_a_holder_reopening_the_device_fails_the_run(self) -> None:
        code, output, _ = self._arm_holding(
            window_result=HolderScan(("wireplumber.service",))
        )
        self.assertIn("the window ended early", output)
        self.assertIn("wireplumber.service", output)
        self.assertIn("do not remove", output)
        self.assertEqual(code, 1)

    def test_a_window_that_stays_clear_succeeds(self) -> None:
        code, output, _ = self._arm_holding()
        self.assertIn("the window closed with the device still clear", output)
        self.assertIn("NOT removal clearance", output)
        self.assertEqual(code, 0)
