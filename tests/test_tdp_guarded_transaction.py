import subprocess
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import test_tdp_provider as provider_fixtures
from test_tdp_control import MemoryJournal
from hdm.adapters.steamos.commands import SteamOsTdpCommandRunner
from hdm.application.auto_tdp_dispatch import AutoTdpDispatchContext, AutoTdpDispatchGuard
from hdm.application.tdp_control import TdpControlService
from hdm.ports.tdp import TdpSessionRecord


class GuardedTransactionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = provider_fixtures.TdpProviderTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.attribute("ppt_pl2_sppt", (17, 15, 43))
        self.fixture.attribute("ppt_pl3_fppt", (17, 15, 53))
        self.expected = self.fixture.provider.observe().reading
        self.fixture.provider._commands = SteamOsTdpCommandRunner(effective_uid=lambda: 0)
        self.journal = MemoryJournal()
        self.service = TdpControlService(self.fixture.provider, self.journal, wait=lambda _: None)
        self.context = AutoTdpDispatchContext("enable-generation", "game-generation", self.expected)
        self.live = self.context
        self.now = 0
        self.reads = 0
        self.writes = []
        self.current = 17
        self.on_second_read = lambda: None
        self.fail_write = False
        self.guard = AutoTdpDispatchGuard(self.context, 0, 2000, lambda: self.live, lambda: self.now)

    def execute(self, argv, **kwargs):
        if "set-property" in argv:
            self.writes.append(int(argv[-1]))
            if self.fail_write:
                raise subprocess.TimeoutExpired(argv, 8)
            self.current = self.writes[-1]
            for name, bounds in (("ppt_pl1_spl", (7, 30)), ("ppt_pl2_sppt", (15, 43)), ("ppt_pl3_fppt", (15, 53))):
                self.fixture.attribute(name, (max(self.current, bounds[0]), *bounds))
            output = b""
        elif "get-property" in argv:
            self.reads += 1
            if self.reads == 2:
                self.on_second_read()
            output = f"u {self.current}\nu 7\nu 30\n".encode()
        else:
            output = b's ":1.42"\n'
        return SimpleNamespace(stdout=output, stderr=b"", returncode=0)

    def apply(self):
        with patch("hdm.adapters.steamos.commands.subprocess.run", side_effect=self.execute):
            return self.service.apply(20, dispatch_guard=self.guard)

    def test_sample_expiring_during_provider_readback_never_dispatches_or_leaves_pending(self):
        self.on_second_read = lambda: setattr(self, "now", 2001)
        result = self.apply()
        self.assertEqual(result.code, "tdp.dispatch_rejected")
        self.assertEqual(result.state, "blocked")
        self.assertEqual(self.writes, [])
        self.assertIsNone(self.journal.record)
        self.assertEqual(self.journal.saved[0].phase, "pending")
        self.assertIsNone(self.journal.saved[-1])

    def test_game_change_during_readback_preserves_existing_recovery_baseline(self):
        baseline = replace(self.expected, sustained=replace(self.expected.sustained, current=15), slow=replace(self.expected.slow, current=15), fast=replace(self.expected.fast, current=15))
        prior = TdpSessionRecord(baseline, self.expected)
        self.journal.record = prior
        self.on_second_read = lambda: setattr(self, "live", replace(self.context, workload_key="new-game"))
        self.assertEqual(self.apply().code, "tdp.dispatch_rejected")
        self.assertEqual(self.writes, [])
        self.assertEqual(self.journal.record, prior)

    def test_throwing_guard_is_categorical_and_not_an_uncertain_write(self):
        def fail():
            raise OSError("private process evidence")
        self.guard = fail
        self.assertEqual(self.apply().code, "tdp.dispatch_rejected")
        self.assertEqual(self.writes, [])
        self.assertIsNone(self.journal.record)

    def test_valid_guard_uses_existing_verification_path(self):
        result = self.apply()
        self.assertEqual(result.state, "applied")
        self.assertEqual(self.writes, [20])
        self.assertEqual(self.journal.record.phase, "active")
        self.assertEqual(self.journal.record.applied.values, (20, 20, 20))

    def test_timeout_after_dispatch_keeps_uncertain_journal(self):
        self.fail_write = True
        result = self.apply()
        self.assertEqual(result.state, "recovery_required")
        self.assertEqual(self.writes, [20])
        self.assertEqual(self.journal.record.phase, "pending")
