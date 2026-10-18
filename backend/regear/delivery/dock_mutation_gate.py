"""Nonblocking cross-process admission for dock/session mutations.

This lock is not durable intent. Teardown must create its durable claim while
holding admission, before releasing resources or writing device controls.
"""
from contextlib import contextmanager
import os
import stat
import threading

from .audio_journal_filesystem import AudioJournalFilesystem
from .whole_dock_claim import WholeDockClaimStore, RESET_PENDING

LOCK_FILENAME = "dock-mutation.lock"
_ADMISSION_KEY = object()


class DockMutationDenied(RuntimeError):
    """Admission was busy, inhibited, or could not be established safely."""


class DockMutationAdmission:
    """Server-only, expiring access to the normal admission's pinned directory.

    This is not durable intent or native authority. A borrower holds the lease
    lock until its filesystem work finishes; release cannot unlock admission
    underneath that work. No filesystem latency/cancellation guarantee exists.
    """
    def __init__(self, gate, directory, *, _key=None):
        if _key is not _ADMISSION_KEY:
            raise DockMutationDenied("dock_mutation.invalid_admission")
        self._gate = gate
        self._directory = directory
        self._active = True
        self._lock = threading.RLock()

    @contextmanager
    def borrow(self, root):
        with self._lock:
            if not self._active or root != self._gate.root:
                raise DockMutationDenied("dock_mutation.stale_admission")
            self._gate._secure(self._directory, directory=True)
            pinned = os.fstat(self._directory)
            current = os.stat(root, follow_symlinks=False)
            if (not stat.S_ISDIR(current.st_mode)
                    or (current.st_dev, current.st_ino) != (pinned.st_dev, pinned.st_ino)
                    or stat.S_IMODE(pinned.st_mode) != 0o700):
                raise DockMutationDenied("dock_mutation.root_changed")
            yield self._directory
            # Refuse evidence after a root replacement during I/O as well.
            current = os.stat(root, follow_symlinks=False)
            if (not stat.S_ISDIR(current.st_mode)
                    or (current.st_dev, current.st_ino) != (pinned.st_dev, pinned.st_ino)):
                raise DockMutationDenied("dock_mutation.root_changed")

    def _expire(self):
        with self._lock:
            self._active = False


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
        admission = None
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
                try:
                    os.stat(RESET_PENDING, dir_fd=directory, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    raise DockMutationDenied("dock_mutation.inhibited")
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
            if not allow_inhibited:
                admission = DockMutationAdmission(self, directory, _key=_ADMISSION_KEY)
            yield admission
        finally:
            if admission is not None:
                admission._expire()
            if lock is not None:
                os.close(lock)
            if directory is not None:
                os.close(directory)
