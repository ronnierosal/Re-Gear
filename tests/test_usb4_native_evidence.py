"""Inert native evidence fixtures; no installed API or device is exercised."""
from dataclasses import replace
import unittest
from unittest.mock import Mock, patch

from regear.application.usb4_native_evidence import collect_native_evidence
from regear.ports.usb4_native_evidence import AttachmentEvidence, Fact, NativeSnapshot, ReadLimits


class Reader:
    def __init__(self, snapshot=None, owners=("private-owner", "private-owner")):
        self.snapshot = snapshot or NativeSnapshot(captured_at=10.0)
        self.owners = iter(owners)
        self.calls = []

    def service_owner(self, budget):
        self.calls.append(("owner", budget))
        return next(self.owners)

    def observe(self, owner, budget):
        self.calls.append(("observe", budget))
        return self.snapshot


class NativeEvidenceTests(unittest.TestCase):
    def collect(self, reader=None, **kwargs):
        return collect_native_evidence(reader or Reader(), clock=lambda: 10.0, **kwargs)

    def test_observation_is_not_eligibility_or_permission(self):
        for permission in (Fact.OBSERVED, Fact.DENIED, Fact.UNKNOWN):
            reader = Reader(NativeSnapshot(captured_at=10.0, static_permission=permission))
            result = self.collect(reader)
            self.assertEqual("evidence.observed", result.code)
            self.assertEqual(permission, result.snapshot.static_permission)
            self.assertFalse(hasattr(result, "dispatch_allowed"))
            self.assertFalse(hasattr(result, "mutation_allowed"))
            self.assertEqual(["owner", "observe", "owner"], [x[0] for x in reader.calls])
            self.assertTrue(all(x[1].deadline == 40.0 for x in reader.calls))
        for api in (Fact.UNKNOWN, Fact.UNAVAILABLE, Fact.UNSUPPORTED):
            result = self.collect(Reader(NativeSnapshot(captured_at=10.0, api=api)))
            self.assertEqual(api, result.snapshot.api)

    def test_absent_service_does_not_start_or_inspect_it(self):
        reader = Reader(owners=(None,))
        self.assertEqual("evidence.service_unavailable", self.collect(reader).code)
        self.assertEqual(["owner"], [x[0] for x in reader.calls])

    def test_owner_replacement_discards_all_partial_evidence(self):
        result = self.collect(Reader(owners=("old-owner", "replacement")))
        self.assertEqual("evidence.owner_changed", result.code)
        self.assertIsNone(result.snapshot)
        self.assertNotIn("old-owner", repr(result))

    def test_timeout_cancellation_and_reader_failures_are_categorical(self):
        for error, expected in ((TimeoutError("private"), "timeout"),
                                (PermissionError("private"), "denied"),
                                (NotImplementedError("private"), "unsupported"),
                                (RuntimeError("private"), "error"),
                                (ValueError("private"), "error")):
            reader = Reader()
            reader.observe = Mock(side_effect=error)
            result = self.collect(reader)
            self.assertEqual("evidence." + expected, result.code)
            self.assertIsNone(result.snapshot)
            self.assertNotIn("private", repr(result))
        reader = Reader()
        self.assertEqual("evidence.cancelled", self.collect(reader, cancelled=lambda: True).code)
        self.assertEqual([], reader.calls)
        reader = Reader()
        times = iter((10.0, 10.0, 10.0, 41.0))
        result = collect_native_evidence(reader, clock=lambda: next(times))
        self.assertEqual("evidence.timeout", result.code)
        self.assertEqual(["owner"], [x[0] for x in reader.calls])

    def test_bad_or_stale_snapshot_and_accounting_are_refused(self):
        for change, code in (({"captured_at": 1.0}, "stale"),
                             ({"captured_at": 11.0}, "stale"),
                             ({"captured_at": float("nan")}, "malformed"),
                             ({"objects_read": 65}, "bounds"),
                             ({"bytes_read": 65536}, "bounds"),
                             ({"objects_read": True}, "malformed"),
                             ({"api": "observed"}, "malformed")):
            with self.subTest(change=change):
                result = self.collect(Reader(replace(NativeSnapshot(captured_at=10.0), **change)))
                self.assertEqual("evidence." + code, result.code)
                self.assertIsNone(result.snapshot)

    def test_attachment_readback_cannot_follow_request_or_replacement(self):
        attached = AttachmentEvidence(binding="private-attachment", generation=4, fresh=True,
            authorization_requested=True, authorized=None, enrolled=False, gpu_present=False)
        for mismatch in ("other", None):
            reading = replace(attached, authorized=True, authorization_binding=mismatch,
                              authorization_generation=4)
            result = self.collect(Reader(NativeSnapshot(captured_at=10.0, attachment_state=Fact.OBSERVED, attachment=reading)))
            self.assertIsNone(result.snapshot.attachment.authorized)
        for change in ({"fresh": False}, {"authorization_generation": 3}):
            reading = replace(replace(attached, authorized=True, authorization_binding=attached.binding,
                              authorization_generation=4), **change)
            result = self.collect(Reader(NativeSnapshot(captured_at=10.0, attachment_state=Fact.OBSERVED, attachment=reading)))
            self.assertIsNone(result.snapshot.attachment.authorized)
        result = self.collect(Reader(NativeSnapshot(captured_at=10.0, attachment_state=Fact.OBSERVED, attachment=attached)))
        self.assertIsNone(result.snapshot.attachment.authorized)

    def test_authorized_readback_neither_enrolls_nor_enumerates_gpu(self):
        reading = AttachmentEvidence(binding="private-attachment", generation=4, fresh=True,
            authorized=True, authorization_binding="private-attachment", authorization_generation=4,
            enrolled=None, gpu_present=False)
        result = self.collect(Reader(NativeSnapshot(captured_at=10.0, attachment_state=Fact.OBSERVED, attachment=reading)))
        self.assertTrue(result.snapshot.attachment.authorized)
        self.assertIsNone(result.snapshot.attachment.enrolled)
        self.assertFalse(result.snapshot.attachment.gpu_present)
        self.assertNotIn("private-attachment", repr(result))

    def test_ambiguous_and_unknown_attachment_withdraw_private_binding(self):
        reading = AttachmentEvidence(binding="private-attachment", generation=4, fresh=True)
        for state in (Fact.AMBIGUOUS, Fact.STALE, Fact.UNKNOWN, Fact.UNAVAILABLE):
            report = self.collect(Reader(NativeSnapshot(captured_at=10.0, attachment_state=state, attachment=reading)))
            self.assertIsNone(report.snapshot.attachment)
            self.assertEqual(state, report.snapshot.attachment_state)

    def test_reader_gets_remaining_budget_and_midread_cancel_withdraws(self):
        reader = Reader()
        self.collect(reader)
        budget = reader.calls[1][1]
        self.assertEqual(64 - 2, budget.max_objects)
        self.assertEqual(65536 - 2 * len("private-owner"), budget.max_bytes)
        cancelled = False
        def observe(owner, budget):
            nonlocal cancelled
            cancelled = True
            return NativeSnapshot(captured_at=10.0)
        reader = Reader()
        reader.observe = observe
        report = self.collect(reader, cancelled=lambda: cancelled)
        self.assertEqual("evidence.cancelled", report.code)
        self.assertIsNone(report.snapshot)
        self.assertEqual(1, len(reader.calls))

    def test_callers_cannot_enlarge_fixed_read_budget(self):
        for limits in (ReadLimits(seconds=31), ReadLimits(max_bytes=65537),
                       ReadLimits(max_objects=65), ReadLimits(seconds=True),
                       ReadLimits(seconds=10**1000), ReadLimits(seconds=float("nan"))):
            reader = Reader()
            self.assertEqual("evidence.limits_invalid", self.collect(reader, limits=limits).code)
            self.assertEqual([], reader.calls)


class AdmissionIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_evidence_never_opens_real_unsupported_host_authorization(self):
        from tests.test_main_process_delivery import load_main_module
        from regear.adapters.steamos.host import HostRecord
        from regear.delivery import build_profile_config
        for profile in ("development", "production"):
            with self.subTest(profile=profile), patch.object(build_profile_config, "BUILD_PROFILE", profile):
                module = load_main_module(real_dock_gate=True, real_host_admission=True)
                with patch("regear.adapters.steamos.host.HostDiscovery.scan", return_value=HostRecord("GPD", "G1617-01", "unknown")), \
                     patch.object(module, "DeviceAuthorizationFacade") as factory, \
                     patch.object(module, "RootOwnedRuntimeState") as store, \
                     patch.object(module, "SleepGuardController") as lease, \
                     patch("regear.adapters.steamos.commands.BoltDeviceAuthorizationRunner.authorize") as authorize, \
                     patch("regear.adapters.steamos.commands.BoltDeviceAuthorizationRunner.enroll") as enroll, \
                     patch.object(module, "DiagnosticsApi"), \
                     patch.object(module.asyncio, "create_task") as schedule:
                    plugin = module.Plugin()
                    collect_native_evidence(Reader(), clock=lambda: 10.0)
                    for token in ("forged-token", "replayed-token"):
                        for method, args in (("get_device_authorization_status", ()),
                                             ("acknowledge_device_authorization", (token,)),
                                             ("confirm_device_authorization", (token, True, "authorize"))):
                            result = await getattr(plugin, method)(*args)
                            self.assertEqual("runtime.observation_only", result["code"])
                            self.assertFalse(result["requested"])
                    for spy in (factory, store, lease, authorize, enroll, schedule):
                        spy.assert_not_called()
