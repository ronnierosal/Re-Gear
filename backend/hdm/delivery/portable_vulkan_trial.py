"""Pure, opt-in supervised GPU selection candidate.

Schema 1 selects Vulkan only; explicit schema 2 adds Mesa OpenGL selection.
Neither can restart a session, remove a device, or certify resource release.
"""
from dataclasses import dataclass
from typing import Mapping

from .gamescope_wrapper import VENDOR_DEVICE_RE, rewrite_gamescope_argv


@dataclass(frozen=True)
class TrialEvidence:
    boot: str
    generation: str
    internal_gpu: str
    internal_connector: str
    identity_verified: bool
    game_running: bool | None
    mesa_layer_verified: bool


def build_candidate(argv: tuple[str, ...], environment: Mapping[str, str], *,
                    evidence: TrialEvidence, current_boot: str,
                    current_generation: str, present_gpus: tuple[str, ...],
                    internal_connectors: tuple[str, ...], schema_version: int = 1) -> tuple[tuple[str, ...], dict[str, str]]:
    """Build a fresh session environment; caller must supervise any execution."""
    if type(schema_version) is not int or schema_version not in (1, 2):
        raise ValueError('unsupported explicit trial schema')
    if (not current_boot or not current_generation or
            evidence.boot != current_boot or evidence.generation != current_generation):
        raise ValueError("stale session evidence")
    if (evidence.identity_verified is not True or
            not VENDOR_DEVICE_RE.fullmatch(evidence.internal_gpu) or
            present_gpus.count(evidence.internal_gpu) != 1 or
            internal_connectors.count(evidence.internal_connector) != 1):
        raise ValueError("internal GPU identity or connector unverified")
    if evidence.game_running is not False or evidence.mesa_layer_verified is not True:
        raise ValueError("idle game state and Mesa layer verification required")
    # Do not silently override custom driver/layer routing or prime policy.
    conflicts = ("DRI_PRIME", "VK_ICD_FILENAMES", "VK_DRIVER_FILES",
                 "VK_LOADER_DRIVERS_SELECT", "VK_LOADER_DRIVERS_DISABLE",
                 "VK_LOADER_LAYERS_DISABLE", "VK_LAYER_PATH", "VK_INSTANCE_LAYERS",
                 "NODEVICE_SELECT")
    if any(key in environment for key in conflicts):
        raise ValueError("conflicting GPU environment requires review")
    candidate = dict(environment)
    candidate["MESA_VK_DEVICE_SELECT"] = evidence.internal_gpu
    candidate["MESA_VK_DEVICE_SELECT_FORCE_DEFAULT_DEVICE"] = "1"
    if schema_version == 2:
        candidate["DRI_PRIME"] = evidence.internal_gpu
    arguments = rewrite_gamescope_argv(argv, output_order=f"*,{evidence.internal_connector}",
                                       vendor_device=evidence.internal_gpu)
    return arguments, candidate


def restore_environment(candidate: Mapping[str, str], original: Mapping[str, str], *, schema_version: int = 1) -> dict[str, str]:
    """Restore only trial-owned keys in a future launch; not a live rollback."""
    restored = dict(candidate)
    if type(schema_version) is not int or schema_version not in (1, 2):
        raise ValueError('unsupported explicit trial schema')
    keys = ("MESA_VK_DEVICE_SELECT", "MESA_VK_DEVICE_SELECT_FORCE_DEFAULT_DEVICE")
    if schema_version == 2:
        keys += ("DRI_PRIME",)
    for key in keys:
        restored.pop(key, None)
        if key in original:
            restored[key] = original[key]
    return restored
