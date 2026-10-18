"""Synthetic consistency fixtures only; no system/session evidence collection."""
from dataclasses import replace
import unittest

from test_experimental_handoff_approval import context
from regear.application.experimental_session_qualification import SessionEvidence, qualify_session


class SessionQualificationTests(unittest.TestCase):
    def setUp(self):
        self.context = replace(context(), session_unit="gamescope-session.service",
                               session_target="gamescope-session.target")
        c = self.context
        self.evidence = SessionEvidence(
            c.boot_id, c.user_uid, c.user_context_sha256, c.source_main_pid, 100, 100,
            c.session_unit, (c.session_unit,), c.session_target, (c.session_unit,),
            c.source_main_pid, c.source_invocation_id, True, True,
            c.session_definition_sha256, c.integration_sha256, True, 10, 11)

    def test_complete_fresh_fixture_and_verified_alias_chain(self):
        self.assertTrue(qualify_session(self.context, self.evidence, now=12))
        e = replace(self.evidence, unit="fixture-session@.service",
                    aliases=("fixture-session@.service", self.context.session_unit),
                    target_services=("fixture-session@.service",))
        self.assertTrue(qualify_session(self.context, e, now=12))

    def test_every_missing_inconsistent_or_unverified_field_refuses(self):
        changes = dict(boot_id="other", user_uid=2, user_context_sha256="f"*64,
                       pid=2, main_pid=2, start_before=0, start_after=101,
                       unit="unrelated.service", aliases=(), target="other.target",
                       target_services=(), invocation_id="other", service_active=False,
                       target_active=False, definition_sha256="f"*64,
                       integration_sha256="f"*64, integration_safe=False)
        for field, value in changes.items():
            with self.subTest(field=field):
                self.assertFalse(qualify_session(self.context,
                    replace(self.evidence, **{field:value}), now=12))

    def test_unknown_malformed_stale_future_and_nonfinite_evidence_refuses(self):
        for evidence in (None, {}, object()):
            self.assertFalse(qualify_session(self.context, evidence, now=12))
        for now in (True, float("nan"), float("inf"), 10, 16):
            self.assertFalse(qualify_session(self.context, self.evidence, now=now))
        for change in (dict(started=-1), dict(completed=9), dict(started=True),
                       dict(aliases=[self.context.session_unit]), dict(integration_safe=1),
                       dict(aliases=(self.context.session_unit,)*2), dict(user_uid=True)):
            self.assertFalse(qualify_session(self.context, replace(self.evidence,**change),now=12))

    def test_oversized_timestamps_refuse_without_raising(self):
        self.assertFalse(qualify_session(self.context,self.evidence,now=10**1000))
        for field in ("started","completed"):
            self.assertFalse(qualify_session(self.context,
                replace(self.evidence,**{field:10**1000}),now=12))

    def test_other_command_contract_and_template_only_refuse(self):
        self.assertFalse(qualify_session(replace(self.context,session_unit="other.service"),
                                        self.evidence,now=12))
        e=replace(self.evidence,unit="fixture-session@.service",aliases=("fixture-session@.service",))
        self.assertFalse(qualify_session(self.context,e,now=12))


if __name__ == "__main__":
    unittest.main()
