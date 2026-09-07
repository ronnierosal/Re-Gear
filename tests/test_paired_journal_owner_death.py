import unittest
from unittest.mock import Mock,patch
from types import SimpleNamespace
from scripts import probe_paired_journal_owner_death as fixture
from scripts.probe_paired_journal_fixture import publish_journal_pair,recover_journal_pair
from tests.test_paired_journal_fixture import MemoryJournal
from hdm.delivery.device_filter_lifecycle import LaunchBinding,Phase,PairedStage
from hdm.delivery.device_filter_recovery import FilterRecovery
from hdm.delivery.device_receive_recovery import ReceiveRecovery
from hdm.delivery.cgroup_retention_map import MapIdentity
from hdm.delivery.device_receive_kernel import ReceiveIdentity,ReceivePinAbsent,FileReceiveLink


class PairedJournalOwnerDeathTests(unittest.TestCase):
    def setUp(self):
        self.binding=LaunchBinding('a'*64,'fixture','gamescope-session.service','b'*32,1000,123,456,1,789,'c'*64,100.)
        self.journal=MemoryJournal(self.binding)
        self.retained=Mock(map_fd=21)
        self.retained.create.return_value=MapIdentity(2);self.retained.identity.return_value=MapIdentity(2)
        self.retained.release_entry.return_value=True
        self.receive=Mock(program_fd=22,link_fd=23)
        self.receive.link_identity.return_value=ReceiveIdentity(3,4,5,6)
        self.receive.probe_program_present.return_value=False
        self.pins=Mock(fd=8)
        self.events=[]
        self.layout=SimpleNamespace(file_inode_offset=1,inode_mode_offset=2,inode_rdev_offset=3,hook_btf_id=5)

    def publish(self,ready=None,before_receive_pin=False):
        def publisher(*args,**kwargs):
            return publish_journal_pair(*args,**kwargs,pins_factory=lambda **k:self.pins,compiler=lambda *a,**k:b'program')
        def marker(packet):
            self.assertFalse(self.journal.locked)
            self.assertEqual(packet,fixture.BEFORE_READY if before_receive_pin else fixture.READY)
            self.retained.close.assert_not_called();self.receive.close.assert_not_called()
            self.assertEqual(self.journal.read().paired.stage,
                PairedStage.RECEIVE_INTENT if before_receive_pin else PairedStage.RECEIVE_CONFIRMED)
            self.events.append('ready')
        def wait():self.events.append('wait');raise RuntimeError('simulated killed owner')
        with patch.object(fixture.os,'major',lambda dev:1,create=True),patch.object(fixture.os,'minor',lambda dev:3,create=True):
            fixture.publish_live(self.journal,self.binding,10,self.layout,3,
                map_factory=lambda:self.retained,receive_factory=lambda:self.receive,
                publisher=publisher,send_ready=ready or marker,wait_for_death=wait,
                fstat=lambda fd:self.events.append(('fstat',fd)),before_receive_pin=before_receive_pin)

    def test_ready_has_live_fds_after_durable_confirmation_outside_lock(self):
        with self.assertRaises(RuntimeError):self.publish()
        self.assertEqual(self.events,[('fstat',21),('fstat',22),('fstat',23),'ready','wait'])
        self.assertFalse(self.journal.locked)
        self.receive.close.assert_called();self.retained.close.assert_called()

    def test_missing_live_fd_cannot_signal_ready(self):
        self.receive.link_fd=None
        marker=Mock()
        with self.assertRaises(ValueError):self.publish(marker)
        marker.assert_not_called()

    def test_kernel_identity_mismatch_cannot_signal_ready(self):
        self.retained.identity.side_effect=[MapIdentity(2),MapIdentity(9)]
        marker=Mock()
        with self.assertRaises(ValueError):self.publish(marker)
        marker.assert_not_called()

    def test_recovery_callback_only_after_exact_death_confirmation(self):
        events=[]
        result=fixture.verify_death(ready=lambda:fixture.READY,deny=lambda:True,
            kill_controller=lambda:events.append('kill-reap'),recover=lambda:events.append('fresh-reader') or {})
        self.assertEqual(events,['kill-reap','fresh-reader'])
        self.assertTrue(result['controller_sigkill_verified'])
        recovery=Mock()
        with self.assertRaises(OSError):fixture.verify_death(ready=lambda:fixture.READY,deny=lambda:True,
            kill_controller=Mock(side_effect=OSError()),recover=recovery)
        recovery.assert_not_called()

    def test_real_recovery_after_simulated_death_persists_cancel_complete(self):
        with self.assertRaises(RuntimeError):self.publish()
        recovery=ReceiveRecovery(map_factory=lambda:self.retained,receive_factory=lambda:self.receive,
            directory_factory=lambda:self.pins,unlink=Mock())
        def recover():
            return recover_journal_pair(lambda:self.journal,self.binding,current_boot_hash=self.binding.boot_hash,
                observe_denial=lambda:True,observe_restored=lambda:True,
                recovery_factory=lambda journal:FilterRecovery(journal,receive_recovery=recovery))
        report=fixture.verify_death(ready=lambda:fixture.READY,deny=lambda:True,kill_controller=lambda:None,recover=recover)
        self.assertEqual(self.journal.read().lifecycle.phase,Phase.CANCELLED)
        self.assertEqual(self.journal.read().paired.stage,PairedStage.COMPLETE)
        self.assertFalse(report['launch_authorized']);self.assertFalse(report['disconnect_clearance'])

    def test_failure_packets_never_include_message_or_identifiers(self):
        packet=fixture.failure_packet('receive_pin',PermissionError(13,'private pointer 0x1234'))
        self.assertNotIn(b'private',packet);self.assertNotIn(b'0x1234',packet)
        self.assertEqual(fixture.parse_failure(packet),dict(stage='receive_pin',error_type='PermissionError',errno=13))
        with self.assertRaises(ValueError):fixture.parse_failure(b'failed:{"stage":"wait","error_type":"OSError","errno":true}')
        with self.assertRaises(ValueError):fixture.parse_failure(b'paired-journal-live')

    def test_bad_readiness_or_denial_never_kills_or_recovers(self):
        kill,recover=Mock(),Mock()
        for ready,deny in ((b'paired-live',True),(fixture.READY,False)):
            with self.assertRaises(ValueError):fixture.verify_death(ready=lambda:ready,deny=lambda:deny,
                kill_controller=kill,recover=recover)
        kill.assert_not_called();recover.assert_not_called()

    def test_before_pin_has_durable_intent_and_live_fds_outside_lock(self):
        with self.assertRaises(RuntimeError):self.publish(before_receive_pin=True)
        self.receive.pin.assert_not_called()
        self.assertEqual(self.journal.read().paired.stage,PairedStage.RECEIVE_INTENT)
        self.assertFalse(self.journal.locked)

    def test_before_pin_requires_exact_marker_and_death_before_recovery(self):
        recover=Mock()
        with self.assertRaises(ValueError):fixture.verify_death(ready=lambda:fixture.READY,deny=lambda:True,
            kill_controller=Mock(),recover=recover,before_receive_pin=True)
        with self.assertRaises(OSError):fixture.verify_death(ready=lambda:fixture.BEFORE_READY,deny=lambda:True,
            kill_controller=Mock(side_effect=OSError()),recover=recover,before_receive_pin=True)
        recover.assert_not_called()
        reader=Mock()
        with self.assertRaises(ValueError):fixture.recover_before_pin(reader,self.binding,
            current_boot_hash=self.binding.boot_hash,observe_restored=lambda:True)
        reader.assert_not_called()

    def test_fixture_receive_wrapper_requires_typed_absence(self):
        owner=object.__new__(fixture.BeforePinReceive)
        owner.close=Mock()
        for error in (ReceivePinAbsent(2,'missing'),FileNotFoundError(2,'metadata'),PermissionError(13,'denied')):
            with patch.object(FileReceiveLink,'recover',side_effect=error):
                with self.assertRaises(type(error)):owner.recover(8,'a'*64,ReceiveIdentity(3,4,5,6))
        with patch.object(FileReceiveLink,'recover',return_value=1):
            with self.assertRaises(ValueError):owner.recover(8,'a'*64,ReceiveIdentity(3,4,5,6))
        owner.close.assert_called_once()

    def test_actual_recovery_handles_unpinned_intent_only_after_quiescence(self):
        with self.assertRaises(RuntimeError):self.publish(before_receive_pin=True)
        self.receive.recover.side_effect=ReceivePinAbsent(2,'missing')
        recovery=ReceiveRecovery(map_factory=lambda:self.retained,receive_factory=lambda:self.receive,
            directory_factory=lambda:self.pins,unlink=Mock())
        result=fixture.recover_before_pin(lambda:self.journal,self.binding,current_boot_hash=self.binding.boot_hash,
            observe_restored=lambda:True,prior_owner_quiesced=True,
            recovery_factory=lambda journal:FilterRecovery(journal,receive_recovery=recovery))
        self.assertTrue(result['before_receive_pin_checkpoint'])
        self.assertFalse(result['post_death_denial_observed'])
        self.assertEqual(self.journal.read().paired.stage,PairedStage.COMPLETE)

    def test_unexpected_published_pin_cannot_complete_before_pin_fixture(self):
        with self.assertRaises(RuntimeError):self.publish(before_receive_pin=True)
        owner=object.__new__(fixture.BeforePinReceive);owner.close=Mock()
        recovery=ReceiveRecovery(map_factory=lambda:self.retained,receive_factory=lambda:owner,
            directory_factory=lambda:self.pins,unlink=Mock())
        with patch.object(FileReceiveLink,'recover',return_value=1):
            with self.assertRaises(ValueError):fixture.recover_before_pin(lambda:self.journal,self.binding,
                current_boot_hash=self.binding.boot_hash,observe_restored=lambda:True,prior_owner_quiesced=True,
                recovery_factory=lambda journal:FilterRecovery(journal,receive_recovery=recovery))
        self.retained.release_entry.assert_not_called()
        self.assertEqual(self.journal.read().paired.stage,PairedStage.RECEIVE_INTENT)


if __name__=='__main__':unittest.main()
