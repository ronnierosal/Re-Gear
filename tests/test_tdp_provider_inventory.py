import dataclasses
import math
import unittest
from copy import deepcopy
from unittest.mock import patch

from regear.adapters.steamos.host import HostRecord
from regear.adapters.steamos.tdp_provider import SteamOsManagerTdpProvider
from regear.adapters.steamos.tdp_provider_inventory import (
    CONFIGURED_LIMIT_KIND,
    POWER_STATION_SIGNATURE,
    WATTS_UNIT,
    interpret_tdp_provider_fixture,
)
from regear.delivery.tdp_runtime import TdpRuntime
from regear.domain.auto_tdp import AutoTdpPolicy
from regear.ports.tdp_provider_evidence import TdpProviderEvidenceResult


def provider_fixture():
    host = {
        "sys_vendor": "GPD",
        "product_name": "G1617-01",
        "board_name": "G1617-01",
        "processor": "AMD Ryzen 7 7840U w/ Radeon 780M Graphics",
    }
    return {
        "schema_version": 1,
        "provenance": {"kind": "synthetic_fixture", "fixture_id": "winmini-2023-sample-a"},
        "host_before": host,
        "host_after": dict(host),
        "provider": {
            "name": "power_station",
            "signature": POWER_STATION_SIGNATURE,
            "value_kind": CONFIGURED_LIMIT_KIND,
            "unit": WATTS_UNIT,
            "current": 15,
            "minimum": 5,
            "maximum": 30,
        },
        "gpu_ownership": {
            "resolved": True,
            "provider_gpu_stable_id": "pci:0000:04:00.0",
            "candidates": [
                {"stable_id": "pci:0000:04:00.0", "role": "igpu"},
                {"stable_id": "pci:0000:05:00.0", "role": "dgpu"},
                {"stable_id": "pci:0000:06:00.0", "role": "egpu"},
            ],
        },
    }


class TdpProviderInventoryTests(unittest.TestCase):
    def test_complete_fixture_is_immutable_observation_without_authority(self):
        result = interpret_tdp_provider_fixture(provider_fixture())

        self.assertEqual(result.code, "tdp.fixture_observed_unverified")
        self.assertEqual(result.provenance, "synthetic_fixture")
        self.assertEqual(result.fixture_id, "winmini-2023-sample-a")
        self.assertIs(result.can_control, False)
        self.assertEqual(result.observed_range.current, 15)
        self.assertEqual(result.provider_gpu.role, "igpu")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            result.can_control = True
        with self.assertRaises(ValueError):
            TdpProviderEvidenceResult("bad", "fixture", can_control=True)

    def test_schema_provider_signature_value_kind_and_units_are_exact(self):
        mutations = (
            (("schema_version",), 2, "tdp.fixture_signature_invalid"),
            (("provider", "name"), "PowerStation", "tdp.fixture_signature_invalid"),
            (("provider", "signature"), POWER_STATION_SIGNATURE + ".v2", "tdp.fixture_signature_invalid"),
            (("provider", "value_kind"), "measured_package_power", "tdp.fixture_signature_invalid"),
            (("provider", "unit"), "milliwatts", "tdp.fixture_unit_invalid"),
        )
        for path, value, code in mutations:
            with self.subTest(path=path):
                fixture = provider_fixture()
                target = fixture
                for component in path[:-1]:
                    target = target[component]
                target[path[-1]] = value
                result = interpret_tdp_provider_fixture(fixture)
                self.assertEqual(result.code, code)
                self.assertIs(result.can_control, False)
                self.assertEqual(result.provenance, "synthetic_fixture")

    def test_missing_extra_and_malformed_evidence_fail_closed(self):
        missing = provider_fixture()
        del missing["provider"]
        extra = provider_fixture()
        extra["live_path"] = "/sys/provider"
        malformed = provider_fixture()
        malformed["provider"] = "power_station"

        for fixture in (None, {}, missing, extra, malformed):
            with self.subTest(fixture=fixture):
                result = interpret_tdp_provider_fixture(fixture)
                self.assertIn(result.code, ("tdp.fixture_malformed", "tdp.fixture_provider_invalid"))
                self.assertIs(result.can_control, False)

    def test_nonfinite_noninteger_and_encoding_range_values_are_rejected(self):
        for value, code in (
            (math.nan, "tdp.fixture_value_nonfinite"),
            (math.inf, "tdp.fixture_value_nonfinite"),
            (-math.inf, "tdp.fixture_value_nonfinite"),
            (15.0, "tdp.fixture_value_invalid"),
            (True, "tdp.fixture_value_invalid"),
            (0, "tdp.fixture_value_out_of_range"),
            (-1, "tdp.fixture_value_out_of_range"),
            (0x100000000, "tdp.fixture_value_out_of_range"),
        ):
            with self.subTest(value=value):
                fixture = provider_fixture()
                fixture["provider"]["current"] = value
                self.assertEqual(interpret_tdp_provider_fixture(fixture).code, code)

        fixture = provider_fixture()
        fixture["provider"].update(current=4, minimum=5, maximum=30)
        self.assertEqual(
            interpret_tdp_provider_fixture(fixture).code,
            "tdp.fixture_range_inconsistent",
        )

    def test_identity_changes_and_unverified_host_are_not_inferred(self):
        changed = provider_fixture()
        changed["host_after"]["product_name"] = "G1618-00"
        self.assertEqual(
            interpret_tdp_provider_fixture(changed).code,
            "tdp.fixture_identity_changed",
        )

        wrong = provider_fixture()
        wrong["host_before"]["sys_vendor"] = "ASUSTeK COMPUTER INC."
        wrong["host_after"] = deepcopy(wrong["host_before"])
        self.assertEqual(
            interpret_tdp_provider_fixture(wrong).code,
            "tdp.fixture_host_unverified",
        )

    def test_gpu_ownership_must_resolve_one_exact_igpu_among_all_roles(self):
        unresolved = provider_fixture()
        unresolved["gpu_ownership"]["resolved"] = False
        self.assertEqual(
            interpret_tdp_provider_fixture(unresolved).code,
            "tdp.fixture_ownership_unresolved",
        )

        missing_owner = provider_fixture()
        missing_owner["gpu_ownership"]["provider_gpu_stable_id"] = "pci:unknown"
        self.assertEqual(
            interpret_tdp_provider_fixture(missing_owner).code,
            "tdp.fixture_ownership_ambiguous",
        )

        duplicate = provider_fixture()
        duplicate["gpu_ownership"]["candidates"].append(
            {"stable_id": "pci:0000:04:00.0", "role": "egpu"}
        )
        self.assertEqual(
            interpret_tdp_provider_fixture(duplicate).code,
            "tdp.fixture_ownership_ambiguous",
        )

        external = provider_fixture()
        external["gpu_ownership"]["provider_gpu_stable_id"] = "pci:0000:06:00.0"
        self.assertEqual(
            interpret_tdp_provider_fixture(external).code,
            "tdp.fixture_provider_gpu_unverified",
        )


class _CountingHost:
    def __init__(self):
        self.calls = 0

    def scan(self):
        self.calls += 1
        return HostRecord("GPD", "G1617-01", "G1617-01")


class _ForbiddenInventory:
    def __init__(self):
        self.calls = 0

    def scan(self):
        self.calls += 1
        raise AssertionError("ASUS firmware inventory must not be scanned")


class _ForbiddenCommands:
    def __init__(self):
        self.owner_calls = self.read_calls = self.set_calls = 0

    def owner(self, _user):
        self.owner_calls += 1
        raise AssertionError("owner command must not run")

    def read(self, _user):
        self.read_calls += 1
        raise AssertionError("read command must not run")

    def set_limit(self, _user, _watts, **_kwargs):
        self.set_calls += 1
        raise AssertionError("set command must not run")


class _ForbiddenBootPath:
    def __init__(self):
        self.calls = 0

    def open(self, *_args, **_kwargs):
        self.calls += 1
        raise AssertionError("boot identity must not be read")


class _EmptyJournal:
    def __init__(self):
        self.loads = 0
        self.saves = 0

    def load(self):
        self.loads += 1
        return None

    def save(self, _record):
        self.saves += 1
        raise AssertionError("journal must not publish or write")


class _Lease:
    held = False

    def __init__(self):
        self.acquires = 0
        self.closes = 0

    def acquire(self):
        self.acquires += 1
        raise AssertionError("writer lease must not be acquired")

    def close(self):
        self.closes += 1


class ExistingRuntimeRejectionTests(unittest.TestCase):
    def test_existing_provider_and_runtime_reject_gpd_before_any_control_boundary(self):
        host = _CountingHost()
        inventory = _ForbiddenInventory()
        commands = _ForbiddenCommands()
        boot = _ForbiddenBootPath()
        users = 0

        def resolve_user():
            nonlocal users
            users += 1
            raise AssertionError("user must not be resolved")

        provider = SteamOsManagerTdpProvider(
            user_resolver=resolve_user,
            host=host,
            inventory=inventory,
            commands=commands,
            boot_id_path=boot,
        )
        direct = provider.observe()
        self.assertEqual(direct.code, "tdp.host_unverified")

        journal = _EmptyJournal()
        lease = _Lease()
        auto_sessions = 0

        def auto_session(_actuator, _provider):
            nonlocal auto_sessions
            auto_sessions += 1
            raise AssertionError("Auto TDP session must not be constructed")

        runtime = TdpRuntime(
            provider_factory=lambda _ownership_ready: provider,
            journal=journal,
            lease=lease,
            preflight=lambda: "tdp.ready",
            auto_session_factory=auto_session,
        )
        status = runtime.status()
        self.assertEqual(status["code"], "tdp.host_unverified")
        self.assertIs(status["auto_tdp_available"], True)
        self.assertEqual(runtime.set_enabled(True)["code"], "tdp.host_unverified")
        self.assertEqual(runtime.apply(15)["code"], "tdp.enable_required")
        self.assertEqual(runtime.restore()["code"], "tdp.host_unverified")
        with patch("regear.delivery.tdp_runtime.AutoTdpWorker") as worker_type:
            self.assertIsNone(runtime.start_auto(AutoTdpPolicy(5, 30, 40.0)))
            worker_type.assert_not_called()
        runtime.close()

        self.assertGreaterEqual(host.calls, 6)
        self.assertGreaterEqual(journal.loads, 5)
        self.assertEqual(journal.saves, 0)
        self.assertEqual(lease.acquires, 0)
        self.assertGreaterEqual(lease.closes, 1)  # close() cleanup is allowed.
        self.assertEqual(users, 0)
        self.assertEqual(inventory.calls, 0)
        self.assertEqual(commands.owner_calls, 0)
        self.assertEqual(commands.read_calls, 0)
        self.assertEqual(commands.set_calls, 0)
        self.assertEqual(boot.calls, 0)
        self.assertEqual(auto_sessions, 0)


if __name__ == "__main__":
    unittest.main()
