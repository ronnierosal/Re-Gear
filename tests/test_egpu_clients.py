from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from hdm.adapters.steamos.egpu_clients import EgpuClientDiscovery  # noqa: E402
from hdm.domain.client_policy import classify_egpu_client  # noqa: E402
from hdm.domain.models import EgpuClientKind, EgpuResourceKind  # noqa: E402


def write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def process_stat(pid: int, name: str, start_time: int) -> str:
    return f"{pid} ({name}) S " + " ".join(["0"] * 18 + [str(start_time)])


def add_process(
    proc_root: Path,
    pid: int,
    name: str,
    cgroup: str,
    targets: tuple[str, ...],
    start_time: int,
) -> None:
    process = proc_root / str(pid)
    write(process / "comm", name + "\n")
    write(process / "stat", process_stat(pid, name, start_time))
    write(process / "cgroup", cgroup)
    write(process / "maps", "")
    (process / "fd").mkdir(exist_ok=True)
    for index, target in enumerate(targets):
        write(process / "fd" / str(index), target)


class EgpuClientPolicyTests(unittest.TestCase):
    def test_classifies_game_and_protected_processes_as_not_close_eligible(self):
        game = classify_egpu_client(
            pid=10,
            name="my-game",
            uid=1000,
            session_uid=1000,
            gamescope_pid=20,
            in_game_scope=True,
        )
        steam = classify_egpu_client(
            pid=11,
            name="steam",
            uid=1000,
            session_uid=1000,
            gamescope_pid=20,
            in_game_scope=False,
        )

        self.assertEqual(game.kind, EgpuClientKind.GAME)
        self.assertFalse(game.close_eligible)
        self.assertEqual(steam.kind, EgpuClientKind.PROTECTED)
        self.assertFalse(steam.close_eligible)

    def test_only_same_session_ordinary_user_process_is_close_eligible(self):
        user = classify_egpu_client(
            pid=30,
            name="blender",
            uid=1000,
            session_uid=1000,
            gamescope_pid=20,
            in_game_scope=False,
        )
        other = classify_egpu_client(
            pid=31,
            name="worker",
            uid=1001,
            session_uid=1000,
            gamescope_pid=20,
            in_game_scope=False,
        )

        self.assertEqual(user.kind, EgpuClientKind.USER)
        self.assertTrue(user.close_eligible)
        self.assertEqual(other.kind, EgpuClientKind.SYSTEM)
        self.assertFalse(other.close_eligible)


class EgpuClientDiscoveryTests(unittest.TestCase):
    GPU_BDF = "0000:08:00.0"
    AUDIO_BDF = "0000:08:00.1"
    ROOT_BDF = "0000:04:00.0"
    XHCI_BDF = "0000:09:00.0"

    def make_discovery(
        self,
        root: Path,
        *,
        block_device_resolver=None,
        fd_target_reader=None,
        descriptor_reader=None,
    ) -> EgpuClientDiscovery:
        pci = root / "pci"
        pci_path = lambda bdf: pci / bdf.replace(":", "_")
        (pci_path(self.GPU_BDF) / "drm" / "card7").mkdir(parents=True)
        (pci_path(self.GPU_BDF) / "drm" / "renderD131").mkdir()
        (pci_path(self.AUDIO_BDF) / "sound" / "card2").mkdir(parents=True)
        sound = root / "dev" / "snd"
        write(sound / "controlC2", "")
        write(sound / "pcmC2D3p", "")
        block = root / "block"
        block.mkdir()
        proc = root / "proc"
        proc.mkdir()
        write(proc / "self" / "mountinfo", "")
        write(proc / "swaps", "Filename Type Size Used Priority\n")
        return EgpuClientDiscovery(
            pci_root=pci,
            proc_root=proc,
            dri_root=Path("/dev/dri"),
            sound_root=sound,
            block_root=block,
            fd_target_reader=fd_target_reader or (
                lambda path: path.read_text(encoding="utf-8")
            ),
            uid_reader=lambda path: 1000,
            pci_path_resolver=pci_path,
            block_device_resolver=block_device_resolver,
            descriptor_reader=descriptor_reader,
        )

    def scan(self, discovery: EgpuClientDiscovery):
        return discovery.scan(
            gpu_bdf=self.GPU_BDF,
            audio_bdf=self.AUDIO_BDF,
            root_bdf=self.ROOT_BDF,
            xhci_bdf=self.XHCI_BDF,
            egpu_stable_id="gpd-g1:fixture",
            gamescope_pid=202,
            session_uid=1000,
        )

    def test_matches_only_exact_egpu_nodes_and_classifies_clients(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            discovery = self.make_discovery(root)
            proc = root / "proc"
            add_process(
                proc,
                101,
                "Space Game",
                "0::/app.slice/app-steam-app1234-abc.scope\n",
                ("/dev/dri/renderD131", "/dev/dri/card0"),
                500,
            )
            add_process(
                proc,
                202,
                "gamescope",
                "0::/gamescope-session.scope\n",
                ("/dev/dri/card7",),
                600,
            )
            add_process(
                proc,
                303,
                "editor\nwith-control",
                "0::/app.slice/editor.scope\n",
                (str(root / "dev" / "snd" / "pcmC2D3p"),),
                700,
            )
            add_process(
                proc,
                404,
                "internal-only",
                "0::/app.slice/other.scope\n",
                ("/dev/dri/renderD128",),
                800,
            )

            result = self.scan(discovery)

            self.assertTrue(result.complete)
            self.assertEqual([client.pid for client in result.clients], [101, 202, 303])
            self.assertTrue(all(client.process_start_time for client in result.clients))
            by_pid = {client.pid: client for client in result.clients}
            self.assertEqual(by_pid[101].kind, EgpuClientKind.GAME)
            self.assertEqual(by_pid[202].kind, EgpuClientKind.PROTECTED)
            self.assertEqual(by_pid[303].kind, EgpuClientKind.USER)
            self.assertEqual(by_pid[303].name, "editorwith-control")
            self.assertEqual(by_pid[303].resources, (EgpuResourceKind.AUDIO_PCM,))
            self.assertNotIn("renderD131", repr(result.clients))

    def test_mapping_without_open_descriptor_is_still_a_protected_client(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            discovery = self.make_discovery(root)
            add_process(root / "proc", 202, "gamescope", "0::/session\n", (), 600)
            write(root / "proc" / "202" / "maps",
                  "1000-2000 rw-s 00000000 00:01 1 /dev/dri/renderD131\n"
                  "2000-3000 rw-s 00000000 00:01 1 /dev/dri/renderD131\n")
            result = self.scan(discovery)
            self.assertTrue(result.complete)
            self.assertEqual(len(result.clients), 1)
            self.assertEqual(result.clients[0].resources, (EgpuResourceKind.DRM_RENDER,))
            self.assertFalse(result.clients[0].close_eligible)

    def test_missing_or_malformed_mappings_block_empty_scan(self):
        for contents in (None, "invalid\n", "x" * 8193):
            with self.subTest(contents=contents), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                discovery = self.make_discovery(root)
                add_process(root / "proc", 202, "gamescope", "0::/session\n", (), 600)
                maps = root / "proc" / "202" / "maps"
                if contents is None:
                    maps.unlink()
                else:
                    write(maps, contents)
                result = self.scan(discovery)
                self.assertFalse(result.complete)
                self.assertEqual(result.clients, ())

    def test_unreadable_mappings_preserve_known_descriptor_client(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            discovery = self.make_discovery(root)
            add_process(root / "proc", 202, "gamescope", "0::/session\n",
                        ("/dev/dri/renderD131",), 600)
            maps = root / "proc" / "202" / "maps"
            maps.unlink()
            maps.mkdir()
            result = self.scan(discovery)
            self.assertFalse(result.complete)
            self.assertEqual(len(result.clients), 1)
            self.assertFalse(result.clients[0].close_eligible)

    def test_process_instance_id_changes_with_start_time(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            discovery = self.make_discovery(root)
            proc = root / "proc"
            add_process(
                proc,
                101,
                "client",
                "0::/app.slice/client.scope\n",
                ("/dev/dri/renderD131",),
                500,
            )
            first = self.scan(discovery).clients[0].instance_id
            write(proc / "101" / "stat", process_stat(101, "client", 501))
            second = self.scan(discovery).clients[0].instance_id

            self.assertNotEqual(first, second)
            self.assertNotIn("500", first)

    def test_exact_g1_storage_mount_blocks_readiness(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            discovery = self.make_discovery(
                root,
                block_device_resolver=lambda entry: PurePosixPath(
                    f"/sys/devices/pci/{self.XHCI_BDF}/usb/block/{entry.name}"
                ),
            )
            write(root / "block" / "sdz1" / "dev", "8:17\n")
            write(
                root / "proc" / "self" / "mountinfo",
                "77 55 8:17 / /run/media/deck/drive rw - ext4 /dev/sdz1 rw\n",
            )

            result = self.scan(discovery)

            self.assertTrue(result.complete)
            self.assertEqual(result.storage_devices, 1)
            self.assertTrue(result.storage_in_use)

    def test_unreadable_live_process_descriptor_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            def unreadable(_path):
                raise PermissionError("fixture")

            discovery = self.make_discovery(root, descriptor_reader=unreadable)
            add_process(
                root / "proc",
                999,
                "unknown-client",
                "0::/app.slice/unknown.scope\n",
                ("/dev/dri/renderD131",),
                900,
            )

            result = self.scan(discovery)

            self.assertFalse(result.complete)
            self.assertIn("could not be inspected", result.error)
            self.assertEqual(result.clients, ())


if __name__ == "__main__":
    unittest.main()
