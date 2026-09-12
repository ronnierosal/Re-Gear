"""Connector ownership follows hardware evidence, not EDID or renderer choice."""
from __future__ import annotations

import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.adapters.steamos.discovery import SteamOsDiscovery
from regear.adapters.steamos.drm import DrmCardRecord, DrmConnectorRecord
from regear.adapters.steamos.game_scopes import GameScopeScan
from regear.adapters.steamos.gamescope import GamescopeScan
from regear.adapters.steamos.host import HostRecord
from regear.adapters.transition_runtime import versioned_snapshot_observation
from regear.application.snapshot import SnapshotReport, report_to_public_dict
from regear.domain.inference import infer_operating_mode
from regear.domain.models import Confidence, EgpuLinkObservation, EgpuLinkState, GameState
from regear.domain.serialization import snapshot_from_dict, snapshot_to_dict
from test_steamos_snapshot import Fixed, FixedTopology, certified_topology


def inventory():
    internal = DrmCardRecord(
        "card4", "0000:01:00.0", "0x1002", "0x0001", True, "amdgpu",
        (DrmConnectorRecord("card4", "eDP-1", "connected", "enabled"),),
    )
    external = DrmCardRecord(
        "card9", "0000:08:00.0", "0x1002", "0x7480", False, "amdgpu",
        (DrmConnectorRecord("card9", "HDMI-A-9", "connected", "disabled", (), "e" * 64),),
    )
    return internal, external


class FixedLink:
    def observe(self, root):
        return EgpuLinkObservation(True, EgpuLinkState.UP, Confidence.VERIFIED)


def collect(cards):
    return SteamOsDiscovery(
        drm=Fixed(cards),
        gamescope=Fixed(GamescopeScan(None, 0, error="Gamescope process was not found")),
        game_scopes=Fixed(GameScopeScan(GameState.RUNNING)),
        pci_usb4=FixedTopology(*certified_topology()),
        host=Fixed(HostRecord("ASUSTeK COMPUTER INC.", "ROG Ally X RC72LA", "RC72LA")),
        link_health=FixedLink(),
    ).collect_snapshot()


class DisplayGpuOwnershipTests(unittest.TestCase):
    def test_collects_external_owner_even_without_renderer_or_active_output(self):
        snapshot = collect(inventory())
        panel, tv = snapshot.displays
        external = next(gpu for gpu in snapshot.gpus if gpu.role.value == "external")
        self.assertEqual(panel.owning_gpu_stable_id, "internal-gpu")
        self.assertEqual(tv.owning_gpu_stable_id, external.stable_id)
        self.assertEqual(tv.owning_gpu_confidence, Confidence.VERIFIED)
        self.assertIsNone(tv.active)
        self.assertIsNone(external.selected_for_render)

    def test_same_tv_on_internal_gpu_changes_owner_but_preserves_edid_identity(self):
        internal, external = inventory()
        before = collect((internal, external)).displays[-1]
        tv = replace(external.connectors[0], card=internal.name)
        after = collect((replace(internal, connectors=(tv,)), replace(external, connectors=()))).displays[0]
        self.assertEqual(before.stable_id, after.stable_id)
        self.assertNotEqual(before.owning_gpu_stable_id, after.owning_gpu_stable_id)
        self.assertEqual(after.owning_gpu_stable_id, "internal-gpu")
        self.assertEqual(after.owning_gpu_confidence, Confidence.VERIFIED)

    def test_renumber_and_reverse_inventory_preserves_owners(self):
        cards = inventory()
        before = collect(cards)
        renamed = tuple(
            replace(card, name=name, connectors=tuple(replace(c, card=name) for c in card.connectors))
            for card, name in zip(cards, ("card17", "card2"), strict=True)
        )
        after = collect(tuple(reversed(renamed)))
        self.assertEqual(
            {d.stable_id: d.owning_gpu_stable_id for d in before.displays},
            {d.stable_id: d.owning_gpu_stable_id for d in after.displays},
        )

    def test_missing_or_ambiguous_owner_is_unknown(self):
        internal, external = inventory()
        cases = {
            "connector_parent_mismatch": (replace(internal, connectors=(replace(internal.connectors[0], card=external.name),)), external),
            "missing_pci_identity": (replace(internal, pci_bdf=""), external),
            "unknown_gpu_role": (replace(internal, boot_vga=False), external),
            "missing_gpu_identity": (replace(internal, vendor=""), external),
            "duplicate_card_name": (internal, replace(external, name=internal.name)),
            "duplicate_pci_identity": (internal, replace(external, pci_bdf=internal.pci_bdf)),
            "contradictory_internal_roles": (internal, replace(external, boot_vga=True)),
            "duplicate_stable_identity": (internal, replace(external, boot_vga=True, device="0xffff")),
            "duplicate_connector": (replace(internal, connectors=internal.connectors * 2), external),
        }
        for reason, cards in cases.items():
            with self.subTest(reason=reason):
                display = collect(cards).displays[0]
                self.assertEqual(display.owning_gpu_stable_id, "")
                self.assertEqual(display.owning_gpu_confidence, Confidence.UNKNOWN)

    def test_unverified_external_profile_never_publishes_an_owner(self):
        internal, external = inventory()
        snapshot = collect((internal, replace(external, device="0xffff")))
        self.assertEqual(snapshot.displays[-1].owning_gpu_stable_id, "")
        self.assertEqual(snapshot.displays[-1].owning_gpu_confidence, Confidence.UNKNOWN)

    def test_private_round_trip_and_legacy_defaults(self):
        snapshot = collect(inventory())
        value = snapshot_to_dict(snapshot)
        self.assertEqual(snapshot_from_dict(value), snapshot)
        for display in value["displays"]:
            display.pop("owning_gpu_stable_id")
            display.pop("owning_gpu_confidence")
        for display in snapshot_from_dict(value).displays:
            self.assertEqual(display.owning_gpu_stable_id, "")
            self.assertEqual(display.owning_gpu_confidence, Confidence.UNKNOWN)

    def test_public_payload_does_not_expose_owner_identity(self):
        snapshot = collect(inventory())
        private = "private-owner-sentinel"
        snapshot = replace(snapshot, displays=tuple(
            replace(d, owning_gpu_stable_id=private) for d in snapshot.displays
        ))
        public = report_to_public_dict(SnapshotReport(snapshot, infer_operating_mode(snapshot)))
        self.assertNotIn(private, json.dumps(public))
        self.assertNotIn("owning_gpu_stable_id", json.dumps(public))
        self.assertEqual(public["snapshot"]["displays"][0]["owning_gpu_confidence"], "verified")

    def test_owner_change_invalidates_transition_observation(self):
        before = collect(inventory())
        after = replace(before, displays=tuple(
            replace(d, owning_gpu_stable_id="internal-gpu") for d in before.displays
        ))
        self.assertNotEqual(
            versioned_snapshot_observation(before).generation,
            versioned_snapshot_observation(after).generation,
        )


if __name__ == "__main__":
    unittest.main()
