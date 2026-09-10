from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.application.docked_igpu_exit import (  # noqa: E402
    DockedIgpuExitArmResult,
    DockedIgpuExitStage,
    DockedIgpuExitWatch,
)
from regear.application.docked_igpu_promotion import (  # noqa: E402
    DockedIgpuPromotionFacade,
)
from regear.application.supervised_transition import (  # noqa: E402
    SupervisedTransitionPreview,
)
from regear.domain.control_plane import PlacementState  # noqa: E402
from regear.domain.game_session import ActiveGameIdentity  # noqa: E402


WATCH_ID = "docked-igpu-watch-test-1"


def watch(stage=DockedIgpuExitStage.WATCHING):
    return DockedIgpuExitWatch(
        WATCH_ID,
        stage,
        ActiveGameIdentity("1234", ("app-steam-app1234-test.scope",)),
        "asus-rog-ally-x",
        "gpd-g1-rx7600mxt-titan-ridge",
        "gpd-g1:0123456789abcdef",
        "snapshot-running",
        "sample-running",
        "game-running",
        "a" * 64,
        100,
        1000,
        (
            "docked_igpu.promotion_ready"
            if stage is DockedIgpuExitStage.PROMOTION_READY
            else "docked_igpu.watching_game_exit"
        ),
        "snapshot-ready"
        if stage is DockedIgpuExitStage.PROMOTION_READY
        else "",
    )


class Watcher:
    def __init__(self):
        self.current = watch()
        self.polled = watch(DockedIgpuExitStage.PROMOTION_READY)

    def arm(self):
        return DockedIgpuExitArmResult(True, "docked_igpu.watch_armed", self.current)

    def poll(self, value):
        self.poll_input = value
        return self.polled


class Transitions:
    def __init__(self, *, blockers=(), token="", return_token_unconfirmed=False):
        self.blockers = blockers
        self.token = token
        self.return_token_unconfirmed = return_token_unconfirmed
        self.calls = []

    def preview(self, target, *, user_confirmed, expected_generation=""):
        self.calls.append((target, user_confirmed, expected_generation))
        return SupervisedTransitionPreview(
            target,
            PlacementState.DOCKED_IGPU,
            self.token if user_confirmed or self.return_token_unconfirmed else "",
            self.blockers,
        )


class DockedIgpuPromotionFacadeTests(unittest.TestCase):
    def test_opaque_watch_id_drives_poll_and_private_generation_bound_preview(self):
        watcher = Watcher()
        transitions = Transitions()
        facade = DockedIgpuPromotionFacade(
            watcher=watcher, transitions=transitions
        )

        armed = facade.arm()
        polled = facade.poll(armed.watch.watch_id)
        prepared = facade.prepare(WATCH_ID, user_confirmed=False)

        self.assertTrue(polled.accepted)
        self.assertEqual(
            polled.watch.stage, DockedIgpuExitStage.PROMOTION_READY
        )
        self.assertTrue(prepared.accepted)
        self.assertFalse(prepared.preview.approval_token)
        self.assertEqual(
            transitions.calls,
            [(PlacementState.DOCKED_EGPU, False, "snapshot-ready")],
        )

    def test_confirmed_preview_consumes_watch_only_after_token_issuance(self):
        facade = DockedIgpuPromotionFacade(
            watcher=Watcher(),
            transitions=Transitions(token="experimental_token_0001"),
        )
        facade.arm()
        facade.poll(WATCH_ID)
        prepared = facade.prepare(WATCH_ID, user_confirmed=True)

        self.assertTrue(prepared.accepted)
        self.assertEqual(
            prepared.preview.approval_token, "experimental_token_0001"
        )
        self.assertFalse(facade.cancel(WATCH_ID))
        self.assertEqual(
            facade.poll(WATCH_ID).code, "docked_igpu.watch_changed"
        )

    def test_unconfirmed_preview_never_consumes_watch_on_unexpected_token(self):
        facade = DockedIgpuPromotionFacade(
            watcher=Watcher(),
            transitions=Transitions(
                token="unexpected_token_0001", return_token_unconfirmed=True
            ),
        )
        facade.arm()
        facade.poll(WATCH_ID)

        prepared = facade.prepare(WATCH_ID, user_confirmed=False)

        self.assertTrue(prepared.accepted)
        self.assertEqual(prepared.preview.approval_token, "unexpected_token_0001")
        self.assertTrue(facade.cancel(WATCH_ID))

    def test_watch_only_composition_retains_ready_state_without_preview_port(self):
        facade = DockedIgpuPromotionFacade(watcher=Watcher())
        self.assertFalse(facade.inspection_supported)
        facade.arm()
        facade.poll(WATCH_ID)

        prepared = facade.prepare(WATCH_ID, user_confirmed=False)

        self.assertFalse(prepared.accepted)
        self.assertEqual(prepared.code, "docked_igpu.preview_unavailable")
        self.assertTrue(facade.cancel(WATCH_ID))

    def test_blocked_preview_retains_watch_for_explicit_cancel(self):
        facade = DockedIgpuPromotionFacade(
            watcher=Watcher(),
            transitions=Transitions(blockers=("integration.not_ready",)),
        )
        facade.arm()
        facade.poll(WATCH_ID)
        blocked = facade.prepare(WATCH_ID, user_confirmed=True)

        self.assertFalse(blocked.accepted)
        self.assertEqual(blocked.code, "docked_igpu.preview_blocked")
        self.assertTrue(facade.cancel(WATCH_ID))

    def test_wrong_identity_and_duplicate_arm_cannot_replace_private_watch(self):
        facade = DockedIgpuPromotionFacade(
            watcher=Watcher(), transitions=Transitions()
        )
        self.assertTrue(facade.arm().accepted)
        self.assertEqual(
            facade.arm().code, "docked_igpu.watch_already_active"
        )
        self.assertEqual(
            facade.poll("docked-igpu-watch-wrong").code,
            "docked_igpu.watch_changed",
        )
        self.assertFalse(facade.cancel("docked-igpu-watch-wrong"))


if __name__ == "__main__":
    unittest.main()
