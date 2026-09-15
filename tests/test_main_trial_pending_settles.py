"""A whole-dock trial's pending record must always reach a terminal answer.

Freeing the dock restarts Gaming Mode, which destroys the panel waiting on the
reply. The record that panel wrote outlives the answer, and the control stays
disabled until something retires it. Two ways that used to be never:

- the worker died without writing its terminal payload, because the payload is
  written by an `except Exception` and a BaseException skips it, leaving the
  recorded status busy for the life of the process; and
- the process restarted with the record still on disk, so the reader returned
  `dock_teardown.no_trial` with no request id for a caller to correlate against.

Both now end in a terminal `dock_teardown.trial_unresolved` carrying the request
id. Unresolved, never success: what the device is actually in is read from the
fresh status beside it.
"""
import asyncio
import unittest

from tests.test_main_process_delivery import load_main_module


class TrialPendingSettlesTests(unittest.TestCase):
    def setUp(self):
        self.module = load_main_module(real_dock_gate=True)
        self.plugin = self.module.Plugin.__new__(self.module.Plugin)

    def read(self):
        return asyncio.run(self.plugin.get_egpu_disconnect_status("whole_dock_trial"))

    # ----------------------------------------------------------------- reader

    def test_no_trial_reports_that_nothing_is_running(self):
        # The field a caller needs to distinguish "not started" from "working".
        result = self.read()
        self.assertEqual(result["code"], "dock_teardown.no_trial")
        self.assertIs(result["in_flight"], False)

    def test_a_live_worker_keeps_the_record_waiting(self):
        # Mid-teardown the only safe answer is to keep waiting: the operation
        # really is outstanding and a second dispatch would race it.
        self.plugin._whole_dock_trial_worker_alive = True
        self.plugin._whole_dock_trial_status = {
            "schema_version": 1, "code": "dock_teardown.trial_running",
            "busy": True, "safe_to_unplug": False, "request_id": "r1"}
        result = self.read()
        self.assertIs(result["in_flight"], True)
        self.assertIs(result["busy"], True)
        self.assertEqual(result["code"], "dock_teardown.trial_running")

    def test_a_worker_that_died_without_settling_becomes_terminal(self):
        # The exact wedge: recorded as running, with nothing running it.
        self.plugin._whole_dock_trial_worker_alive = False
        self.plugin._whole_dock_trial_status = {
            "schema_version": 1, "code": "dock_teardown.trial_running",
            "busy": True, "safe_to_unplug": False, "request_id": "r1"}
        result = self.read()
        self.assertEqual(result["code"], "dock_teardown.trial_unresolved")
        self.assertIs(result["busy"], False)
        self.assertIs(result["ok"], False)
        self.assertIs(result["in_flight"], False)
        self.assertIs(result["safe_to_unplug"], False)
        # Correlation survives, or no caller can retire the record it belongs to.
        self.assertEqual(result["request_id"], "r1")

    def test_a_restart_with_no_liveness_attribute_is_also_terminal(self):
        # After a plugin restart the attribute does not exist at all. Absence is
        # not evidence that a teardown is still running.
        self.plugin._whole_dock_trial_status = {
            "schema_version": 1, "code": "dock_teardown.trial_running",
            "busy": True, "safe_to_unplug": False, "request_id": "r1"}
        self.assertEqual(self.read()["code"], "dock_teardown.trial_unresolved")

    def test_the_terminal_rewrite_is_remembered_not_recomputed(self):
        # A later read must agree with the first: a caller that saw unresolved
        # and one that polls a second later must not disagree about what ended.
        self.plugin._whole_dock_trial_status = {
            "schema_version": 1, "code": "dock_teardown.trial_running",
            "busy": True, "safe_to_unplug": False, "request_id": "r1"}
        self.read()
        self.assertEqual(
            self.plugin._whole_dock_trial_status["code"], "dock_teardown.trial_unresolved")
        self.assertEqual(self.read()["code"], "dock_teardown.trial_unresolved")

    def test_a_settled_success_is_never_rewritten(self):
        # Only a busy record with no worker is reinterpreted. A real result
        # stands exactly as the worker wrote it.
        self.plugin._whole_dock_trial_worker_alive = False
        self.plugin._whole_dock_trial_status = {
            "schema_version": 1, "code": "dock_teardown.software_down",
            "busy": False, "ok": True, "software_down": True,
            "safe_to_unplug": False, "request_id": "r1"}
        result = self.read()
        self.assertEqual(result["code"], "dock_teardown.software_down")
        self.assertIs(result["ok"], True)

    def test_a_busy_read_reports_the_live_phase_and_elapsed_time(self):
        # A worker can legitimately wait ~90 s on a session restart. A caller
        # that only ever sees "busy" for that long calls it stuck; the phase and
        # a clock are the difference between "stuck" and "working, step 4".
        import time
        self.plugin._whole_dock_trial_worker_alive = True
        self.plugin._whole_dock_trial_phase = "gpu_release"
        self.plugin._whole_dock_trial_started = time.monotonic() - 42
        self.plugin._whole_dock_trial_status = {
            "schema_version": 1, "code": "dock_teardown.trial_running",
            "busy": True, "safe_to_unplug": False, "request_id": "r1"}
        result = self.read()
        self.assertEqual(result["phase"], "gpu_release")
        self.assertGreaterEqual(result["elapsed_s"], 42)
        self.assertLess(result["elapsed_s"], 60)
        self.assertIs(result["busy"], True)

    def test_progress_fields_never_leak_into_a_terminal_read(self):
        # The terminal payload already carries its own phase; the live clock is
        # for a wait, not a result. Nothing here may make a refusal look alive.
        self.plugin._whole_dock_trial_worker_alive = False
        self.plugin._whole_dock_trial_started = 0.0
        self.plugin._whole_dock_trial_status = {
            "schema_version": 1, "code": "dock_teardown.gpu_release_unverified",
            "busy": False, "ok": False, "safe_to_unplug": False, "request_id": "r1",
            "phase": "gpu_release"}
        result = self.read()
        self.assertNotIn("elapsed_s", result)
        self.assertEqual(result["phase"], "gpu_release")
        self.assertIs(result["in_flight"], False)

    def test_the_dispatch_stamps_the_start_beside_the_busy_record(self):
        import inspect
        source = inspect.getsource(self.module.Plugin.execute_egpu_disconnect)
        busy = source.index('"code": "dock_teardown.trial_running", "busy": True')
        self.assertIn("self._whole_dock_trial_started = time.monotonic()", source[:busy])

    # ----------------------------------------------------------------- worker

    def test_the_shipped_wrapper_clears_liveness_for_a_base_exception(self):
        # The case the terminal payload cannot cover: KeyboardInterrupt and
        # friends skip `except Exception` entirely. Without the finally the
        # status stays busy and the control never recovers. This calls the
        # production wrapper, not a copy of it written here.
        calls = []

        def worker():
            calls.append("ran")
            self.assertIs(self.plugin._whole_dock_trial_worker_alive, True)
            raise KeyboardInterrupt("interpreter going down")

        with self.assertRaises(KeyboardInterrupt):
            self.plugin._watched_trial(worker)
        self.assertEqual(calls, ["ran"])
        self.assertIs(self.plugin._whole_dock_trial_worker_alive, False)

    def test_the_shipped_wrapper_returns_and_clears_on_success(self):
        self.assertEqual(self.plugin._watched_trial(lambda: "result"), "result")
        self.assertIs(self.plugin._whole_dock_trial_worker_alive, False)

    def test_an_abandoned_worker_leaves_a_record_the_reader_settles(self):
        # End to end over production code: a worker that dies the unnamed way,
        # then the read a returning panel makes. Before this the read answered
        # busy for ever and the pending record could never be retired.
        self.plugin._whole_dock_trial_status = {
            "schema_version": 1, "code": "dock_teardown.trial_running",
            "busy": True, "safe_to_unplug": False, "request_id": "r1"}

        def worker():
            raise KeyboardInterrupt("killed mid-teardown")

        with self.assertRaises(KeyboardInterrupt):
            self.plugin._watched_trial(worker)
        result = self.read()
        self.assertEqual(result["code"], "dock_teardown.trial_unresolved")
        self.assertIs(result["busy"], False)
        self.assertEqual(result["request_id"], "r1")

    def test_a_poll_in_the_executor_start_window_keeps_waiting(self):
        # The window between the dispatcher writing the busy record and the
        # executor thread running its first instruction. A poll landing there
        # must see the trial as in flight -- not rewrite it as unresolved and
        # let the control go usable while the teardown is about to run. This
        # stands in for the scheduler with a coroutine that polls BEFORE it
        # runs the worker, which is exactly the ordering the race needs.
        from types import SimpleNamespace as NS
        from unittest.mock import Mock
        self.plugin._background_operations = set()
        self.plugin._unloading = False
        self.plugin._run_whole_dock_trial = Mock(return_value=NS(
            code="dock_teardown.software_down", software_down=True))
        seen = {}

        async def scheduler(operation, *args, **kwargs):
            seen["during"] = await self.plugin.get_egpu_disconnect_status("whole_dock_trial")
            return operation(*args, **kwargs)

        self.plugin._run_background_operation = scheduler

        async def run():
            result = await self.plugin.execute_egpu_disconnect(
                trial_action="whole_dock_disconnect", release_display=True,
                trial_confirmed=True)
            self.assertTrue(result["ok"])
            after = await self.plugin.get_egpu_disconnect_status("whole_dock_trial")
            return after

        after = asyncio.run(run())
        self.assertIs(seen["during"]["in_flight"], True, "alive before the worker's first instruction")
        self.assertIs(seen["during"]["busy"], True)
        self.assertEqual(seen["during"]["code"], "dock_teardown.trial_running")
        # And the real result was never overwritten by a stale unresolved.
        self.assertEqual(after["code"], "dock_teardown.software_down")
        self.assertIs(after["in_flight"], False)

    def test_the_dispatch_runs_the_watched_wrapper(self):
        # Guards the wiring: a wrapper that exists but is not what the dispatch
        # runs would leave the wedge exactly where it was.
        import inspect
        source = inspect.getsource(self.module.Plugin.execute_egpu_disconnect)
        self.assertIn("self._watched_trial(trial)", source)


if __name__ == "__main__":
    unittest.main()
