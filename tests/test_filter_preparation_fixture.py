import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock
from scripts import probe_filter_preparation_fixture as fixture


class PreparationFixtureTests(unittest.TestCase):
    def test_partial_preparation_never_calls_recovery(self):
        binding = SimpleNamespace(operation='fixture', unit='gamescope-session.service')
        record = SimpleNamespace(lifecycle=SimpleNamespace(binding=binding,
            phase=fixture.Phase.REQUESTED))
        journal = Mock()
        @contextmanager
        def transaction():
            yield SimpleNamespace(read=lambda *args: record)
        journal.transaction = transaction
        recovery = Mock()
        with self.assertRaises(ValueError):
            fixture.recover_preparation(lambda: journal, binding, current_boot_hash='a'*64,
                observe_denial=lambda: True, observe_restored=lambda: True,
                recovery_factory=recovery)
        recovery.assert_not_called()

    def test_incomplete_direct_cleanup_cannot_pass(self):
        binding = SimpleNamespace(operation='fixture', unit='gamescope-session.service')
        pair = SimpleNamespace(stage=fixture.PairedStage.RECEIVE_CONFIRMED,
                               receive=object(), map_id=1)
        record = SimpleNamespace(lifecycle=SimpleNamespace(binding=binding,
            phase=fixture.Phase.ATTACHED, owned=object()), paired=pair,
            delivery_granted=False, revision=1)
        journal = Mock()
        @contextmanager
        def transaction():
            yield SimpleNamespace(read=lambda *args: record)
        journal.transaction = transaction
        recovery = Mock()
        recovery.return_value.recover.return_value = SimpleNamespace(outcome='pin_missing_unverified')
        restored = Mock(return_value=True)
        with self.assertRaises(ValueError):
            fixture.recover_preparation(lambda: journal, binding, current_boot_hash='a'*64,
                observe_denial=lambda: True, observe_restored=restored,
                recovery_factory=recovery)
        restored.assert_not_called()


if __name__ == '__main__':
    unittest.main()
