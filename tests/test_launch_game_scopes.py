import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch
from backend.hdm.adapters.steamos.game_scopes import LaunchGameScopeDiscovery
from backend.hdm.domain.models import GameState


class LaunchScopeInputTests(unittest.TestCase):
    def test_invalid_uid_deadline_never_opens(self):
        scanner=LaunchGameScopeDiscovery(clock=lambda:0)
        with patch('os.open') as opened:
            for uid,deadline in ((None,1),(True,1),(-1,1),(1,float('nan')),(1,True)):
                self.assertIs(scanner.scan(uid,deadline=deadline).state,GameState.UNKNOWN)
            opened.assert_not_called()

    def test_expired_or_decreasing_clock_never_reports_idle(self):
        scanner=LaunchGameScopeDiscovery(clock=lambda:5)
        self.assertIs(scanner.scan(0,deadline=5).state,GameState.UNKNOWN)


@unittest.skipUnless(sys.platform=='linux','Linux descriptor-relative directory fixture')
class NativeLaunchScopes(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.service=self.root/'user.slice'/'user-1000.slice'/'user@1000.service'
        self.service.mkdir(parents=True)
        self.scanner=LaunchGameScopeDiscovery(self.root,clock=lambda:1)

    def scan(self):return self.scanner.scan(1000,deadline=10)

    def test_complete_empty_and_recognized_scopes(self):
        self.assertIs(self.scan().state,GameState.IDLE)
        (self.service/'app.slice').mkdir()
        (self.service/'app.slice'/'app-steam-app42-test.scope').mkdir()
        self.assertEqual(self.scan().active_app_id,'42')

    def test_missing_root_and_traversal_failure_unknown(self):
        self.assertIs(self.scanner.scan(2000,deadline=10).state,GameState.UNKNOWN)
        with patch('os.scandir',side_effect=PermissionError()):
            self.assertIs(self.scan().state,GameState.UNKNOWN)

    def test_symlink_entry_and_root_rejected(self):
        (self.service/'alias').symlink_to(self.root,target_is_directory=True)
        self.assertIs(self.scan().state,GameState.UNKNOWN)
        alias=self.root/'root-alias';alias.symlink_to(self.root,target_is_directory=True)
        self.assertIs(LaunchGameScopeDiscovery(alias,clock=lambda:1).scan(1000,deadline=10).state,GameState.UNKNOWN)

    def test_depth_entry_bounds(self):
        (self.service/'child').mkdir()
        self.scanner.MAX_DEPTH=0
        self.assertIs(self.scan().state,GameState.UNKNOWN)
        self.scanner.MAX_DEPTH=16;self.scanner.MAX_ENTRIES=0
        self.assertIs(self.scan().state,GameState.UNKNOWN)

    def test_root_replacement_detected_at_final_check(self):
        original=os.scandir
        def changed(fd):
            self.service.rename(self.service.with_name('old.service'))
            self.service.mkdir()
            return original(fd)
        with patch('os.scandir',side_effect=changed):
            self.assertIs(self.scan().state,GameState.UNKNOWN)

    def test_expiry_during_descriptor_cleanup_rejected(self):
        now=[1]
        self.scanner._clock=lambda:now[0]
        original=os.close
        def close(fd):original(fd);now[0]=11
        with patch('os.close',side_effect=close):
            self.assertIs(self.scan().state,GameState.UNKNOWN)

    def test_scope_added_after_enumeration_is_unknown(self):
        original=os.scandir
        service=self.service
        class ChangedInventory:
            def __init__(self,fd):self.source=original(fd)
            def __enter__(self):return self.source.__enter__()
            def __exit__(self,*args):
                self.source.__exit__(*args)
                (service/'app-steam-app42-new.scope').mkdir()
        with patch('os.scandir',side_effect=ChangedInventory):
            self.assertIs(self.scan().state,GameState.UNKNOWN)


if __name__=='__main__':unittest.main()
