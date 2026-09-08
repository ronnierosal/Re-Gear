"""Read-only discovery of the character devices belonging to an exact eGPU.

`hdm.domain.egpu_device_policy` composes the device set an access filter must
deny, but it needs observed `(major, minor)` numbers to work from. This adapter
supplies them, resolved from the two PCI functions of the eGPU rather than from
guessed node names, so the result satisfies the exact-identity requirement in
safety invariant 4.

Both functions matter. Supervised measurement showed that denying only the DRM
nodes of a GPD G1 released the compositor and the Steam client while the session
audio daemon kept the eGPU's audio control node, leaving the device held. The
GPU and audio functions are discovered separately and reported together.

Read-only: resolves symlinks and stats device nodes. No writes, no subprocess,
no device or process action.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ...domain.egpu_device_policy import EgpuDeviceNode
from ...domain.models import EgpuResourceKind
from .pci import PCI_PATTERN


#: `/dev/snd/by-path` links a PCI function to its ALSA control node, from which
#: the card index and therefore its sibling nodes follow.
CONTROL_PATTERN = re.compile(r"controlC(?P<index>[0-9]+)")

#: Sibling ALSA nodes of one card index, mapped to the resource kind the client
#: scanner already uses for them.
ALSA_SIBLINGS: tuple[tuple[str, EgpuResourceKind], ...] = (
    ("hwC{index}D", EgpuResourceKind.AUDIO_HARDWARE),
    ("pcmC{index}D", EgpuResourceKind.AUDIO_PCM),
)

#: Bounds an unexpected `/dev/snd` from producing an unbounded scan.
MAX_ALSA_SIBLINGS = 64


@dataclass(frozen=True, slots=True)
class EgpuDeviceNodeScan:
    """Observed nodes, plus why the observation is incomplete when it is."""

    complete: bool
    nodes: tuple[EgpuDeviceNode, ...] = field(default_factory=tuple)
    error: str = ""


def _resolve_link(path: Path) -> Path:
    """Resolve a /dev by-path symlink to its target node."""
    return path.resolve(strict=True)


def _device_numbers(path: Path) -> tuple[int, int] | None:
    """Return the character device numbers for `path`, or None.

    `os.major` and `os.minor` exist only on POSIX, which is where this adapter
    runs. Discovery takes this as an injected callable so the surrounding logic
    stays testable on platforms that lack them.
    """
    try:
        info = path.stat()
    except OSError:
        return None
    rdev = getattr(info, "st_rdev", 0)
    if not rdev:
        return None
    return os.major(rdev), os.minor(rdev)


class SteamOsEgpuDeviceNodeDiscovery:
    """Resolve the exact character devices of one eGPU's PCI functions."""

    def __init__(
        self,
        dri_by_path: Path = Path("/dev/dri/by-path"),
        snd_by_path: Path = Path("/dev/snd/by-path"),
        snd_root: Path = Path("/dev/snd"),
        device_numbers: Callable[[Path], tuple[int, int] | None] = _device_numbers,
        resolve_link: Callable[[Path], Path] = _resolve_link,
    ) -> None:
        self._dri_by_path = dri_by_path
        self._snd_by_path = snd_by_path
        self._snd_root = snd_root
        self._device_numbers = device_numbers
        self._resolve_link = resolve_link

    def scan(self, *, gpu_bdf: str, audio_bdf: str) -> EgpuDeviceNodeScan:
        """Collect DRM and ALSA nodes for the exact GPU and audio functions."""
        if not PCI_PATTERN.fullmatch(gpu_bdf) or not PCI_PATTERN.fullmatch(audio_bdf):
            return EgpuDeviceNodeScan(False, error="egpu_nodes.identity_invalid")
        if gpu_bdf.lower() == audio_bdf.lower():
            return EgpuDeviceNodeScan(False, error="egpu_nodes.identity_ambiguous")

        drm_nodes, drm_error = self._drm_nodes(gpu_bdf)
        if drm_error:
            return EgpuDeviceNodeScan(False, error=drm_error)
        audio_nodes, audio_error = self._audio_nodes(audio_bdf)
        if audio_error:
            return EgpuDeviceNodeScan(False, error=audio_error)
        return EgpuDeviceNodeScan(True, (*drm_nodes, *audio_nodes))

    def _drm_nodes(
        self, gpu_bdf: str
    ) -> tuple[tuple[EgpuDeviceNode, ...], str]:
        collected: list[EgpuDeviceNode] = []
        present = 0
        for suffix, kind in (
            ("card", EgpuResourceKind.DRM_CARD),
            ("render", EgpuResourceKind.DRM_RENDER),
        ):
            link = self._dri_by_path / f"pci-{gpu_bdf}-{suffix}"
            try:
                node = self._resolve_link(link)
            except (OSError, RuntimeError):
                continue
            present += 1
            numbers = self._device_numbers(node)
            if numbers is None:
                # The link exists but its device numbers are unreadable. Skipping
                # it would emit a set that omits a node the eGPU still exposes.
                return (), "egpu_nodes.drm_incomplete"
            collected.append(EgpuDeviceNode(kind, *numbers))
        if not present:
            return (), "egpu_nodes.drm_unavailable"
        if len(collected) != 2:
            # A partial DRM set still satisfies the policy's required-kind check
            # when the render node survives, producing a policy that silently
            # omits the card node. Fail closed instead.
            return (), "egpu_nodes.drm_incomplete"
        return tuple(collected), ""

    def _audio_nodes(
        self, audio_bdf: str
    ) -> tuple[tuple[EgpuDeviceNode, ...], str]:
        control_link = self._snd_by_path / f"pci-{audio_bdf}"
        try:
            control = self._resolve_link(control_link)
        except (OSError, RuntimeError):
            return (), "egpu_nodes.audio_unavailable"
        match = CONTROL_PATTERN.fullmatch(control.name)
        if match is None:
            return (), "egpu_nodes.audio_control_unrecognised"
        numbers = self._device_numbers(control)
        if numbers is None:
            return (), "egpu_nodes.audio_unavailable"

        collected = [EgpuDeviceNode(EgpuResourceKind.AUDIO_CONTROL, *numbers)]
        index = match.group("index")
        try:
            entries = sorted(self._snd_root.iterdir(), key=lambda item: item.name)
        except OSError:
            return (), "egpu_nodes.audio_root_unreadable"
        for entry in entries:
            if len(collected) > MAX_ALSA_SIBLINGS:
                return (), "egpu_nodes.audio_sibling_limit"
            for template, kind in ALSA_SIBLINGS:
                if not entry.name.startswith(template.format(index=index)):
                    continue
                sibling = self._device_numbers(entry)
                if sibling is None:
                    # This node belongs to the eGPU's ALSA card. Omitting it
                    # would leave it openable under an otherwise valid policy.
                    return (), "egpu_nodes.audio_incomplete"
                collected.append(EgpuDeviceNode(kind, *sibling))
                break
        return tuple(collected), ""
