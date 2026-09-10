from __future__ import annotations

import dataclasses
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.adapters.drm_engine_activity import (  # noqa: E402
    ProcfsDrmEngineCounterAdapter,
)
from regear.adapters.steamos.drm import DrmCardRecord  # noqa: E402
from regear.adapters.steamos.game_render_binding import (  # noqa: E402
    AllyInternalDrmRenderBindingResolver,
    GpdG1DrmRenderBindingResolver,
)
from regear.adapters.steamos.host import HostRecord  # noqa: E402
from regear.adapters.steamos.pci import (  # noqa: E402
    PciDeviceRecord,
    Usb4DeviceRecord,
)
from regear.application.game_render_activity import (  # noqa: E402
    GameRenderActivityComparisonService,
    GameRenderActivityEvidenceService,
)
from regear.domain.game_render_activity import (  # noqa: E402
    DrmEngineClientCounters,
    DrmEngineCounterSample,
    DrmRenderBinding,
    GameRenderActivityStatus,
)
from regear.domain.game_runtime import (  # noqa: E402
    ActiveGameRuntimeObservation,
    GameProcessInstance,
    GameRuntimeKind,
)
from regear.domain.game_session import ActiveGameIdentity  # noqa: E402
from regear.domain.models import GameState, GpuRole  # noqa: E402
from regear.domain.serialization import snapshot_from_dict  # noqa: E402
from regear.ports.transition import VersionedObservation  # noqa: E402


FIXTURES = ROOT / "tests" / "fixtures"
EGPU_ID = "gpd-g1:0123456789abcdef"
BINDING = DrmRenderBinding(EGPU_ID, "0000:08:00.0", "/dev/dri/renderD131")
INTERNAL_BINDING = DrmRenderBinding(
    "internal-gpu", "0000:01:00.0", "/dev/dri/renderD128"
)
IDENTITY = ActiveGameIdentity("1234", ("app-steam-app1234-test.scope",))
PROCESS = GameProcessInstance(101, 500, 1, "game", False)


def stat_line(start: int) -> str:
    fields = ["S", "1", *("0" for _ in range(48))]
    fields[19] = str(start)
    return f"101 (game process) {' '.join(fields)}\n"


def fdinfo(*, gfx: int, compute: int = 0, pdev: str = "0000:08:00.0") -> str:
    return (
        "pos:\t0\n"
        "drm-driver:\tamdgpu\n"
        f"drm-pdev:\t{pdev}\n"
        "drm-client-id:\t7\n"
        f"drm-engine-gfx:\t{gfx} ns\n"
        f"drm-engine-compute:\t{compute} ns\n"
    )


class DrmEngineAdapterTests(unittest.TestCase):
    def fixture(self, root: Path, *, info: str, target="/dev/dri/renderD131"):
        process = root / "101"
        (process / "fd").mkdir(parents=True)
        (process / "fdinfo").mkdir()
        (process / "stat").write_text(stat_line(500), encoding="utf-8")
        descriptor = process / "fd" / "5"
        descriptor.write_text("", encoding="utf-8")
        (process / "fdinfo" / "5").write_text(info, encoding="utf-8")
        return ProcfsDrmEngineCounterAdapter(
            proc_root=root,
            fd_target_reader=lambda path: target,
        )

    def test_exact_fdinfo_returns_private_engine_counters(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter = self.fixture(Path(directory), info=fdinfo(gfx=100, compute=5))
            result = adapter.sample((PROCESS,), BINDING)

        self.assertTrue(result.complete)
        self.assertEqual(len(result.clients), 1)
        self.assertEqual(result.clients[0].identity, (101, 500, 7))
        self.assertEqual(
            dict(result.clients[0].counters_ns), {"compute": 5, "gfx": 100}
        )
        self.assertNotIn(BINDING.render_node, repr(result))

    def test_wrong_pci_identity_and_missing_counter_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter = self.fixture(
                Path(directory), info=fdinfo(gfx=100, pdev="0000:09:00.0")
            )
            wrong = adapter.sample((PROCESS,), BINDING)
        with tempfile.TemporaryDirectory() as directory:
            adapter = self.fixture(
                Path(directory),
                info=(
                    "drm-driver: amdgpu\n"
                    "drm-pdev: 0000:08:00.0\n"
                    "drm-client-id: 7\n"
                ),
            )
            incomplete = adapter.sample((PROCESS,), BINDING)

        self.assertEqual(wrong.error_code, "render_activity.pci_identity_changed")
        self.assertEqual(incomplete.error_code, "render_activity.fdinfo_incomplete")

    def test_non_target_descriptor_is_complete_no_client(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter = self.fixture(
                Path(directory),
                info=fdinfo(gfx=100),
                target="/dev/dri/renderD128",
            )
            result = adapter.sample((PROCESS,), BINDING)

        self.assertTrue(result.complete)
        self.assertEqual(result.clients, ())

    def test_pid_reuse_during_scan_is_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = self.fixture(root, info=fdinfo(gfx=100))

            def change_identity(fd_directory):
                (root / "101" / "stat").write_text(
                    stat_line(501), encoding="utf-8"
                )
                return tuple(fd_directory.iterdir())

            adapter = ProcfsDrmEngineCounterAdapter(
                proc_root=root,
                descriptor_reader=change_identity,
                fd_target_reader=lambda path: "/dev/dri/renderD131",
            )
            result = adapter.sample((PROCESS,), BINDING)

        self.assertFalse(result.complete)
        self.assertEqual(
            result.error_code, "render_activity.process_identity_changed"
        )


def g1_pci_records():
    root = "0000:04:00.0"
    downstream = "0000:05:01.0"
    ancestry = ("0000:00:03.1", root)
    return (
        PciDeviceRecord(
            root,
            "0x8086",
            "0x15ef",
            "0x060400",
            "pcieport",
            ("0000:00:03.1", root),
            True,
        ),
        PciDeviceRecord(
            downstream,
            "0x8086",
            "0x15ef",
            "0x060400",
            "pcieport",
            ("0000:00:03.1", root, downstream),
            True,
        ),
        PciDeviceRecord(
            "0000:08:00.0",
            "0x1002",
            "0x7480",
            "0x030000",
            "amdgpu",
            (*ancestry, downstream, "0000:06:00.0", "0000:07:00.0", "0000:08:00.0"),
        ),
        PciDeviceRecord(
            "0000:08:00.1",
            "0x1002",
            "0xab30",
            "0x040300",
            "snd_hda_intel",
            (*ancestry, downstream, "0000:06:00.0", "0000:07:00.0", "0000:08:00.1"),
        ),
        PciDeviceRecord(
            "0000:09:00.0",
            "0x8086",
            "0x15f0",
            "0x0c0330",
            "xhci_hcd",
            (*ancestry, "0000:09:00.0"),
        ),
    )


class FakeDrm:
    def __init__(self, cards):
        self.cards = cards

    def scan(self):
        return self.cards


class FakePciUsb4:
    def __init__(self, *, usb_hash="0123456789abcdef" + "0" * 48):
        self.usb_hash = usb_hash

    def scan_pci(self):
        return g1_pci_records()

    def scan_usb4(self):
        return (
            Usb4DeviceRecord("0-2", "Intel", "Tapex Creek", True, self.usb_hash),
        )


class FakeHost:
    def __init__(self, value=None):
        self.value = value or HostRecord(
            "ASUSTeK COMPUTER INC.",
            "ROG Ally X RC72LA",
            "RC72LA",
        )

    def scan(self):
        return self.value


class DrmRenderBindingResolverTests(unittest.TestCase):
    def test_exact_fresh_topology_resolves_one_private_render_node(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pci = root / "pci"
            (pci / "0000_08_00.0" / "drm" / "renderD131").mkdir(parents=True)
            resolver = GpdG1DrmRenderBindingResolver(
                drm=FakeDrm(
                    (
                        DrmCardRecord(
                            "card9",
                            "0000:08:00.0",
                            "0x1002",
                            "0x7480",
                            False,
                            "amdgpu",
                        ),
                    )
                ),
                pci_usb4=FakePciUsb4(),
                pci_path_resolver=lambda bdf: pci / bdf.replace(":", "_"),
                dri_root=Path("/dev/dri"),
                node_validator=lambda path: path.name == "renderD131",
            )
            result = resolver.resolve(snapshot())

        self.assertEqual(result, BINDING)

    def test_ambiguous_node_or_changed_usb_identity_fails_closed(self):
        card = DrmCardRecord(
            "card9",
            "0000:08:00.0",
            "0x1002",
            "0x7480",
            False,
            "amdgpu",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pci = root / "pci"
            drm = pci / "0000_08_00.0" / "drm"
            (drm / "renderD131").mkdir(parents=True)
            (drm / "renderD132").mkdir()
            kwargs = dict(
                drm=FakeDrm((card,)),
                pci_path_resolver=lambda bdf: pci / bdf.replace(":", "_"),
                node_validator=lambda path: True,
            )
            ambiguous = GpdG1DrmRenderBindingResolver(
                pci_usb4=FakePciUsb4(), **kwargs
            ).resolve(snapshot())
            changed = GpdG1DrmRenderBindingResolver(
                pci_usb4=FakePciUsb4(usb_hash="f" * 64), **kwargs
            ).resolve(snapshot())

        self.assertIsNone(ambiguous)
        self.assertIsNone(changed)

    def test_exact_ally_boot_gpu_resolves_one_private_render_node(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pci = root / "pci"
            (pci / "0000_01_00.0" / "drm" / "renderD128").mkdir(parents=True)
            resolver = AllyInternalDrmRenderBindingResolver(
                drm=FakeDrm(
                    (
                        DrmCardRecord(
                            "card0",
                            "0000:01:00.0",
                            "0x1002",
                            "0x0000",
                            True,
                            "amdgpu",
                        ),
                    )
                ),
                host=FakeHost(),
                pci_path_resolver=lambda bdf: pci / bdf.replace(":", "_"),
                dri_root=Path("/dev/dri"),
                node_validator=lambda path: path.name == "renderD128",
            )
            result = resolver.resolve(snapshot())

        self.assertEqual(
            result,
            DrmRenderBinding(
                "internal-gpu", "0000:01:00.0", "/dev/dri/renderD128"
            ),
        )

    def test_internal_binding_rejects_unknown_host_and_ambiguous_boot_gpu(self):
        card = DrmCardRecord(
            "card0",
            "0000:01:00.0",
            "0x1002",
            "0x0000",
            True,
            "amdgpu",
        )
        unknown_host = AllyInternalDrmRenderBindingResolver(
            drm=FakeDrm((card,)),
            host=FakeHost(HostRecord("Other", "Other", "Other")),
            node_validator=lambda path: True,
        ).resolve(snapshot())
        ambiguous = AllyInternalDrmRenderBindingResolver(
            drm=FakeDrm((card, dataclasses.replace(card, name="card1"))),
            host=FakeHost(),
            node_validator=lambda path: True,
        ).resolve(snapshot())

        self.assertIsNone(unknown_host)
        self.assertIsNone(ambiguous)


def runtime(*, generation="a" * 64, sample="b" * 64):
    return ActiveGameRuntimeObservation(
        "1234",
        IDENTITY.scopes,
        (PROCESS,),
        GameRuntimeKind.NATIVE,
        generation,
        sample,
        True,
    )


def snapshot():
    value = json.loads((FIXTURES / "tv-docked.json").read_text(encoding="utf-8"))
    return dataclasses.replace(
        snapshot_from_dict(value), game_state=GameState.RUNNING
    )


def counter(value: int):
    return DrmEngineCounterSample(
        (DrmEngineClientCounters(101, 500, 7, (("gfx", value),)),),
        True,
    )


class RuntimePort:
    def __init__(self, *values):
        self.values = list(values)

    def observe(self, identity, *, user_uid):
        return self.values.pop(0)


class SnapshotPort:
    def __init__(self, value):
        self.value = value

    def observe(self):
        return VersionedObservation("snapshot", self.value, "sample")


class SnapshotSequencePort:
    def __init__(self, *values):
        self.values = list(values)

    def observe(self):
        return self.values.pop(0)


class BindingPort:
    def __init__(self, value=BINDING):
        self.value = value

    def resolve(self, value):
        return self.value


class CounterPort:
    def __init__(self, *values):
        self.values = list(values)

    def sample(self, processes, binding):
        return self.values.pop(0)


class Waiter:
    def __init__(self):
        self.waits = []

    def wait_ms(self, value):
        self.waits.append(value)


def service(
    first,
    second,
    *,
    before=None,
    after=None,
    binding=BINDING,
    target_role=GpuRole.EXTERNAL,
):
    waiter = Waiter()
    value = GameRenderActivityEvidenceService(
        runtime=RuntimePort(
            before or runtime(sample="b" * 64),
            after or runtime(sample="c" * 64),
        ),
        snapshots=SnapshotPort(snapshot()),
        bindings=BindingPort(binding),
        counters=CounterPort(first, second),
        waiter=waiter,
        target_role=target_role,
        sample_interval_ms=250,
    )
    return value, waiter


class GameRenderActivityServiceTests(unittest.TestCase):
    def test_increasing_counter_proves_bounded_active_rendering(self):
        value, waiter = service(counter(100), counter(125))
        result = value.observe(IDENTITY, user_uid=1000)

        self.assertEqual(result.status, GameRenderActivityStatus.ACTIVE)
        self.assertEqual(result.active_engine_count, 1)
        self.assertTrue(result.proves_active_rendering)
        self.assertEqual(waiter.waits, [250])

    def test_unchanged_counter_and_no_client_are_not_active_proof(self):
        idle, _ = service(counter(100), counter(100))
        idle_result = idle.observe(IDENTITY, user_uid=1000)
        empty = DrmEngineCounterSample((), True)
        absent, _ = service(empty, empty)
        absent_result = absent.observe(IDENTITY, user_uid=1000)

        self.assertEqual(idle_result.status, GameRenderActivityStatus.IDLE_WINDOW)
        self.assertEqual(absent_result.status, GameRenderActivityStatus.NO_CLIENT)
        self.assertFalse(idle_result.proves_active_rendering)
        self.assertFalse(absent_result.proves_active_rendering)

    def test_client_change_counter_decrease_and_runtime_change_are_unknown(self):
        empty = DrmEngineCounterSample((), True)
        changed_clients, _ = service(counter(100), empty)
        decreased, _ = service(counter(100), counter(90))
        changed_runtime, _ = service(
            counter(100),
            counter(125),
            after=runtime(generation="d" * 64, sample="c" * 64),
        )

        results = (
            changed_clients.observe(IDENTITY, user_uid=1000),
            decreased.observe(IDENTITY, user_uid=1000),
            changed_runtime.observe(IDENTITY, user_uid=1000),
        )
        self.assertEqual(
            [result.reason_code for result in results],
            [
                "render_activity.client_set_changed",
                "render_activity.counter_decreased",
                "render_activity.runtime_changed",
            ],
        )
        self.assertTrue(
            all(result.status is GameRenderActivityStatus.UNKNOWN for result in results)
        )

    def test_binding_identity_must_match_exact_profile(self):
        other = DrmRenderBinding(
            "other-gpu", "0000:08:00.0", "/dev/dri/renderD131"
        )
        value, _ = service(counter(100), counter(125), binding=other)
        result = value.observe(IDENTITY, user_uid=1000)

        self.assertEqual(result.status, GameRenderActivityStatus.UNKNOWN)
        self.assertEqual(result.reason_code, "render_activity.binding_unverified")

    def test_internal_target_accepts_only_exact_internal_binding(self):
        internal = DrmRenderBinding(
            "internal-gpu", "0000:01:00.0", "/dev/dri/renderD128"
        )
        active, _ = service(
            counter(100),
            counter(125),
            binding=internal,
            target_role=GpuRole.INTERNAL,
        )
        wrong, _ = service(
            counter(100),
            counter(125),
            binding=BINDING,
            target_role=GpuRole.INTERNAL,
        )

        self.assertEqual(
            active.observe(IDENTITY, user_uid=1000).status,
            GameRenderActivityStatus.ACTIVE,
        )
        self.assertEqual(
            wrong.observe(IDENTITY, user_uid=1000).reason_code,
            "render_activity.binding_unverified",
        )


class GameRenderActivityComparisonServiceTests(unittest.TestCase):
    def comparison(
        self,
        *,
        snapshots=None,
        external_binding=BINDING,
        counters=None,
    ):
        waiter = Waiter()
        snapshot_values = snapshots or (
            VersionedObservation("snapshot", snapshot(), "sample-1"),
            VersionedObservation("snapshot", snapshot(), "sample-2"),
        )
        value = GameRenderActivityComparisonService(
            runtime=RuntimePort(
                runtime(sample="b" * 64),
                runtime(sample="c" * 64),
            ),
            snapshots=SnapshotSequencePort(*snapshot_values),
            internal_binding=BindingPort(INTERNAL_BINDING),
            external_binding=BindingPort(external_binding),
            counters=CounterPort(
                *(counters or (counter(100), counter(10), counter(125), counter(10)))
            ),
            waiter=waiter,
            sample_interval_ms=250,
        )
        return value, waiter

    def test_both_targets_share_one_runtime_snapshot_and_wait_window(self):
        value, waiter = self.comparison()

        result = value.observe(IDENTITY, user_uid=1000)

        self.assertEqual(result.internal.status, GameRenderActivityStatus.ACTIVE)
        self.assertEqual(result.external.status, GameRenderActivityStatus.IDLE_WINDOW)
        self.assertEqual(result.internal.placement, result.external.placement)
        self.assertEqual(waiter.waits, [250])

    def test_snapshot_change_discards_both_target_results(self):
        changed = dataclasses.replace(snapshot(), game_state=GameState.IDLE)
        value, _waiter = self.comparison(
            snapshots=(
                VersionedObservation("snapshot", snapshot(), "sample-1"),
                VersionedObservation("changed", changed, "sample-2"),
            )
        )

        result = value.observe(IDENTITY, user_uid=1000)

        self.assertEqual(result.internal.status, GameRenderActivityStatus.UNKNOWN)
        self.assertEqual(result.external.status, GameRenderActivityStatus.UNKNOWN)
        self.assertEqual(result.internal.reason_code, "render_activity.snapshot_changed")

    def test_missing_external_binding_keeps_internal_evidence_non_comparative(self):
        value, waiter = self.comparison(
            external_binding=None,
            counters=(counter(100), counter(125)),
        )

        result = value.observe(IDENTITY, user_uid=1000)

        self.assertEqual(result.internal.status, GameRenderActivityStatus.ACTIVE)
        self.assertEqual(result.external.status, GameRenderActivityStatus.UNKNOWN)
        self.assertEqual(result.external.reason_code, "render_activity.binding_unverified")
        self.assertEqual(waiter.waits, [250])


if __name__ == "__main__":
    unittest.main()
