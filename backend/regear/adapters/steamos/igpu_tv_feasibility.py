"""Read-only prerequisites inventory, never presenter support certification.

This private seam is not wired to a CLI/RPC. Artifact metadata does not prove
installed versions, plugin features, capture support or DRM lease authority.
PipeWire process properties are self-reported; even a unique PID match cannot
authenticate stream ownership, game rendering, or moving frames on a TV.
The parser admission limit does not hard-bound subprocess capture memory;
the existing runner captures output before checking its own result-size limit.
"""
from dataclasses import dataclass
import json
from pathlib import Path
import stat

from ...domain.models import Confidence
from .commands import PipeWireCommandRunner


# Fixed Linux system paths only. No PATH search, binary execution or plugin load.
ARTIFACTS = (
    ("gamescope", "/usr/bin/gamescope"),
    ("pipewire_dump", "/usr/bin/pw-dump"),
    ("gstreamer_inspector", "/usr/bin/gst-inspect-1.0"),
    ("gstreamer_pipewire_library", "/usr/lib/gstreamer-1.0/libgstpipewire.so"),
    ("gstreamer_kms_library", "/usr/lib/gstreamer-1.0/libgstkms.so"),
)
MAX_DUMP_BYTES = 256 * 1024
MAX_OBJECTS = 2048


def dependency_metadata():
    """Inspect fixed file metadata, rejecting observed symlinks.

    Missing paths are missing only at these locations, not proof of absence
    from all possible packaging layouts. No contents or versions are read.
    These best-effort pathname checks are not race-resistant descriptor-relative
    traversal and never establish authority to load or execute an artifact.
    """
    rows = []
    for label, name in ARTIFACTS:
        try:
            path = Path(name)
            parents = (path.parent, *path.parent.parents)
            trusted = all(
                stat.S_ISDIR((info := parent.lstat()).st_mode)
                and info.st_uid == 0 and not info.st_mode & 0o022
                for parent in parents
            )
            info = path.lstat()
            trusted = (trusted and stat.S_ISREG(info.st_mode)
                       and info.st_uid == 0 and not info.st_mode & 0o022)
            state = "present_at_expected_path" if trusted else "untrusted_metadata"
        except FileNotFoundError:
            state = "missing_at_expected_path"
        except OSError:
            state = "metadata_unavailable"
        rows.append((label, state))
    return tuple(rows)


@dataclass(frozen=True, slots=True)
class FeasibilityInventory:
    dependencies: tuple[tuple[str, str], ...]
    stream_code: str

    def to_payload(self):
        """Only allowlisted categories; never return raw metadata or identities."""
        states = {"present_at_expected_path", "missing_at_expected_path",
                  "untrusted_metadata", "metadata_unavailable"}
        streams = {"observation_unavailable", "session_unverified", "sample_stale",
                   "session_or_topology_changed", "dump_unavailable", "dump_invalid",
                   "candidate_missing", "candidate_ambiguous", "candidate_observed_unverified"}
        # Keep order fixed and suppress arbitrary labels supplied by test/adaptor seams.
        rows = dict(self.dependencies)
        return {
            "schema_version": 1,
            "dependencies": {label: rows.get(label) if type(rows.get(label)) is str and rows.get(label) in states
                             else "metadata_unavailable" for label, _ in ARTIFACTS},
            "stream_code": self.stream_code if type(self.stream_code) is str and self.stream_code in streams else "observation_unavailable",
            "presenter_supported": False,
            "stream_ownership_verified": False,
            "game_renderer_verified": False,
            "frame_delivery_verified": False,
            "drm_lease_verified": False,
        }


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_key")
        result[key] = value
    return result


def classify_stream_metadata(raw: bytes, gamescope_pid: int) -> str:
    """Inspect declared PID matches; no match can establish authenticated ownership."""
    if (type(raw) is not bytes or len(raw) > MAX_DUMP_BYTES
            or type(gamescope_pid) is not int or not 0 < gamescope_pid < 2**31):
        return "dump_invalid"
    try:
        objects = json.loads(raw, object_pairs_hook=_unique_object)
        if not isinstance(objects, list) or len(objects) > MAX_OBJECTS:
            return "dump_invalid"
        seen = set()
        matches = 0
        unattributable = False
        for item in objects:
            if not isinstance(item, dict):
                return "dump_invalid"
            identity = item.get("id")
            if type(identity) is not int or not 0 <= identity < 2**32 or identity in seen:
                return "dump_invalid"
            seen.add(identity)
            if item.get("type") != "PipeWire:Interface:Node":
                continue
            info = item.get("info")
            if not isinstance(info, dict) or not isinstance(info.get("props"), dict):
                return "dump_invalid"
            props = info["props"]
            if props.get("media.class") != "Video/Source":
                continue
            pid = props.get("application.process.id")
            if type(pid) is int and 0 < pid < 2**31:
                declared = pid
            elif (type(pid) is str and pid.isascii() and pid.isdecimal()
                  and 0 < len(pid) <= 10 and 0 < int(pid) < 2**31):
                declared = int(pid)
            else:
                # An unattributable video source may be another Gamescope source.
                unattributable = True
                continue
            if declared == gamescope_pid:
                matches += 1
        return ("candidate_ambiguous" if unattributable else "candidate_missing" if matches == 0 else
                "candidate_observed_unverified" if matches == 1 else "candidate_ambiguous")
    except (ValueError, TypeError, RecursionError, UnicodeError):
        return "dump_invalid"


class IgpuTvFeasibilityCollector:
    def __init__(self, *, observations, gamescope_sessions, session_user,
                 pipewire=None, metadata=dependency_metadata):
        self._observations = observations
        self._sessions = gamescope_sessions
        # Existing trusted runtime composition supplies the authenticated user.
        # This collector neither guesses the user nor changes permissions.
        self._user = session_user
        self._pipewire = pipewire or PipeWireCommandRunner()
        self._metadata = metadata

    @staticmethod
    def _valid(current, session):
        return (current is not None and session is not None and session.exact is True
                and bool(session.generation) and bool(current.sample_id)
                and bool(current.generation)
                and current.snapshot.gamescope.running is True
                and current.snapshot.gamescope.confidence == Confidence.VERIFIED
                and type(current.snapshot.gamescope.pid) is int
                and 0 < current.snapshot.gamescope.pid < 2**31)

    def collect(self) -> FeasibilityInventory:
        missing = tuple((label, "metadata_unavailable") for label, _ in ARTIFACTS)
        dependencies = missing
        try:
            dependencies = self._metadata()
            first_session = self._sessions.observe()
            first = self._observations.observe()
            if not self._valid(first, first_session):
                return FeasibilityInventory(dependencies, "session_unverified")
            dump = self._pipewire.dump(self._user)
            second = self._observations.observe()
            second_session = self._sessions.observe()
            if not self._valid(second, second_session):
                return FeasibilityInventory(dependencies, "session_unverified")
            if first.sample_id == second.sample_id:
                return FeasibilityInventory(dependencies, "sample_stale")
            if (first_session.generation != second_session.generation
                    or first.snapshot.gamescope != second.snapshot.gamescope
                    or first.snapshot.displays != second.snapshot.displays
                    or first.snapshot.gpus != second.snapshot.gpus):
                return FeasibilityInventory(dependencies, "session_or_topology_changed")
            if dump.ok is not True:
                return FeasibilityInventory(dependencies, "dump_unavailable")
            code = classify_stream_metadata(dump.output, first.snapshot.gamescope.pid)
            return FeasibilityInventory(dependencies, code)
        except Exception:
            return FeasibilityInventory(missing, "observation_unavailable")
