from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from hdm.adapters.steamos.version_info import SteamOsVersionDiscovery  # noqa: E402
from hdm.application.support_bundle import (  # noqa: E402
    BoundedEventLog,
    SupportBundlePreviewStore,
    SupportBundleService,
    SupportBundleContext,
    WakeDiagnosticsSupportStatus,
    PeripheralSupportStatus,
)
from hdm.domain.control_plane import PlacementState, WorkflowState  # noqa: E402
from hdm.domain.game_compatibility import GameCompatibilityRecord  # noqa: E402
from hdm.domain.hardware_compatibility import HardwareCompatibilityRecord  # noqa: E402
from hdm.domain.transition_journal import (  # noqa: E402
    JournalEventKind,
    TransitionJournal,
    append_journal_entry,
)
from hdm.delivery.support_export import SupportBundleFileWriter  # noqa: E402


class IncrementingClock:
    def __init__(self):
        self.value = datetime(2026, 8, 31, tzinfo=timezone.utc)

    def __call__(self):
        current = self.value
        self.value += timedelta(seconds=1)
        return current


def adversarial_report() -> dict[str, object]:
    private = (
        "FixtureUser fixture-secret 192.0.2.185 /home/FixtureUser/private "
        "C:\\Users\\FixtureUser\\secret 0000:08:00.0 1002:7480 card17 "
        "renderD128 HDMI-A-9 1814797631546d0ba959013aee764ebb65e79cb2e"
    )
    return {
        "snapshot": {
            "schema_version": 3,
            "observed_at": "2026-08-31T00:00:00+00:00",
            "host_profile": "asus-rog-ally-x",
            "support_tier": "certified",
            "game_state": "idle",
            "gpus": [
                {
                    "stable_id": private,
                    "vendor_device": "1002:7480",
                    "role": "external",
                    "present": True,
                    "selected_for_render": False,
                    "confidence": "verified",
                }
            ],
            "displays": [
                {
                    "stable_id": private,
                    "connector": "HDMI-A-9",
                    "kind": "external",
                    "connected": True,
                    "active": False,
                    "edid_ready": True,
                    "confidence": "verified",
                }
            ],
            "gamescope": {
                "running": True,
                "pid": 1234,
                "output_order": ["HDMI-A-9"],
                "render_gpu_stable_id": private,
                "confidence": "verified",
            },
            "disconnect_readiness": {
                "applicable": True,
                "scan_complete": True,
                "ready": False,
                "clients": [
                    {
                        "instance_id": private,
                        "pid": 1234,
                        "name": private,
                        "kind": "user",
                        "resources": ["drm_render"],
                        "close_eligible": True,
                        "reason": private,
                        "process_start_time": "987654321",
                    }
                ],
                "storage_devices": 0,
                "storage_in_use": False,
                "error": private,
            },
            "sleep_guard": {
                "required": True,
                "active": True,
                "confidence": "verified",
                "reason": private,
                "error": "",
            },
            "blockers": [{"code": "fixture", "message": private}],
        },
        "inference": {"mode": "portable", "reasons": []},
        "diagnostics": {
            "schema_version": 1,
            "timings_ms": [{"stage": "snapshot_total", "duration_ms": 25.5}],
        },
    }


class BoundedEventLogTests(unittest.TestCase):
    def test_rotates_and_emits_structured_ephemeral_ids(self):
        clock = IncrementingClock()
        identifiers = iter(("id0001", "id0002", "id0003"))
        events = BoundedEventLog(
            max_events=2,
            clock=clock,
            correlation_id=lambda: next(identifiers),
        )
        for index in range(3):
            events.append(
                severity="info",
                code=f"snapshot.sample_{index}",
                component="discovery",
                stage="observe",
                details={"index": index},
            )

        rows = events.snapshot()

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].code, "snapshot.sample_1")
        self.assertEqual(rows[1].correlation_id, "id0003")


class SupportBundleTests(unittest.TestCase):
    def test_adversarial_private_values_and_raw_hardware_ids_are_absent(self):
        clock = IncrementingClock()
        events = BoundedEventLog(
            clock=clock,
            correlation_id=lambda: "event001",
        )
        events.append(
            severity="warning",
            code="fixture.private",
            component="support",
            stage="preview",
            details={
                "value": adversarial_report()["snapshot"]["blockers"][0]["message"],
                "pid": 9876,
                "command": "/usr/bin/private --secret",
                "stable_id": "private-stable-id",
            },
        )
        bundle = SupportBundleService(clock=clock).build(
            adversarial_report(),
            events.snapshot(),
            {
                "regear": "0.2.0",
                "decky": "fixture-secret",
                "steamos": "FixtureUser@192.0.2.185",
                "kernel": "6.11.11-valve",
            },
            sensitive_values=("FixtureUser", "fixture-secret"),
        )

        for forbidden in (
            "FixtureUser",
            "fixture-secret",
            "192.0.2.185",
            "/home/",
            "C:\\Users\\",
            "0000:08:00.0",
            "1002:7480",
            "card17",
            "renderD128",
            "HDMI-A-9",
            "1814797631546d0ba959013aee764ebb65e79cb2e",
        ):
            self.assertNotIn(forbidden, bundle.json_text)
        self.assertNotIn("stable_id", bundle.payload["snapshot"]["gpus"][0])
        self.assertNotIn("pid", bundle.payload["snapshot"]["gamescope"])
        self.assertNotIn(
            "process_start_time",
            bundle.payload["snapshot"]["disconnect_readiness"]["clients"][0],
        )
        self.assertNotIn("9876", bundle.json_text)
        self.assertNotIn("/usr/bin/private", bundle.json_text)
        self.assertNotIn("private-stable-id", bundle.json_text)
        self.assertTrue(bundle.payload["manifest"]["redacted"])
        self.assertLessEqual(bundle.size_bytes, 256 * 1024)

    def test_profile_check_uses_exact_runtime_status_not_one_host_id(self):
        report = adversarial_report()
        report["snapshot"]["host_profile"] = "synthetic-handheld-profile"
        report["diagnostics"]["hardware_profiles"] = {
            "host": {"status": "exact", "profile_id": "synthetic-handheld-profile"},
            "egpu": {"status": "absent", "profile_id": "unknown"},
            "capabilities": [],
        }

        bundle = SupportBundleService().build(report, (), {})

        check = next(
            row
            for row in bundle.payload["profile_checks"]
            if row["code"] == "host.profile_exact"
        )
        self.assertEqual(check["result"], "pass")

    def test_size_limit_drops_old_events_but_keeps_manifest_and_snapshot(self):
        clock = IncrementingClock()
        events = BoundedEventLog(max_events=128, clock=clock)
        for index in range(128):
            events.append(
                severity="info",
                code="fixture.large",
                component="support",
                stage="size_test",
                details={"index": index, "message": "x" * 1000},
            )

        bundle = SupportBundleService(max_bytes=8 * 1024, clock=clock).build(
            adversarial_report(), events.snapshot(), {}, sensitive_values=()
        )

        self.assertLess(bundle.event_count, 128)
        self.assertLessEqual(bundle.size_bytes, 8 * 1024)
        self.assertTrue(bundle.payload["manifest"]["events_truncated_for_size"])
        self.assertIn("snapshot", bundle.payload)

    def test_preview_token_is_single_use_and_expires(self):
        now = [10.0]
        tokens = iter(("preview_token_0001", "preview_token_0002"))
        bundle = SupportBundleService().build(adversarial_report(), (), {})
        store = SupportBundlePreviewStore(
            ttl_seconds=5,
            monotonic=lambda: now[0],
            token_factory=lambda: next(tokens),
        )

        first = store.issue(bundle)
        self.assertIs(store.consume(first.token), bundle)
        with self.assertRaisesRegex(ValueError, "expired or was already used"):
            store.consume(first.token)

        second = store.issue(bundle)
        now[0] = 15.0
        with self.assertRaisesRegex(ValueError, "expired or was already used"):
            store.consume(second.token)

    def test_preview_store_rejects_arbitrary_tokens(self):
        store = SupportBundlePreviewStore()
        with self.assertRaisesRegex(ValueError, "invalid"):
            store.consume("../../etc/passwd")

    def test_optional_transition_and_compatibility_context_is_strictly_reduced(self):
        journal = TransitionJournal("private-operation-id", "private-request-id")
        journal = append_journal_entry(
            journal,
            kind=JournalEventKind.REQUESTED,
            occurred_at="2026-08-31T12:00:00Z",
            workflow_state=WorkflowState.SLEEP_PENDING_DISCONNECT,
            placement=PlacementState.DOCKED_EGPU,
            code="sleep.requested",
        )
        game = GameCompatibilityRecord(
            catalog_id="private-game-record",
            title="Private Game Title",
            steam_app_id="1234",
            host_profile_id="asus-rog-ally-x",
            egpu_profile_id="gpd-g1-rx7600mxt-titan-ridge",
        )
        hardware = HardwareCompatibilityRecord(
            catalog_id="private-hardware-record",
            host_profile_id="asus-rog-ally-x",
            egpu_profile_id="gpd-g1-rx7600mxt-titan-ridge",
        )
        bundle = SupportBundleService().build(
            adversarial_report(),
            (),
            {},
            context=SupportBundleContext(
                transition_journals=(journal,),
                game_compatibility=(game,),
                hardware_compatibility=(hardware,),
            ),
        )

        self.assertEqual(bundle.payload["schema_version"], 2)
        self.assertEqual(
            bundle.payload["game_compatibility"][0]["steam_app_id"],
            "1234",
        )
        self.assertEqual(
            bundle.payload["transition_history"][0]["entries"][0]["code"],
            "sleep.requested",
        )
        for forbidden in (
            "private-operation-id",
            "private-request-id",
            "private-game-record",
            "Private Game Title",
            "private-hardware-record",
        ):
            self.assertNotIn(forbidden, bundle.json_text)

    def test_support_context_counts_are_bounded(self):
        record = GameCompatibilityRecord(
            catalog_id="game-record",
            title="Game",
            host_profile_id="host-profile",
            egpu_profile_id="egpu-profile",
        )
        with self.assertRaisesRegex(ValueError, "game compatibility"):
            SupportBundleContext(game_compatibility=(record,) * 9)

    def test_peripheral_support_context_is_categorical_and_omits_bindings(self):
        bundle = SupportBundleService().build(
            adversarial_report(), (), {},
            context=SupportBundleContext(
                peripheral_status=PeripheralSupportStatus(
                    True, False, "controller.identity_unmapped",
                    True, False, "audio.default_output_unobserved",
                )
            ),
        )
        self.assertEqual(
            bundle.payload["peripheral_status"]["controller"]["code"],
            "controller.identity_unmapped",
        )
        self.assertEqual(
            bundle.payload["peripheral_status"]["audio"]["exact"], False)
        for private in ("controller-private", "audio-private", "binding", "event1", "card0"):
            self.assertNotIn(private, bundle.json_text)

    def test_wake_diagnostics_context_is_categorical_and_omits_pci_identity(self):
        bundle = SupportBundleService().build(
            adversarial_report(), (), {},
            context=SupportBundleContext(
                wake_diagnostics=WakeDiagnosticsSupportStatus(
                    applicable=True,
                    bridge_wakeup="enabled",
                    function_wakeup_enabled=2,
                    function_wakeup_disabled=1,
                    function_wakeup_unknown=0,
                    function_runtime_active=2,
                    function_runtime_suspended=1,
                    function_runtime_unknown=0,
                    reason="wake.read_only_capability_observed",
                )
            ),
        )

        self.assertEqual(bundle.payload["wake_diagnostics"]["bridge_wakeup"], "enabled")
        self.assertEqual(bundle.payload["wake_diagnostics"]["function_runtime"]["suspended"], 1)
        self.assertIn("wake_diagnostics", bundle.payload["manifest"]["contents"])
        for private in ("0000:01:00.0", "0000:02:00.0", "power/wakeup", "runtime_status"):
            self.assertNotIn(private, bundle.json_text)


class SteamOsVersionDiscoveryTests(unittest.TestCase):
    def test_reads_only_allowlisted_version_fields(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            os_release = root / "os-release"
            kernel = root / "kernel"
            os_release.write_text(
                'VERSION_ID="3.7"\nBUILD_ID=20260830\nPRIVATE_TOKEN=must-not-export\n',
                encoding="utf-8",
            )
            kernel.write_text("6.11.11-valve\n", encoding="utf-8")

            result = SteamOsVersionDiscovery(os_release, kernel).scan()

            self.assertEqual(result.steamos, "3.7 (20260830)")
            self.assertEqual(result.kernel, "6.11.11-valve")
            self.assertNotIn("must-not-export", repr(result))


class SupportBundleFileWriterTests(unittest.TestCase):
    def test_writes_exact_reviewed_bytes_only_under_fixed_downloads_directory(self):
        fixed = datetime(2026, 8, 31, 1, 2, 3, 456789, tzinfo=timezone.utc)
        bundle = SupportBundleService().build(adversarial_report(), (), {})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            homes = root / "home"
            user_home = homes / "deck"
            user_home.mkdir(parents=True)
            writer = SupportBundleFileWriter(
                allowed_home_parent=homes,
                clock=lambda: fixed,
            )

            result = writer.save(user_home, bundle)
            target = user_home / result.relative_path

            self.assertEqual(
                result.relative_path,
                "Downloads/Re-Gear-support-20260831T010203456789Z.json",
            )
            self.assertEqual(target.read_text(encoding="utf-8"), bundle.json_text)
            self.assertNotIn(str(user_home), result.relative_path)
            with self.assertRaises(FileExistsError):
                writer.save(user_home, bundle)

    def test_rejects_home_outside_fixed_parent(self):
        bundle = SupportBundleService().build(adversarial_report(), (), {})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            allowed = root / "home"
            allowed.mkdir()
            outside = root / "outside"
            outside.mkdir()
            writer = SupportBundleFileWriter(allowed_home_parent=allowed)

            with self.assertRaisesRegex(ValueError, "outside"):
                writer.save(outside, bundle)


if __name__ == "__main__":
    unittest.main()
