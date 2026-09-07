"""Real process death while holding the fixture journal lock; no kernel filter."""
import os
from pathlib import Path
import select
import signal
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from hdm.delivery.device_filter_journal import FilterJournal
from hdm.delivery.device_filter_lifecycle import LaunchBinding, OwnedFilter, Phase
from scripts.probe_killed_filter_controller import terminate_owned


@unittest.skipUnless(sys.platform == 'linux', 'Linux fork and flock fixture')
class JournalProcessCrashTests(unittest.TestCase):
    def test_durable_pending_record_and_lock_survive_writer_sigkill(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = os.open(temporary, os.O_RDONLY | os.O_DIRECTORY)
            read_fd, write_fd = os.pipe()
            child = None
            try:
                journal = FilterJournal(temporary, owner_uid=os.getuid(), trusted_directory_fd=root)
                binding = LaunchBinding('a'*64, 'crash-test', 'gamescope-session.service',
                    'b'*32, max(os.getuid(), 1), os.getpid(), 1, 1, 2, 'c'*64, time.monotonic()+20)
                journal.create(binding)
                owned = OwnedFilter(3, 'd'*64, True, False, 4, 5)
                child = os.fork()
                if child == 0:
                    try:
                        os.close(read_fd)
                        with journal.transaction() as tx:
                            record = tx.read(binding.operation, binding.unit)
                            pending = tx.change(binding.operation, binding.unit, record.revision,
                                'prepare_pin', owned=owned, observed=binding, now=time.monotonic())
                            if pending.lifecycle.phase is not Phase.PIN_PENDING:
                                os._exit(3)
                            if os.write(write_fd, b'p') != 1:
                                os._exit(4)
                            # Remain inside the actual locked transaction until killed.
                            signal.pause()
                        os._exit(5)
                    except BaseException:
                        os._exit(2)
                os.close(write_fd)
                write_fd = None
                self.assertEqual(select.select([read_fd], [], [], 3)[0], [read_fd])
                self.assertEqual(os.read(read_fd, 1), b'p')
                os.kill(child, signal.SIGKILL)
                done, status = os.waitpid(child, 0)
                self.assertEqual(done, child)
                child = None
                self.assertTrue(os.WIFSIGNALED(status))
                self.assertEqual(os.WTERMSIG(status), signal.SIGKILL)
                # New journal object must acquire the released flock and read the
                # committed phase; no in-memory record crosses this boundary.
                recovered = FilterJournal(temporary, owner_uid=os.getuid(), trusted_directory_fd=root)
                with recovered.transaction() as tx:
                    record = tx.read(binding.operation, binding.unit)
                    self.assertEqual(record.lifecycle.phase, Phase.PIN_PENDING)
                    self.assertEqual(record.lifecycle.owned, owned)
                    self.assertFalse(record.delivery_granted)
                    cancelled = tx.change(binding.operation, binding.unit, record.revision, 'recover')
                    self.assertEqual(cancelled.lifecycle.phase, Phase.CANCELLED)
                    self.assertFalse(cancelled.delivery_granted)
            finally:
                if child is not None: terminate_owned(child)
                os.close(read_fd)
                if write_fd is not None: os.close(write_fd)
                os.close(root)


if __name__ == '__main__': unittest.main()
