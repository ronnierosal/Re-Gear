"""Linux-root recovery composition against production fixed-path filesystem IO.

Only a forked child enters a private chroot. The parent retains its normal root
and removes only its verified temporary directory. No admission/store/factory is patched,
and no fixture owner_uid or trusted_directory_fd bypass is used. Device/session
observations and commands are fake; these tests never operate an eGPU.
"""
import asyncio
import concurrent.futures.thread  # Preload lazy executor imports before chroot.
from contextlib import ExitStack, contextmanager
import os
from pathlib import Path
import select
import shutil
import signal
import subprocess
import sys
from tempfile import mkdtemp
import threading
import time
import traceback
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

from tests.test_main_process_delivery import load_main_module
from tests.test_main_link_recovery import observation, status
from tests.test_link_recovery_service import FakeCommands, USER, RESTART, service
from regear.delivery.dock_mutation_gate import DockMutationDenied, LOCK_FILENAME
from regear.delivery.runtime_state import RootOwnedRuntimeState
from regear.delivery.whole_dock_claim import WholeDockClaimStore, FILENAME
from regear.domain.models import Confidence, GameState, GpuRole


ROOT_AVAILABLE = (sys.platform == "linux" and hasattr(os, "fork")
                  and hasattr(os, "chroot") and os.geteuid() == 0)


@unittest.skipUnless(ROOT_AVAILABLE, "Linux root and chroot required")
class AutomaticRecoveryPrivilegedTests(unittest.TestCase):
    @contextmanager
    def private_root(self):
        root = Path(mkdtemp(prefix="regear-root-recovery-"))
        expected = root.resolve(strict=True)
        try:
            yield root
        finally:
            # No TemporaryDirectory finalizer: an unexpected path is retained
            # for inspection, rather than recursively cleaned after assertion.
            self.assertFalse(root.is_symlink(), "changed fixture path retained")
            self.assertEqual(root.resolve(strict=True), expected,
                             "changed fixture path retained")
            self.assertTrue(expected.is_absolute() and expected.name.startswith("regear-root-recovery-"))
            shutil.rmtree(expected)

    def isolated(self, scenario):
        import fcntl  # Native module must be loaded outside the empty chroot.
        self.assertEqual(threading.active_count(), 1, "fork fixture requires a single-threaded parent")
        module = load_main_module(real_dock_gate=True)
        with self.private_root() as root:
            resolved_root = root.resolve(strict=True)
            (root / "var" / "lib").mkdir(parents=True, mode=0o755)
            root.chmod(0o700)
            (root / "var").chmod(0o755)
            (root / "var" / "lib").chmod(0o755)
            read_fd, write_fd = os.pipe()
            pid = os.fork()
            if pid == 0:
                os.close(read_fd)
                try:
                    # Path isolation is not a root security sandbox. Drop inherited
                    # host handles before chroot; retain only stdio and result IPC.
                    for entry in os.listdir("/proc/self/fd"):
                        descriptor = int(entry)
                        if descriptor > 2 and descriptor != write_fd:
                            try:
                                os.close(descriptor)
                            except OSError:
                                pass  # /proc listing's own transient descriptor.
                    os.chroot(root)
                    os.chdir("/")
                    self.exercise(module, scenario, fcntl)
                    payload = b"OK"
                    exit_code = 0
                except BaseException:
                    payload = traceback.format_exc().encode("utf-8", "replace")[-3500:]
                    exit_code = 1
                try:
                    os.write(write_fd, payload)
                finally:
                    os.close(write_fd)
                    os._exit(exit_code)
            os.close(write_fd)
            reaped = False
            try:
                readable, _, _ = select.select([read_fd], [], [], 20)
                self.assertTrue(readable, "root recovery child exceeded 20 seconds")
                payload = os.read(read_fd, 4096)
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    finished, child_status = os.waitpid(pid, os.WNOHANG)
                    if finished == pid:
                        reaped = True
                        break
                    time.sleep(0.01)
                self.assertTrue(reaped, "root recovery child did not exit")
                self.assertEqual(os.waitstatus_to_exitcode(child_status), 0,
                                 payload.decode("utf-8", "replace"))
                self.assertEqual(payload, b"OK")
            finally:
                os.close(read_fd)
                if not reaped:
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    os.waitpid(pid, 0)
                self.assertFalse(root.is_symlink())
                self.assertEqual(root.resolve(strict=True), resolved_root)

    def exercise(self, module, scenario, fcntl):
        current = NS(snapshot=NS(game_state=GameState.IDLE,
            gamescope=NS(running=True, confidence=Confidence.VERIFIED),
            gpus=(NS(role=GpuRole.INTERNAL, present=True, confidence=Confidence.VERIFIED),)))
        topology = NS(transport_identity="transport:known", transport_present=True,
                      pci_complete=False)
        clock = NS(now=0.0)
        transport = NS(binding="dock", generation="generation")
        with ExitStack() as stack:
            stack.enter_context(patch.object(subprocess, "Popen", side_effect=AssertionError(
                "subprocess is forbidden in the root recovery fixture")))
            stack.enter_context(patch.object(os, "system", side_effect=AssertionError(
                "shell execution is forbidden in the root recovery fixture")))
            # Only external observations are substituted. Real persisted consent,
            # root validation, locking, claim and power-intent readers remain.
            replacements = {
                "read_boot_hash": Mock(return_value="b" * 64),
                "resolve_transport": Mock(return_value=transport),
                "HeldTrialLauncher": Mock(return_value=NS(call=Mock(return_value={
                    "code": "held_helper.settled", "settled": True}))),
                "DrmDiscovery": Mock(return_value=NS(scan=lambda: [])),
                "GamescopeDiscovery": Mock(return_value=NS(scan=lambda: [])),
                "resolve_gamescope_user": Mock(return_value=NS(ok=True, context=USER)),
                "resolve_runtime_profiles": Mock(return_value=NS(exact_host=True)),
                "SnapshotTransitionObservationAdapter": Mock(return_value=NS(observe=lambda: current)),
            }
            for name, value in replacements.items():
                stack.enter_context(patch.object(module, name, value))
            stack.enter_context(patch.object(module.time, "monotonic", side_effect=lambda: clock.now))
            state_root = RootOwnedRuntimeState().ensure()
            self.assertEqual(state_root, Path("/var/lib/handheld-dock-mode"))
            self.assertEqual(state_root.stat().st_uid, 0)
            claims = WholeDockClaimStore(state_root)

            def make_plugin():
                plugin = module.Plugin.__new__(module.Plugin)
                plugin._unloading = False
                plugin._background_operations = set()
                plugin._automatic_dock_preference_store = None
                plugin._discovery = object()
                plugin._connection_topology = NS(observe=lambda: topology)
                plugin._append_journey_event = Mock()
                commands = FakeCommands()
                original_run = commands.run
                def run(*args, **kwargs):
                    self.assertEqual(args[0], RESTART)
                    # An independently opened real lock must contend while the
                    # production callback is issuing its fake restart command.
                    with self.assertRaises(DockMutationDenied):
                        with plugin._dock_mutation_gate().admit(allow_inhibited=True):
                            self.fail("restart escaped real admission")
                    return original_run(*args, **kwargs)
                commands.run = run
                plugin._link_recovery, _ = service(commands, [True])
                async def readiness(_):
                    return status()
                plugin._observe_connection_readiness = readiness
                journal = plugin._transition_journal_service().status()
                self.assertTrue(journal.durable)
                self.assertEqual(journal.owner.value, "none")
                self.assertTrue(module.inner_removal_records_absent())
                return plugin, commands

            def poll(plugin, now, *, absent=False):
                clock.now = now
                plugin._last_readiness_observation = observation(
                    transport_identity="" if absent else "transport:known",
                    transport_present=not absent, transport_absent_verified=absent)
                return asyncio.run(plugin._maybe_automatic_link_recovery(
                    current, plugin._automatic_dock_preferences().load()))

            def arm(plugin, commands):
                self.assertTrue(plugin._automatic_dock_preferences().load())
                self.assertTrue(plugin._automatic_recovery_preferences().load())
                self.assertFalse(poll(plugin, 0, absent=True))
                self.assertFalse(poll(plugin, 1))
                self.assertFalse(poll(plugin, 10.999))
                self.assertEqual(commands.calls, [])

            def refused(plugin, commands, code):
                for now in (11, 12, 13):
                    self.assertFalse(poll(plugin, now))
                self.assertEqual(commands.calls, [])
                self.assertEqual(plugin._automatic_link_recovery.attempts, 0)
                reply = asyncio.run(plugin._automatic_link_recovery_status())
                self.assertEqual(reply["decision_code"], code)
                self.assertIsNot(reply.get("safe_to_unplug"), True)
                codes = [call.kwargs["code"] for call in plugin._append_journey_event.call_args_list]
                self.assertNotIn("automatic_recovery.started", codes)
                self.assertEqual(codes.count(code), 1)

            plugin, commands = make_plugin()
            plugin._automatic_dock_preferences().save(True)
            plugin._automatic_recovery_preferences().save(True)
            for filename in ("automatic-dock.json", "automatic-link-recovery.json"):
                self.assertEqual((state_root / filename).stat().st_uid, 0)
            if scenario == "positive":
                arm(plugin, commands)
                self.assertTrue(poll(plugin, 11))
                self.assertEqual(commands.calls, [RESTART])
                self.assertEqual(plugin._automatic_link_recovery.attempts, 1)
                self.assertFalse(poll(plugin, 30))
                self.assertEqual(commands.calls, [RESTART])
                self.assertIsNone(claims.load())
            elif scenario == "busy":
                arm(plugin, commands)
                fd = os.open(state_root / LOCK_FILENAME, os.O_RDWR | os.O_CREAT, 0o600)
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    refused(plugin, commands, "automatic_recovery.admission_unavailable_or_busy")
                finally:
                    os.close(fd)
                self.assertTrue(poll(plugin, 14))
                self.assertEqual(commands.calls, [RESTART])
            elif scenario in ("software_down", "claimed", "release_intent"):
                with plugin._dock_mutation_gate().admit():
                    self.assertTrue(claims.claim("operation", "dock", "generation"))
                    if scenario != "claimed":
                        claims.record("operation", scenario)
                original_bytes = (state_root / FILENAME).read_bytes()
                if scenario == "software_down":
                    for _ in range(2):
                        plugin, commands = make_plugin()
                        arm(plugin, commands)
                        refused(plugin, commands, "automatic_recovery.admission_inhibited")
                        self.assertEqual((state_root / FILENAME).read_bytes(), original_bytes)
                        self.assertEqual(claims.load().stage, "software_down")
                else:
                    arm(plugin, commands)
                    self.assertTrue(poll(plugin, 11))
                    self.assertEqual(commands.calls, [RESTART])
                    self.assertEqual((state_root / FILENAME).read_bytes(), original_bytes)
                    self.assertEqual(claims.load().stage, scenario)
            elif scenario == "malformed":
                arm(plugin, commands)
                target = state_root / FILENAME
                target.write_bytes(b"not-json")
                target.chmod(0o600)
                refused(plugin, commands, "automatic_recovery.admission_unavailable_or_busy")
                self.assertEqual(target.read_bytes(), b"not-json")
            elif scenario == "unsafe":
                arm(plugin, commands)
                target = state_root / LOCK_FILENAME
                target.write_bytes(b"unsafe-lock")
                target.chmod(0o666)
                refused(plugin, commands, "automatic_recovery.admission_unavailable_or_busy")
                self.assertEqual(target.stat().st_mode & 0o777, 0o666)
                self.assertEqual(target.read_bytes(), b"unsafe-lock")
            elif scenario == "unsafe-root":
                arm(plugin, commands)
                state_root.chmod(0o777)
                for now in (11, 12, 13):
                    with self.assertRaisesRegex(ValueError, "mode 0700"):
                        poll(plugin, now)
                self.assertEqual(commands.calls, [])
                self.assertEqual(plugin._automatic_link_recovery.attempts, 0)
                reply = asyncio.run(plugin._automatic_link_recovery_status())
                self.assertEqual(reply["decision_code"], "automatic_recovery.observation_failed")
                self.assertIsNot(reply.get("safe_to_unplug"), True)
                codes = [call.kwargs["code"] for call in plugin._append_journey_event.call_args_list]
                self.assertEqual(codes.count("automatic_recovery.observation_failed"), 1)
                self.assertNotIn("automatic_recovery.started", codes)
                self.assertEqual(state_root.stat().st_mode & 0o777, 0o777)
            else:
                self.fail("unknown scenario")

    def test_real_factory_recovers_after_ten_seconds_with_persisted_consent(self):
        self.isolated("positive")

    def test_real_flock_contention_refuses_without_spending_attempt(self):
        self.isolated("busy")

    def test_persisted_software_down_is_retained_across_plugin_recreation(self):
        self.isolated("software_down")

    def test_real_early_claim_permits_only_settled_connection_recovery(self):
        for stage in ("claimed", "release_intent"):
            with self.subTest(stage=stage):
                self.isolated(stage)

    def test_malformed_claim_is_not_erased_or_recovered_around(self):
        self.isolated("malformed")

    def test_unsafe_admission_lock_is_not_repaired_or_bypassed(self):
        self.isolated("unsafe")

    def test_unsafe_runtime_root_reports_observation_failure_without_repair(self):
        self.isolated("unsafe-root")


if __name__ == "__main__":
    unittest.main()
