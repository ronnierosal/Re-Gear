"""One-shot supervised Vulkan launch; never an eGPU removal mechanism."""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

from .gamescope_wrapper import config_to_dict
from .portable_vulkan_trial import TrialEvidence, build_candidate


def mesa_layer_available(
    manifest: Path = Path('/usr/share/vulkan/implicit_layer.d/VkLayer_MESA_device_select.json'),
    libraries: tuple[Path, ...] = (Path('/usr/lib/libVkLayer_MESA_device_select.so'),
                                  Path('/usr/lib64/libVkLayer_MESA_device_select.so')),
) -> bool:
    try:
        with manifest.open(encoding='utf-8') as source:
            value = json.loads(source.read(8193))
        layer = value['layer']
        return (layer['name'] == 'VK_LAYER_MESA_device_select'
                and layer['library_path'] == 'libVkLayer_MESA_device_select.so'
                and any(path.is_file() for path in libraries))
    except (OSError, ValueError, KeyError, TypeError):
        return False


def candidate_from_record(record, *, config, argv, environment, boot_hash,
                          egpu_binding_hash, now, cards, game_idle, layer_available):
    """Revalidate actual internal card/connector ownership at launch time."""
    if (config is None or config_to_dict(config) != record['expected_config']
            or record['boot_id_sha256'] != boot_hash
            or record['egpu_binding_sha256'] != egpu_binding_hash
            or not 0 < record['expires_at'] - now <= 120):
        raise ValueError('trial launch identity or deadline changed')
    internal = tuple(card for card in cards if card.boot_vga is True)
    if len(internal) != 1 or internal[0].vendor_device != record['internal_gpu']:
        raise ValueError('trial internal GPU changed')
    connectors = tuple(c.name for c in internal[0].connectors
                       if c.internal and c.connected is True)
    evidence = TrialEvidence(
        boot_hash, record['generation'], record['internal_gpu'],
        record['internal_connector'], True, False if game_idle is True else None,
        layer_available,
    )
    return build_candidate(
        tuple(argv), environment, evidence=evidence, current_boot=boot_hash,
        current_generation=record['generation'],
        present_gpus=tuple(card.vendor_device for card in cards),
        internal_connectors=connectors,
    )


def consume_launch_candidate(state_root, *, config, argv, environment, raw_boot_id):
    # Imports stay local so ordinary launches do not collect extra evidence.
    from .portable_trial_store import PortableTrialStore

    try:
        store = PortableTrialStore(state_root)
        record = store.consume()
        if record is None:
            return None
        # The durable marker already exists. Any validation or exec failure
        # leaves the next launch on its normal policy, never a repeated trial.
        candidate = live_candidate_from_record(
            record, config=config, argv=argv, environment=environment,
            raw_boot_id=raw_boot_id,
        )
        invocation = environment.get('INVOCATION_ID', '')
        if invocation:
            store.publish_gamescope_launch(record['operation_id'], invocation)
        return candidate
    except (OSError, ValueError, TypeError, KeyError):
        return None


def live_candidate_from_record(record, *, config, argv, environment, raw_boot_id):
    from .gamescope_wrapper import _verified_egpu_binding_sha256
    from ..adapters.steamos.drm import DrmDiscovery
    from ..adapters.steamos.game_scopes import SystemdGameScopeDiscovery
    from ..domain.models import GameState

    return candidate_from_record(
        record, config=config, argv=argv, environment=environment,
        boot_hash=hashlib.sha256(raw_boot_id.encode()).hexdigest(),
        egpu_binding_hash=_verified_egpu_binding_sha256(raw_boot_id),
        now=time.monotonic(), cards=DrmDiscovery().scan(),
        game_idle=SystemdGameScopeDiscovery().scan(user_uid=os.getuid()).state is GameState.IDLE,
        layer_available=mesa_layer_available(),
    )
