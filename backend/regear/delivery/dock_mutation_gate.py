"""Nonblocking cross-process admission for dock/session mutations.

This lock is not durable intent. Teardown must create its durable claim while
holding admission, before releasing resources or writing device controls.
"""
from contextlib import contextmanager
import os
import stat

from .audio_journal_filesystem import AudioJournalFilesystem
from .whole_dock_claim import WholeDockClaimStore

LOCK_FILENAME = "dock-mutation.lock"


class DockMutationDenied(RuntimeError):
    """Admission was busy, inhibited, or could not be established safely."""


class DockMutationGate(AudioJournalFilesystem):
    @contextmanager
    def admit(self, *, allow_inhibited=False):
        """Hold exclusive admission through the entire caller operation.

        allow_inhibited is an internal teardown-continuation capability, never a
        player-supplied override. Admission is non-reentrant; nested calls fail
        immediately. Body exceptions propagate unchanged.
        """
        if type(allow_inhibited) is not bool:
            raise DockMutationDenied("dock_mutation.invalid_override")
        directory = None
        lock = None
        try:
            try:
                import fcntl
                directory = self._directory()
                if stat.S_IMODE(os.fstat(directory).st_mode) != 0o700:
                    raise ValueError("dock mutation directory must be private")
                lock = os.open(LOCK_FILENAME, os.O_RDWR | os.O_CREAT |
                               os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=directory)
                self._secure(lock)
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                if not allow_inhibited:
                    # Reuse the pinned directory instead of re-resolving its path.
                    claims = WholeDockClaimStore(self.root, owner_uid=self.owner_uid,
                                                trusted_directory_fd=directory)
                    # Claim inspection must not wait on a competing claim writer.
                    # Mutation admission serializes legitimate claim creation;
                    # an in-progress/nonconforming writer is treated as inhibited.
                    claim_lock = None
                    try:
                        claim_lock = os.open("whole-dock-claim.lock", os.O_RDWR |
                                             os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                                             0o600, dir_fd=directory)
                        self._secure(claim_lock)
                        fcntl.flock(claim_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        if claims._load(directory) is not None:
                            raise DockMutationDenied("dock_mutation.inhibited")
                    finally:
                        if claim_lock is not None:
                            os.close(claim_lock)
            except DockMutationDenied:
                raise
            except Exception as error:
                raise DockMutationDenied("dock_mutation.unavailable_or_busy") from error
            yield
        finally:
            if lock is not None:
                os.close(lock)
            if directory is not None:
                os.close(directory)
