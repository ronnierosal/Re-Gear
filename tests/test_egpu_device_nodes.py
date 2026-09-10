from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.adapters.steamos.egpu_device_nodes import (  # noqa: E402
    SteamOsEgpuDeviceNodeDiscovery,
)
from regear.domain.egpu_device_policy import (  # noqa: E402
    DevicePolicyState,
    compose_egpu_device_policy,
)
from regear.domain.models import EgpuResourceKind  # noqa: E402


GPU_BDF = "0000:08:00.0"
AUDIO_BDF = "0000:08:00.1"

#: The layout measured on an Ally X with a GPD G1 attached.
MEASURED = {
    "dri": {
        f"pci-{GPU_BDF}-card": ("card1", 226, 1),
        f"pci-{GPU_BDF}-render": ("renderD129", 226, 129),
    },
    "snd_control": ("controlC2", 116, 15),
    "snd_siblings": {
        "hwC2D0": (116, 14),
        "pcmC2D3p": (116, 10),
        "pcmC2D7p": (116, 11),
        "pcmC2D8p": (116, 12),
        "pcmC2D9p": (116, 13),
    },
    # Nodes of the internal GPU's audio functions, which must not be collected.
    "snd_other": {"controlC0": (116, 5), "hwC0D0": (116, 4), "pcmC1D0p": (116, 6)},
}


class FakeTree:
    """Build a /dev-shaped tree of plain files with faked device numbers."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.numbers: dict[Path, tuple[int, int]] = {}
        self.links: dict[Path, Path] = {}
        self.dri = root / "dri"
        self.dri_by_path = self.dri / "by-path"
        self.snd = root / "snd"
        self.snd_by_path = self.snd / "by-path"
        for path in (self.dri_by_path, self.snd_by_path):
            path.mkdir(parents=True, exist_ok=True)

    def node(self, directory: Path, name: str, major: int, minor: int) -> Path:
        path = directory / name
        path.write_text("", encoding="utf-8")
        self.numbers[path.resolve()] = (major, minor)
        return path

    def link(self, directory: Path, name: str, target: Path) -> None:
        """Record a by-path mapping without needing real symlink privilege."""
        self.links[(directory / name).resolve()] = target.resolve()

    def resolve_link(self, path: Path) -> Path:
        target = self.links.get(Path(path).resolve())
        if target is None:
            raise OSError("no such link")
        return target

    def device_numbers(self, path: Path):
        """Stand in for os.major/os.minor, which are POSIX-only."""
        try:
            return self.numbers.get(Path(path).resolve())
        except OSError:
            return None


def build(tree: FakeTree, *, with_audio: bool = True, with_drm: bool = True) -> None:
    if with_drm:
        for link_name, (node_name, major, minor) in MEASURED["dri"].items():
            node = tree.node(tree.dri, node_name, major, minor)
            tree.link(tree.dri_by_path, link_name, node)
    if with_audio:
        name, major, minor = MEASURED["snd_control"]
        control = tree.node(tree.snd, name, major, minor)
        tree.link(tree.snd_by_path, f"pci-{AUDIO_BDF}", control)
        for sibling, (smajor, sminor) in MEASURED["snd_siblings"].items():
            tree.node(tree.snd, sibling, smajor, sminor)
    for other, (omajor, ominor) in MEASURED["snd_other"].items():
        tree.node(tree.snd, other, omajor, ominor)


class DiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.tree = FakeTree(Path(directory.name))

    def discovery(self) -> SteamOsEgpuDeviceNodeDiscovery:
        return SteamOsEgpuDeviceNodeDiscovery(
            dri_by_path=self.tree.dri_by_path,
            snd_by_path=self.tree.snd_by_path,
            snd_root=self.tree.snd,
            device_numbers=self.tree.device_numbers,
            resolve_link=self.tree.resolve_link,
        )

    def scan(self):
        return self.discovery().scan(gpu_bdf=GPU_BDF, audio_bdf=AUDIO_BDF)

    def test_measured_layout_yields_eight_nodes(self) -> None:
        build(self.tree)
        scan = self.scan()
        self.assertTrue(scan.complete, scan.error)
        self.assertEqual(len(scan.nodes), 8)

    def test_measured_layout_matches_the_recorded_device_numbers(self) -> None:
        build(self.tree)
        numbers = {node.number for node in self.scan().nodes}
        self.assertEqual(
            numbers,
            {(226, 1), (226, 129), (116, 15), (116, 14), (116, 10), (116, 11),
             (116, 12), (116, 13)},
        )

    def test_other_cards_audio_nodes_are_not_collected(self) -> None:
        build(self.tree)
        numbers = {node.number for node in self.scan().nodes}
        for excluded in MEASURED["snd_other"].values():
            self.assertNotIn(excluded, numbers)

    def test_both_required_kinds_are_present(self) -> None:
        build(self.tree)
        kinds = {node.kind for node in self.scan().nodes}
        self.assertIn(EgpuResourceKind.DRM_RENDER, kinds)
        self.assertIn(EgpuResourceKind.AUDIO_CONTROL, kinds)

    def test_scan_feeds_a_composable_policy(self) -> None:
        build(self.tree)
        policy = compose_egpu_device_policy(self.scan().nodes)
        self.assertIs(policy.state, DevicePolicyState.COMPOSED)
        self.assertEqual(len(policy.devices), 8)

    def test_missing_audio_function_fails_closed(self) -> None:
        build(self.tree, with_audio=False)
        scan = self.scan()
        self.assertFalse(scan.complete)
        self.assertEqual(scan.error, "egpu_nodes.audio_unavailable")
        self.assertEqual(scan.nodes, ())

    def test_missing_drm_function_fails_closed(self) -> None:
        build(self.tree, with_drm=False)
        scan = self.scan()
        self.assertFalse(scan.complete)
        self.assertEqual(scan.error, "egpu_nodes.drm_unavailable")

    def test_invalid_identity_is_refused(self) -> None:
        build(self.tree)
        scan = self.discovery().scan(gpu_bdf="not-a-bdf", audio_bdf=AUDIO_BDF)
        self.assertFalse(scan.complete)
        self.assertEqual(scan.error, "egpu_nodes.identity_invalid")

    def test_identical_functions_are_refused(self) -> None:
        build(self.tree)
        scan = self.discovery().scan(gpu_bdf=GPU_BDF, audio_bdf=GPU_BDF)
        self.assertFalse(scan.complete)
        self.assertEqual(scan.error, "egpu_nodes.identity_ambiguous")

    def test_absent_device_tree_fails_closed(self) -> None:
        scan = self.scan()
        self.assertFalse(scan.complete)
        self.assertEqual(scan.nodes, ())


if __name__ == "__main__":
    unittest.main()


class PartialScanTests(unittest.TestCase):
    """A partial set still passes the policy's required-kind check, so the
    scan must fail closed rather than emit one. Reported by Codex on #101."""

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.tree = FakeTree(Path(directory.name))

    def discovery(self) -> SteamOsEgpuDeviceNodeDiscovery:
        return SteamOsEgpuDeviceNodeDiscovery(
            dri_by_path=self.tree.dri_by_path,
            snd_by_path=self.tree.snd_by_path,
            snd_root=self.tree.snd,
            device_numbers=self.tree.device_numbers,
            resolve_link=self.tree.resolve_link,
        )

    def scan(self):
        return self.discovery().scan(gpu_bdf=GPU_BDF, audio_bdf=AUDIO_BDF)

    def test_missing_card_link_fails_closed(self) -> None:
        """Render alone would compose a policy omitting the card node."""
        build(self.tree)
        del self.tree.links[(self.tree.dri_by_path / f"pci-{GPU_BDF}-card").resolve()]
        scan = self.scan()
        self.assertFalse(scan.complete)
        self.assertEqual(scan.error, "egpu_nodes.drm_incomplete")
        self.assertEqual(scan.nodes, ())

    def test_missing_render_link_fails_closed(self) -> None:
        build(self.tree)
        del self.tree.links[(self.tree.dri_by_path / f"pci-{GPU_BDF}-render").resolve()]
        scan = self.scan()
        self.assertFalse(scan.complete)
        self.assertEqual(scan.error, "egpu_nodes.drm_incomplete")

    def test_unreadable_drm_device_numbers_fail_closed(self) -> None:
        build(self.tree)
        card = self.tree.dri / MEASURED["dri"][f"pci-{GPU_BDF}-card"][0]
        del self.tree.numbers[card.resolve()]
        scan = self.scan()
        self.assertFalse(scan.complete)
        self.assertEqual(scan.error, "egpu_nodes.drm_incomplete")

    def test_unreadable_alsa_sibling_fails_closed(self) -> None:
        build(self.tree)
        sibling = self.tree.snd / "pcmC2D7p"
        del self.tree.numbers[sibling.resolve()]
        scan = self.scan()
        self.assertFalse(scan.complete)
        self.assertEqual(scan.error, "egpu_nodes.audio_incomplete")
        self.assertEqual(scan.nodes, ())

    def test_a_partial_set_would_have_passed_the_policy_check(self) -> None:
        """Why this matters: the policy alone cannot catch a missing card node."""
        from regear.domain.egpu_device_policy import compose_egpu_device_policy

        build(self.tree)
        full = self.scan().nodes
        without_card = tuple(
            node for node in full if node.kind is not EgpuResourceKind.DRM_CARD
        )
        policy = compose_egpu_device_policy(without_card)
        self.assertIs(policy.state, DevicePolicyState.COMPOSED)
        self.assertEqual(len(policy.devices), 7)
