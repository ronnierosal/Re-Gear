"""Fictional context tests; no hardware, runtime composition or admission."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, fields, replace
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from regear.application.experimental_handoff_approval import HandoffContext, HandoffApprovalStore, HandoffAudioPermission, HandoffAudioOperation
from regear.domain.control_plane import PlacementState
from regear.ports.presentation_activation import UserServiceOperation


def context():
    return HandoffContext(
        host_identity_sha256="1" * 64, host_profile_id="fixture-host",
        egpu_profile_id="fixture-egpu", egpu_stable_id="fixture-egpu-identity",
        build_profile="development", boot_id="fixture-boot-0001",
        snapshot_generation="2" * 64, source_placement=PlacementState.PORTABLE,
        target_placement=PlacementState.DOCKED_EGPU, internal_gpu_id="fixture-internal-gpu",
        internal_display_id="fixture-internal-display", external_display_id="fixture-external-display",
        user_uid=1000, user_context_sha256="3" * 64,
        session_unit="fixture-session.service", session_target="fixture-session.target",
        session_definition_sha256="4" * 64, integration_sha256="5" * 64,
        source_invocation_id="fixture-invocation-0001", source_main_pid=1234,
        allowed_operations=(UserServiceOperation.DAEMON_RELOAD,), evidence_verified=True,
    )


class HandoffApprovalTests(unittest.TestCase):
    def store(self, clock=lambda: 0):
        return HandoffApprovalStore(monotonic=clock)

    def test_exact_context_consumes_existing_permit_once(self):
        store = self.store(); current = context()
        token = store.issue(plan_id="fixture-plan-0001", context=current, user_confirmed=True)
        approved = store.consume(token, current=current)
        self.assertEqual(approved.context, current)
        self.assertEqual(approved.permit.observed_generation, current.snapshot_generation)
        self.assertEqual(approved.permit.target_placement, current.target_placement)
        with self.assertRaises(ValueError):store.consume(token, current=current)
        with self.assertRaises(FrozenInstanceError):approved.context.boot_id = "changed"

    def test_every_changed_field_denies_and_burns_token(self):
        for field in fields(HandoffContext):
            with self.subTest(field=field.name):
                original = context(); value = getattr(original, field.name)
                if field.name == "audio":
                    changed = replace(original, audio=HandoffAudioPermission("a"*64,"b"*64,"c"*64,
                        (HandoffAudioOperation.DUMP,)))
                elif field.name == "source_placement" or field.name == "target_placement":
                    changed = replace(original, source_placement=PlacementState.DOCKED_EGPU,
                                      target_placement=PlacementState.PORTABLE)
                elif field.name in {"build_profile", "evidence_verified"}:
                    changed = None  # Invalid/uncertain context cannot be constructed.
                elif field.name == "allowed_operations":
                    changed = replace(original, allowed_operations=(UserServiceOperation.VERIFY_GAMESCOPE_UNIT,))
                elif type(value) is int:changed = replace(original, **{field.name: value + 1})
                elif field.name.endswith("sha256") or field.name == "snapshot_generation":
                    changed = replace(original, **{field.name: "a" * 64})
                elif field.name == "session_unit":changed = replace(original, session_unit="different.service")
                elif field.name == "session_target":changed = replace(original, session_target="different.target")
                else:changed = replace(original, **{field.name: value + "-changed"})
                store = self.store();token = store.issue(plan_id="fixture-plan-0001", context=original, user_confirmed=True)
                with self.assertRaises(ValueError):store.consume(token, current=changed)
                with self.assertRaises(ValueError):store.consume(token, current=original)

    def test_missing_malformed_or_unverified_fields_deny(self):
        for field in fields(HandoffContext):
            if field.name == "audio":continue  # Optional permission defaults denied.
            with self.subTest(field=field.name), self.assertRaises(ValueError):
                replace(context(), **{field.name: None})
        for name, value in (("build_profile", "production"), ("evidence_verified", False),
                            ("evidence_verified", 1), ("user_uid", True),
                            ("source_main_pid", 0), ("host_identity_sha256", "unknown"),
                            ("session_unit", "../unsafe.service"),
                            ("allowed_operations", (UserServiceOperation.RESTART_PIPEWIRE,)),
                            ("allowed_operations", [UserServiceOperation.DAEMON_RELOAD])):
            with self.subTest(field=name), self.assertRaises(ValueError):replace(context(), **{name:value})

    def test_strict_consent_expiry_and_replacement(self):
        now = [0.0];store = self.store(lambda:now[0]); current = context()
        for value in (False, None, 1, "true", object()):
            with self.assertRaises(ValueError):store.issue(plan_id="fixture-plan-0001", context=current, user_confirmed=value)
        old = store.issue(plan_id="fixture-plan-0001", context=current, user_confirmed=True)
        new = store.issue(plan_id="fixture-plan-0002", context=current, user_confirmed=True)
        self.assertNotEqual(old, new)
        now[0] = 120.0
        with self.assertRaises(ValueError):store.consume(new, current=current)
        with self.assertRaises(ValueError):store.consume(new, current=current)

    def test_only_one_concurrent_consumer_succeeds(self):
        store=self.store(); current=context()
        token=store.issue(plan_id="fixture-plan-0001", context=current, user_confirmed=True)
        def consume(_):
            try:store.consume(token,current=current);return True
            except ValueError:return False
        with ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(sum(pool.map(consume, range(16))),1)

    def test_wrong_or_malformed_token_never_grants_context(self):
        for bad in (None, 1, "", "wrong-token-00000000"):
            store=self.store();current=context()
            store.issue(plan_id="fixture-plan-0001",context=current,user_confirmed=True)
            with self.assertRaises(ValueError):store.consume(bad,current=current)


class HandoffRequestBindingTests(unittest.TestCase):
    def test_explicit_request_survives_one_consumption_and_invalid_values_deny(self):
        store=HandoffApprovalStore();current=context()
        token=store.issue(plan_id="fixture-plan",request_id="fixture-request",context=current,user_confirmed=True)
        approved=store.consume(token,current=current)
        self.assertEqual(approved.request_id,"fixture-request")
        self.assertEqual(approved.permit.plan_id,"fixture-plan")
        with self.assertRaises(ValueError):store.consume(token,current=current)
        for request in (None,True,"../unsafe","x"*97):
            with self.assertRaises(ValueError):
                store.issue(plan_id="fixture-plan",request_id=request,context=current,user_confirmed=True)


class AudioPermissionTests(unittest.TestCase):
    def permission(self):
        return HandoffAudioPermission("a"*64,"b"*64,"c"*64,tuple(HandoffAudioOperation))

    def test_audio_fields_and_operation_changes_burn_approval(self):
        original=replace(context(),audio=self.permission())
        for field in fields(HandoffAudioPermission):
            value=getattr(original.audio,field.name)
            changed=replace(original.audio,**{field.name:(HandoffAudioOperation.DUMP,)
                if field.name=="operations" else "d"*64})
            store=HandoffApprovalStore();token=store.issue(plan_id="fixture-plan-audio",context=original,user_confirmed=True)
            with self.assertRaises(ValueError):store.consume(token,current=replace(original,audio=changed))
            with self.assertRaises(ValueError):store.consume(token,current=original)
        self.assertIsNone(context().audio)
        with self.assertRaises(ValueError):replace(context(),audio=True)

    def test_malformed_audio_identity_and_permissions_refuse(self):
        for bad in (None,True,"unknown","a"*63):
            with self.assertRaises(ValueError):replace(self.permission(),target_sink_sha256=bad)
        for bad in ((),[],("dump",),(HandoffAudioOperation.DUMP,)*2):
            with self.assertRaises(ValueError):replace(self.permission(),operations=bad)


if __name__ == "__main__":unittest.main()
