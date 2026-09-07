from contextlib import contextmanager,ExitStack
import unittest
from unittest.mock import Mock,patch
from backend.hdm.delivery import device_filter_journal as journal
from tests.test_device_filter_journal import binding


class InitialPublicationTests(unittest.TestCase):
    def write(self,*,fsync=None,publish=None,unlink=None):
        instance=object.__new__(journal.FilterJournal)
        record=journal.JournalRecord(1,journal.FilterLifecycle(binding()))
        with ExitStack() as stack:
            stack.enter_context(patch.object(journal.os,'O_NOFOLLOW',0,create=True))
            stack.enter_context(patch.object(journal.os,'open',return_value=10))
            stack.enter_context(patch.object(journal.os,'write',side_effect=lambda fd,data:len(data)))
            stack.enter_context(patch.object(journal.os,'close'))
            stack.enter_context(patch.object(journal.os,'fsync',side_effect=fsync))
            stack.enter_context(patch.object(journal.os,'unlink',side_effect=unlink))
            stack.enter_context(patch.object(journal,'_publish_exclusive',side_effect=publish))
            instance._write(9,record,initial=True)

    def test_directory_fsync_failure_is_typed_after_exclusive_publication(self):
        with self.assertRaises(journal.JournalInitialPublicationUncertain) as caught:
            self.write(fsync=[None,OSError('directory sync')])
        self.assertEqual(caught.exception.binding,binding())

    def test_temporary_cleanup_failure_after_publication_is_typed(self):
        with self.assertRaises(journal.JournalInitialPublicationUncertain):self.write(unlink=PermissionError())

    def test_prepublication_failure_and_duplicate_are_never_typed(self):
        for kwargs in (dict(fsync=OSError()),dict(publish=FileExistsError()),dict(publish=PermissionError())):
            with self.subTest(kwargs=tuple(kwargs)):
                try:self.write(**kwargs)
                except OSError as error:self.assertNotIsInstance(error,journal.JournalInitialPublicationUncertain)
                else:self.fail('failure expected')

    def test_lock_exit_failure_is_typed_only_after_write_success(self):
        instance=object.__new__(journal.FilterJournal)
        @contextmanager
        def after():
            yield 9
            raise OSError('lock close')
        instance._locked=after;instance._write=Mock()
        with self.assertRaises(journal.JournalInitialPublicationUncertain):instance.create(binding())
        @contextmanager
        def before():
            raise TimeoutError('lock busy')
            yield 9
        instance._locked=before
        with self.assertRaises(TimeoutError):instance.create(binding())

    def test_lock_cleanup_cannot_erase_known_exclusive_publication(self):
        instance=object.__new__(journal.FilterJournal)
        @contextmanager
        def locked():
            try:yield 9
            finally:raise OSError('lock close')
        instance._locked=locked
        instance._write=Mock(side_effect=journal.JournalInitialPublicationUncertain(binding()))
        with self.assertRaises(journal.JournalInitialPublicationUncertain) as caught:instance.create(binding())
        self.assertEqual(caught.exception.binding,binding())


if __name__=='__main__':unittest.main()
