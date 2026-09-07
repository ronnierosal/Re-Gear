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
