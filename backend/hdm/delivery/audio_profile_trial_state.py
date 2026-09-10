"""Durable identity for the separately supervised audio profile trial."""
from dataclasses import dataclass
from enum import Enum
import re


class AudioTrialPhase(str, Enum):
    PREPARED = "prepared"
    OFF_REQUESTED = "off_requested"
    OFF_OBSERVED = "off_observed"
    RESTORE_REQUESTED = "restore_requested"
    RESTORED = "restored"
    RECOVERY_REQUIRED = "recovery_required"
    #: Ended without restoration because the boot that owned it is gone. See
    #: `decide_trial_boot`.
    ABANDONED = "abandoned"


#: The phases that end a record. A terminal record stays on disk as a replay
#: tombstone for its operation, but it is never pending recovery and never
#: refuses a new trial.
TERMINAL_PHASES = frozenset({AudioTrialPhase.RESTORED, AudioTrialPhase.ABANDONED})

#: A boot identity is the sha256 of the kernel's boot id. Anything else is not
#: an identity, and comparing it anyway would decide a record's fate on a value
#: bound to nothing.
BOOT_HASH_RE = re.compile(r"[0-9a-f]{64}")


class AudioTrialBootVerdict(str, Enum):
    #: The record was written by the boot that is running now, so a live
    #: observation can still be matched against it.
    SAME_BOOT = "same_boot"
    #: The machine rebooted. Nothing this record claims can be revalidated.
    DIFFERENT_BOOT = "different_boot"
    #: The running boot could not be identified, so neither of the above is
    #: shown. Not a synonym for `DIFFERENT_BOOT`; see `decide_trial_boot`.
    UNIDENTIFIED_BOOT = "unidentified_boot"


def decide_trial_boot(record, live_boot_hash):
    """Whether a durable trial record still belongs to the running boot.

    `AudioProfileTrial._fresh` binds every observation to `record.boot_hash`,
    which is what makes restoration safe: nothing is restored except onto the
    same attachment that was taken away. It also means a record cannot outlive
    its boot -- after a reboot no live observation can match it, so no
    restoration attempt can ever succeed, however many times it is retried.

    `relaunch_intent` reaches the same conclusion about the same fact: "A reboot
    ends every claim this record had." A record whose boot is gone is finished,
    and the caller retires it rather than keeping it pending against a boot that
    will never come back.

    One thing inverts from that precedent, and this is where the verdicts
    matter. There, an unidentifiable boot is treated exactly like a different
    one, because refusing to relaunch is the safe direction and both refuse.
    Here retiring is the *permissive* direction -- it is what lets supervised
    transitions run again -- so a record is retired only when the running boot
    is positively identified and positively different. An unreadable boot id
    leaves the record pending and everything blocked, which is the same
    fail-closed answer the rest of this module gives to an unknown.

    Pure. It reads nothing and stores nothing; the caller supplies the live
    boot identity and owns what happens to the record.
    """
    if type(record) is not AudioTrialRecord:
        raise ValueError("typed audio trial record required")
    if type(live_boot_hash) is not str or BOOT_HASH_RE.fullmatch(live_boot_hash) is None:
        return AudioTrialBootVerdict.UNIDENTIFIED_BOOT
    if live_boot_hash == record.boot_hash:
        return AudioTrialBootVerdict.SAME_BOOT
    return AudioTrialBootVerdict.DIFFERENT_BOOT


@dataclass(frozen=True)
class AudioTrialRecord:
    operation: str
    boot_hash: str
    topology_hash: str
    audio_bdf: str
    original_profile: str
    portable_sink: str
    uid: int
    revision: int = 1
    phase: AudioTrialPhase = AudioTrialPhase.PREPARED

    def __post_init__(self):
        for value, pattern in ((self.operation, r"[A-Za-z0-9_.:-]{1,128}"),
                (self.boot_hash, r"[0-9a-f]{64}"), (self.topology_hash, r"[0-9a-f]{64}"),
                (self.audio_bdf, r"[0-9a-f]{4}:[0-9a-f]{2}:[0-1][0-9a-f]\.[0-7]"),
                (self.original_profile, r"[A-Za-z0-9_.:+-]{1,256}"),
                (self.portable_sink, r"[A-Za-z0-9_.:-]{1,256}")):
            if type(value) is not str or re.fullmatch(pattern, value) is None:
                raise ValueError("invalid audio trial identity")
        if (self.original_profile == "off" or type(self.uid) is not int or self.uid <= 0
                or type(self.revision) is not int or self.revision <= 0
                or type(self.phase) is not AudioTrialPhase):
            raise ValueError("invalid audio trial state")
