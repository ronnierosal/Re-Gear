from __future__ import annotations

import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.application.attach_readiness import (  # noqa: E402
    AttachReadinessLifecycle,
    AttachReadinessStage,
    READY_STABILITY_SAMPLES,
    arm_attach_readiness,
    observe_attach_readiness,
)
from regear.application.topology_event_detection import detect_topology_event  # noqa: E402
from regear.domain.models import (  # noqa: E402
    Confidence,
    DisplayKind,
    EgpuLinkObservation,
    EgpuLinkState,
    GameState,
)
from regear.domain.serialization import snapshot_from_dict  # noqa: E402
from regear.ports.transition import VersionedObservation  # noqa: E402


FIXTURES = ROOT / "tests" / "fixtures"


def snapshot(name: str):
    return snapshot_from_dict(json.loads((FIXTURES / name).read_text(encoding="utf-8")))


def observed(generation: str, sample: str, value):
    return VersionedObservation(generation, value, sample)


def link_up(value):
    return replace(
        value,
        egpu_link=EgpuLinkObservation(
            True, EgpuLinkState.UP, Confidence.OBSERVED, "egpu.link_observed"
        ),
    )


class AttachReadinessTests(unittest.TestCase):
    def _watch(self):
        before = observed("portable", "sample-a", snapshot("portable.json"))
        attached = observed("attached", "sample-b", snapshot("connected-internal.json"))
        detection = detect_topology_event(before, attached)
        watch = arm_attach_readiness(detection, attached)
        self.assertIsNotNone(watch)
        return watch, attached

    def test_exact_attached_idle_tv_is_readiness_only(self):
        watch, attached = self._watch()

        result = observe_attach_readiness(
            watch,
            observed(attached.generation, "sample-c", link_up(attached.snapshot)),
        )

        self.assertEqual(result.stage, AttachReadinessStage.READY_IDLE)
        self.assertEqual(result.code, "attach.ready_idle")

    def test_reused_sample_waits_and_changed_identity_fails_closed(self):
        watch, attached = self._watch()
        settling = observe_attach_readiness(watch, attached)
        self.assertEqual(settling.stage, AttachReadinessStage.SETTLING)
        self.assertEqual(settling.poll_after_ms, 250)

        changed = replace(
            attached.snapshot,
            gpus=tuple(
                replace(gpu, stable_id="gpd-g1:ffffffffffffffff")
                if gpu.role.value == "external"
                else gpu
                for gpu in attached.snapshot.gpus
            ),
        )
        result = observe_attach_readiness(watch, observed("changed", "sample-c", changed))
        self.assertEqual(result.stage, AttachReadinessStage.ACTION_REQUIRED)
        self.assertEqual(result.code, "attach.identity_changed")

    def test_missing_tv_waits_but_unknown_game_or_session_stops(self):
        watch, attached = self._watch()
        no_tv = replace(
            attached.snapshot,
            displays=tuple(
                replace(display, connected=False, edid_ready=False)
                if display.kind is DisplayKind.EXTERNAL
                else display
                for display in attached.snapshot.displays
            ),
        )
        waiting = observe_attach_readiness(watch, observed("no-tv", "sample-c", no_tv))
        self.assertEqual(waiting.stage, AttachReadinessStage.WAITING_FOR_EXTERNAL_DISPLAY)

        unknown_game = replace(attached.snapshot, game_state=GameState.UNKNOWN)
        result = observe_attach_readiness(
            watch, observed("unknown-game", "sample-d", unknown_game)
        )
        self.assertEqual(result.stage, AttachReadinessStage.ACTION_REQUIRED)
        self.assertEqual(result.code, "attach.game_state_unknown")

    def test_down_or_missing_link_never_appears_ready_idle(self):
        watch, attached = self._watch()
        down = replace(
            attached.snapshot,
            egpu_link=EgpuLinkObservation(
                True, EgpuLinkState.DOWN, Confidence.OBSERVED, "egpu.link_down"
            ),
        )
        result = observe_attach_readiness(watch, observed("down", "sample-c", down))
        self.assertEqual(result.stage, AttachReadinessStage.WAITING_FOR_LINK_HEALTH)
        self.assertEqual(result.code, "attach.link_down")

        unverified = replace(
            attached.snapshot,
            egpu_link=EgpuLinkObservation(False, EgpuLinkState.UNKNOWN, Confidence.UNKNOWN),
        )
        result = observe_attach_readiness(
            watch, observed("unknown-link", "sample-d", unverified)
        )
        self.assertEqual(result.stage, AttachReadinessStage.WAITING_FOR_LINK_HEALTH)
        self.assertEqual(result.code, "attach.link_unverified")

    def test_running_game_never_becomes_idle_transition_ready(self):
        watch, attached = self._watch()
        running = replace(link_up(attached.snapshot), game_state=GameState.RUNNING)

        result = observe_attach_readiness(watch, observed("running", "sample-c", running))

        self.assertEqual(result.stage, AttachReadinessStage.GAME_RUNNING)
        self.assertEqual(result.code, "attach.game_running")

    def test_lifecycle_uses_only_existing_snapshot_updates(self):
        before = observed("portable", "sample-a", snapshot("portable.json"))
        attached = observed("attached", "sample-b", snapshot("connected-internal.json"))
        lifecycle = AttachReadinessLifecycle()

        armed = lifecycle.update(detect_topology_event(before, attached), attached)
        results = []
        prior = attached
        for index in range(READY_STABILITY_SAMPLES):
            fresh = observed(
                "attached",
                f"sample-{index + 3}",
                link_up(attached.snapshot),
            )
            results.append(
                lifecycle.update(detect_topology_event(prior, fresh), fresh)
            )
            prior = fresh

        self.assertEqual(armed.stage, AttachReadinessStage.SETTLING)
        self.assertTrue(
            all(
                result.stage is AttachReadinessStage.SETTLING
                for result in results[:-1]
            )
        )
        self.assertEqual(results[-1].stage, AttachReadinessStage.READY_IDLE)

    def test_exact_startup_candidate_requires_a_later_fresh_sample(self):
        first = observed(
            "attached", "sample-a", link_up(snapshot("connected-internal.json"))
        )
        lifecycle = AttachReadinessLifecycle()

        armed = lifecycle.arm_current(first)
        still_same = lifecycle.update(detect_topology_event(first, first), first)
        prior = first
        results = []
        for index in range(READY_STABILITY_SAMPLES):
            fresh = observed("attached", f"sample-{index + 2}", first.snapshot)
            results.append(lifecycle.update(detect_topology_event(prior, fresh), fresh))
            prior = fresh

        self.assertEqual(armed.stage, AttachReadinessStage.SETTLING)
        self.assertEqual(still_same.stage, AttachReadinessStage.SETTLING)
        self.assertEqual(results[-1].stage, AttachReadinessStage.READY_IDLE)

    def test_repeated_ready_sample_cannot_satisfy_stability_quorum(self):
        before = observed("portable", "sample-a", snapshot("portable.json"))
        attached = observed("attached", "sample-b", snapshot("connected-internal.json"))
        lifecycle = AttachReadinessLifecycle()
        lifecycle.update(detect_topology_event(before, attached), attached)
        ready_sample = observed(
            "attached", "sample-c", link_up(attached.snapshot)
        )

        results = [
            lifecycle.update(detect_topology_event(attached, ready_sample), ready_sample)
            for _ in range(READY_STABILITY_SAMPLES + 1)
        ]

        self.assertTrue(
            all(result.stage is AttachReadinessStage.SETTLING for result in results)
        )

    def test_readiness_regression_resets_stability_quorum(self):
        before = observed("portable", "sample-a", snapshot("portable.json"))
        attached = observed("attached", "sample-b", snapshot("connected-internal.json"))
        lifecycle = AttachReadinessLifecycle()
        lifecycle.update(detect_topology_event(before, attached), attached)

        prior = attached
        for index in range(READY_STABILITY_SAMPLES - 1):
            ready = observed(
                "attached",
                f"ready-before-regression-{index}",
                link_up(attached.snapshot),
            )
            status = lifecycle.update(detect_topology_event(prior, ready), ready)
            self.assertEqual(status.stage, AttachReadinessStage.SETTLING)
            prior = ready

        regressed = observed("attached", "regressed", attached.snapshot)
        status = lifecycle.update(detect_topology_event(prior, regressed), regressed)
        self.assertEqual(status.stage, AttachReadinessStage.WAITING_FOR_LINK_HEALTH)
        self.assertEqual(status.code, "attach.link_unverified")

        prior = regressed
        results = []
        for index in range(READY_STABILITY_SAMPLES):
            ready = observed(
                "attached",
                f"ready-after-regression-{index}",
                link_up(attached.snapshot),
            )
            results.append(lifecycle.update(detect_topology_event(prior, ready), ready))
            prior = ready

        self.assertTrue(
            all(
                result.stage is AttachReadinessStage.SETTLING
                for result in results[:-1]
            )
        )
        self.assertEqual(results[-1].stage, AttachReadinessStage.READY_IDLE)


if __name__ == "__main__":
    unittest.main()
