from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.application.docked_igpu_lifecycle import (  # noqa: E402
    DockedIgpuLifecycleStage,
    DockedIgpuLifecycleStatus,
)
from regear.delivery.docked_igpu_scheduler import (  # noqa: E402
    DockedIgpuLifecycleScheduler,
)


def status(stage, code, poll_after_ms=0):
    return DockedIgpuLifecycleStatus(
        stage,
        code,
        poll_after_ms,
        inspection_available=(
            stage is DockedIgpuLifecycleStage.PROMOTION_READY
        ),
        acknowledgement_required=(
            stage is DockedIgpuLifecycleStage.ACTION_REQUIRED
        ),
    )


class Lifecycle:
    def __init__(self, values):
        self.values = list(values)
        self.current = status(
            DockedIgpuLifecycleStage.IDLE,
            "docked_igpu.lifecycle_idle",
            250,
        )
        self.tick_calls = 0
        self.close_calls = 0
        self.acknowledge_calls = 0

    def status(self):
        return self.current

    def tick(self):
        self.tick_calls += 1
        if self.values:
            self.current = self.values.pop(0)
        return self.current

    def close(self):
        self.close_calls += 1
        self.current = status(
            DockedIgpuLifecycleStage.CLOSED,
            "docked_igpu.lifecycle_closed",
        )
        return self.current

    def acknowledge_action(self):
        self.acknowledge_calls += 1
        if self.current.stage is not DockedIgpuLifecycleStage.ACTION_REQUIRED:
            return False
        self.current = status(
            DockedIgpuLifecycleStage.IDLE,
            "docked_igpu.action_acknowledged",
            5000,
        )
        return True


async def wait_until(predicate, attempts=200):
    for _ in range(attempts):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("asynchronous condition was not reached")


class DockedIgpuLifecycleSchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def test_wake_advances_without_waiting_for_poll_deadline(self):
        lifecycle = Lifecycle(
            (
                status(
                    DockedIgpuLifecycleStage.WATCHING,
                    "docked_igpu.watching_game_exit",
                    5000,
                ),
                status(
                    DockedIgpuLifecycleStage.PROMOTION_READY,
                    "docked_igpu.promotion_ready",
                ),
            )
        )
        scheduler = DockedIgpuLifecycleScheduler(lifecycle)
        task = asyncio.create_task(scheduler.run())
        await wait_until(lambda: lifecycle.tick_calls == 1)

        scheduler.wake()
        await wait_until(
            lambda: scheduler.status().stage
            is DockedIgpuLifecycleStage.PROMOTION_READY
        )

        self.assertEqual(
            scheduler.status().stage,
            DockedIgpuLifecycleStage.PROMOTION_READY,
        )
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(lifecycle.close_calls, 1)
        self.assertEqual(
            scheduler.status().stage,
            DockedIgpuLifecycleStage.CLOSED,
        )

    async def test_terminal_state_quiesces_until_explicit_wake(self):
        lifecycle = Lifecycle(
            (
                status(
                    DockedIgpuLifecycleStage.ACTION_REQUIRED,
                    "docked_igpu.game_identity_unverified",
                ),
                status(
                    DockedIgpuLifecycleStage.IDLE,
                    "docked_igpu.action_acknowledged",
                    5000,
                ),
            )
        )
        scheduler = DockedIgpuLifecycleScheduler(lifecycle)
        task = asyncio.create_task(scheduler.run())
        await wait_until(lambda: lifecycle.tick_calls == 1)

        for _ in range(20):
            await asyncio.sleep(0)
        self.assertEqual(lifecycle.tick_calls, 1)

        scheduler.wake()
        await wait_until(lambda: lifecycle.tick_calls == 2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_duplicate_run_is_rejected_and_owner_closes_once(self):
        lifecycle = Lifecycle(
            (
                status(
                    DockedIgpuLifecycleStage.PROMOTION_READY,
                    "docked_igpu.promotion_ready",
                ),
            )
        )
        scheduler = DockedIgpuLifecycleScheduler(lifecycle)
        task = asyncio.create_task(scheduler.run())
        await wait_until(lambda: lifecycle.tick_calls == 1)

        with self.assertRaisesRegex(RuntimeError, "already running"):
            await scheduler.run()

        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(lifecycle.close_calls, 1)

    async def test_acknowledgement_is_forwarded_but_wake_remains_explicit(self):
        lifecycle = Lifecycle(())
        lifecycle.current = status(
            DockedIgpuLifecycleStage.ACTION_REQUIRED,
            "docked_igpu.game_identity_unverified",
        )
        scheduler = DockedIgpuLifecycleScheduler(lifecycle)

        accepted = scheduler.acknowledge_action()

        self.assertTrue(accepted)
        self.assertEqual(lifecycle.acknowledge_calls, 1)
        self.assertEqual(lifecycle.tick_calls, 0)
        self.assertEqual(
            scheduler.status().stage,
            DockedIgpuLifecycleStage.IDLE,
        )


if __name__ == "__main__":
    unittest.main()
