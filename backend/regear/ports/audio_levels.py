"""Command surface an audio-levels adapter must provide.

Deliberately four narrow operations rather than one general "run wpctl". The
adapter that satisfies this is expected to delegate to the existing
`PipeWireCommandRunner`, which already confines the privilege drop, the
username validation, the timeout and the output cap; a general escape hatch
here would let a caller route around all of that.

Reads and writes are separate methods on purpose. A port where `set` returned
the new value would invite trusting the write's own report of itself, and the
whole point of the readback rule in `domain.audio_levels` is that it does not.
"""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class LevelCommandResult:
    """One command's outcome. `output` is raw text for the domain to parse."""

    ok: bool
    output: str = ""
    #: Adapter-side failure reason, e.g. the runner's audio.root_required.
    #: Empty on success.
    code: str = ""


class AudioLevelsPort(Protocol):
    """Read and write the default sink's volume and the default source's mute."""

    def read_sink_volume(self) -> LevelCommandResult: ...

    def apply_sink_volume(self, percent: int) -> LevelCommandResult: ...

    def read_source_mute(self) -> LevelCommandResult: ...

    def apply_source_mute(self, muted: bool) -> LevelCommandResult: ...
