from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.application.filter_arm import (  # noqa: E402
    FilterArmCoordinator,
    HolderObservation,
)
from regear.application.live_disconnect import (  # noqa: E402
    FreshRemovalObservation,
    LiveDisconnectService,
    LiveDisconnectStage,
)
from regear.domain.device_removal import (  # noqa: E402
    RemovalFunction,
    RemovalFunctionKind,
)
from regear.domain.filter_arm_sequence import SESSION_TARGET  # noqa: E402
from regear.domain.filter_authorization import (  # noqa: E402
    CgroupIdentity,
    OwnerIdentity,
    authorize_parent_scope,
)
from regear.domain.display_release import DisplayReleaseEvidence  # noqa: E402
from regear.domain.removal_safety import RemovalSafety, RemovalSafetyState  # noqa: E402
from regear.domain.removal_transaction import (  # noqa: E402
    FunctionProgress,
    record_progress,
)
from regear.domain.removal_transaction import plan as plan_transaction  # noqa: E402
from regear.domain.safe_undock_readiness import SafeUndockRevalidation  # noqa: E402
from regear.ports.device_filter import (  # noqa: E402
    ArmedFilter,
    ArmOutcome,
    ArmResult,
    DisarmOutcome,
    DisarmResult,
)
from regear.ports.display_release import (  # noqa: E402
    DisplayReleaseOutcome,
    DisplayReleaseResult,
)
from regear.ports.device_removal import (  # noqa: E402
    RemovalOutcome,
    RemovalResult,
    RescanOutcome,
    RescanResult,
)


UID = 1000
MANAGER = f"/sys/fs/cgroup/user.slice/user-{UID}.slice/user@{UID}.service"
BOOT = "a" * 64
CGROUP = CgroupIdentity(MANAGER, 30, 5561)
FILTER = ArmedFilter(program_id=444, link_id=6, cgroup_id=5561)
PROGRAM = b"\x00" * 312
HOLDERS = ("gamescope-session.service", "steam-launcher.service", "wireplumber.service")

GPU = "0000:08:00.0"
AUDIO = "0000:08:00.1"
BOTH = (GPU, AUDIO)
#: The plan orders the audio function first, so this is the order of the writes.
PLAN_ORDER = (AUDIO, GPU)
FUNCTIONS = (
    RemovalFunction(RemovalFunctionKind.GPU, GPU),
    RemovalFunction(RemovalFunctionKind.AUDIO, AUDIO),
)

BINDING = "egpu-stable-id"
GENERATION = "generation"


def grant():
    return authorize_parent_scope(
        cgroup=CGROUP,
        uid=UID,
        session_uid=UID,
        owner=OwnerIdentity(1844, 99001),
        boot_hash=BOOT,
        attachment_binding=BINDING,
        generation=GENERATION,
        sample_id="sample",
        deadline=1000.0,
    )


def ready(binding: str = BINDING, generation: str = GENERATION):
    return FreshRemovalObservation(
        RemovalSafety(
            RemovalSafetyState.READY_FOR_SUPERVISED_REMOVAL,
            "removal_safety.ready_for_supervised_removal",
            SafeUndockRevalidation(binding, generation, "sample"),
        ),
        binding,
        generation,
    )


def blocked(code: str = "removal_safety.external_display_still_active"):
    return FreshRemovalObservation(
        RemovalSafety(RemovalSafetyState.NOT_READY, code), BINDING, GENERATION
    )


def prior_transaction():
    return plan_transaction(
        owner_id="regear", device_set=BINDING, addresses=PLAN_ORDER, now_ns=1
    )


class FakeFilter:
    def __init__(self, *, arm_ok=True, enforcing=True) -> None:
        self._arm_ok = arm_ok
        self.enforcing = enforcing
        self.armed = False
        self.disarm_calls = 0

    def arm(self, program, cgroup):
        if not self._arm_ok:
            return ArmResult(ArmOutcome.ATTACH_FAILED, code="fake.attach_failed")
        self.armed = True
        return ArmResult(ArmOutcome.ARMED, FILTER)

    def enforced(self, cgroup, program_id):
        return self.enforcing

    def disarm(self):
        self.disarm_calls += 1
        self.armed = False
        return DisarmResult(DisarmOutcome.DISARMED)


class FakeRemoval:
    def __init__(self, events, *, fails=(), rescan_ok=True) -> None:
        self._events = events
        self._fails = {address.lower() for address in fails}
        self._rescan_ok = rescan_ok
        self.rescans: list[tuple[str, ...]] = []

    @property
    def detached(self) -> tuple[str, ...]:
        return tuple(event[1] for event in self._events if event[0] == "remove")

    def remove(self, address):
        self._events.append(("remove", address))
        if address.lower() in self._fails:
            return RemovalResult(
                address, RemovalOutcome.STILL_PRESENT, "fake.still_present"
            )
        return RemovalResult(address, RemovalOutcome.REMOVED)

    def rescan(self, expected):
        self._events.append(("rescan", expected))
        self.rescans.append(expected)
        if not self._rescan_ok:
            return RescanResult(RescanOutcome.FAILED, code="fake.rescan_failed")
        return RescanResult(RescanOutcome.RESTORED, expected)


class FakeStore:
    def __init__(self, events, *, record=None, load_raises=False, fail_save=None) -> None:
        self._events = events
        self.record = record
        self._load_raises = load_raises
        self._fail_save = fail_save
        self.saves = 0
        self.cleared = 0

    def load(self):
        if self._load_raises:
            raise ValueError("fake.unreadable")
        return self.record

    def save(self, record):
        self.saves += 1
        self._events.append(("save", record.state.value))
        if self._fail_save == self.saves:
            raise OSError("fake.save_failed")
        self.record = record

    def clear(self):
        self.cleared += 1
        self._events.append(("clear",))
        self.record = None


#: No committed external mode, so most tests take no display step at all.
NO_DISPLAY = DisplayReleaseEvidence(
    external_committed=(),
    external_complete=True,
    internal_committed=True,
    client_holders=(),
    client_scan_complete=True,
)
#: The tested hardware after the return: the eGPU still driving CRTC 98.
DISPLAY_HELD = DisplayReleaseEvidence(
    external_committed=(98,),
    external_complete=True,
    internal_committed=True,
    client_holders=(),
    client_scan_complete=True,
)


class FakeHeld:
    def __init__(self, events, released) -> None:
        self._events = events
        self.released = released
        self.held = True

    def still_released(self):
        return self.held

    def restore(self):
        if self.held:
            self._events.append(("display_restore",))
            self.held = False


class FakeDisplayRelease:
    def __init__(self, events, *, fails=False) -> None:
        self._events = events
        self._fails = fails
        self.handles = []

    def release(self, node, crtcs):
        self._events.append(("display_release", crtcs))
        if self._fails:
            return (
                DisplayReleaseResult(
                    DisplayReleaseOutcome.STILL_COMMITTED, "fake.still_committed"
                ),
                None,
            )
        handle = FakeHeld(self._events, crtcs)
        self.handles.append(handle)
        return (
            DisplayReleaseResult(
                DisplayReleaseOutcome.RELEASED, "display_release.released", crtcs
            ),
            handle,
        )


class Harness:
    """One assembled service with every collaborator faked and observable."""

    def __init__(
        self,
        *,
        observations=None,
        present=None,
        arm_ok=True,
        holders=(HOLDERS, ()),
        scan_complete=True,
        fails=(),
        rescan_ok=True,
        record=None,
        load_raises=False,
        fail_save=None,
        lose_enforcement=False,
        display=NO_DISPLAY,
        display_fails=False,
    ) -> None:
        self.events: list[tuple] = []
        self.filter = FakeFilter(arm_ok=arm_ok)
        self.removal = FakeRemoval(self.events, fails=fails, rescan_ok=rescan_ok)
        self.display = FakeDisplayRelease(self.events, fails=display_fails)
        self._display_evidence = display
        self.store = FakeStore(
            self.events, record=record, load_raises=load_raises, fail_save=fail_save
        )
        self._observations = list(observations or [ready()])
        self._present = list(present or [()])
        self._lose_enforcement = lose_enforcement
        self.restarted: list[str] = []

        holder_scans = list(holders)

        def observe_holders():
            units = holder_scans.pop(0) if len(holder_scans) > 1 else holder_scans[0]
            return HolderObservation(tuple(units), scan_complete)

        def restart(unit):
            self.restarted.append(unit)
            if self._lose_enforcement and unit == SESSION_TARGET:
                # The coordinator re-checks enforcement before each restart, so
                # dropping it after the last one leaves exactly one caller
                # affected: the service's own check before the first write.
                self.filter.enforcing = False
            return True

        self.service = LiveDisconnectService(
            coordinator=FilterArmCoordinator(
                device_filter=self.filter,
                restart=restart,
                observe_holders=observe_holders,
                observe_cgroup=lambda: CGROUP,
                monotonic=lambda: 1.0,
            ),
            device_filter=self.filter,
            removal=self.removal,
            display_release=self.display,
            store=self.store,
            observe=self._next_observation,
            observe_display=lambda: self._display_evidence,
            display_node="/dev/dri/card1",
            present_addresses=self._next_present,
            removal_functions=lambda: FUNCTIONS,
            now_ns=lambda: 1_700_000_000_000_000_000,
            owner_id="regear",
            device_set=BINDING,
        )

    def _next_observation(self):
        if len(self._observations) > 1:
            return self._observations.pop(0)
        return self._observations[0]

    def _next_present(self):
        if len(self._present) > 1:
            return self._present.pop(0)
        return tuple(self._present[0])

    def run(self, release_display=True):
        return self.service.disconnect(
            grant(), PROGRAM, boot_hash=BOOT, release_display=release_display
        )

    @property
    def detached(self) -> tuple[str, ...]:
        return self.removal.detached


class HardwareBlockerTests(unittest.TestCase):
    """The state the tested hardware actually reaches."""

    def test_a_released_device_still_driving_a_display_refuses_and_removes_nothing(
        self,
    ) -> None:
        """The measured outcome on 0.3.60: holders clear, display still held.

        This must read as a successful release that is blocked by something
        else, not as a failed release, because the two send someone to fix
        different things.
        """
        harness = Harness(observations=[blocked()])
        result = harness.run()

        self.assertIs(result.stage, LiveDisconnectStage.NOT_SAFE_AFTER_RELEASE)
        self.assertEqual(result.code, "removal_safety.external_display_still_active")
        self.assertTrue(result.released)
        self.assertFalse(result.ok)
        self.assertEqual(harness.detached, ())
        self.assertEqual(harness.store.saves, 0)
        self.assertTrue(result.filter_disarmed)
        self.assertFalse(harness.filter.armed)


class ReleaseTests(unittest.TestCase):
    def test_a_refused_release_never_consults_readiness_or_removes(self) -> None:
        harness = Harness(arm_ok=False, observations=[ready()])
        result = harness.run()

        self.assertIs(result.stage, LiveDisconnectStage.RELEASE_REFUSED)
        self.assertFalse(result.released)
        self.assertFalse(result.session_disturbed)
        self.assertEqual(harness.detached, ())

    def test_remaining_holders_stop_the_sequence_before_any_removal(self) -> None:
        harness = Harness(holders=(HOLDERS, HOLDERS), observations=[ready()])
        result = harness.run()

        self.assertIs(result.stage, LiveDisconnectStage.HOLDERS_REMAIN)
        self.assertEqual(harness.detached, ())

    def test_an_incomplete_scan_is_not_a_clear_device(self) -> None:
        harness = Harness(scan_complete=False, observations=[ready()])
        result = harness.run()

        self.assertIs(result.stage, LiveDisconnectStage.RELEASE_REFUSED)
        self.assertEqual(harness.detached, ())


class RevalidationTests(unittest.TestCase):
    """What must still hold at the moment of the write, not merely earlier."""

    def test_a_different_device_at_the_write_stops_the_removal(self) -> None:
        harness = Harness(observations=[ready(), ready(binding="another-egpu")])
        result = harness.run()

        self.assertIs(result.stage, LiveDisconnectStage.IDENTITY_CHANGED)
        self.assertTrue(result.released)
        self.assertEqual(harness.detached, ())
        self.assertEqual(harness.store.saves, 0)

    def test_a_different_device_set_at_the_write_stops_the_removal(self) -> None:
        harness = Harness(observations=[ready(), ready(generation="later")])
        self.assertIs(harness.run().stage, LiveDisconnectStage.IDENTITY_CHANGED)
        self.assertEqual(harness.detached, ())

    def test_readiness_that_lapses_after_the_decision_stops_the_removal(self) -> None:
        """The deciding verdict describes when it was taken, not the write."""
        harness = Harness(observations=[ready(), blocked("removal_safety.game_running")])
        result = harness.run()

        self.assertIs(result.stage, LiveDisconnectStage.READINESS_LAPSED)
        self.assertEqual(result.code, "removal_safety.game_running")
        self.assertEqual(harness.detached, ())

    def test_losing_enforcement_before_the_write_stops_the_removal(self) -> None:
        """The device is only clear while the filter that emptied it holds."""
        harness = Harness(observations=[ready(), ready()], lose_enforcement=True)
        result = harness.run()

        self.assertIs(result.stage, LiveDisconnectStage.ENFORCEMENT_LOST)
        self.assertTrue(result.released)
        self.assertEqual(harness.detached, ())
        self.assertEqual(harness.store.saves, 0)

    def test_a_record_that_cannot_be_stored_stops_before_the_first_write(self) -> None:
        harness = Harness(observations=[ready(), ready()], fail_save=1)
        result = harness.run()

        self.assertIs(result.stage, LiveDisconnectStage.RECORD_FAILED)
        self.assertEqual(harness.detached, ())


class RemovalTests(unittest.TestCase):
    def test_a_complete_removal_records_before_each_write_and_clears_at_the_end(
        self,
    ) -> None:
        """Ordering is the property, not merely that a record exists.

        The record has to reach stable storage before the detach it describes,
        because the crash this survives happens between the two writes to the
        bus.
        """
        harness = Harness(observations=[ready(), ready()], present=[(), ()])
        result = harness.run()

        self.assertIs(result.stage, LiveDisconnectStage.REMOVED)
        self.assertTrue(result.ok)
        self.assertEqual(result.removed, PLAN_ORDER)
        self.assertEqual(
            harness.events,
            [
                ("save", "planned"),
                ("remove", AUDIO),
                ("save", "in_progress"),
                ("remove", GPU),
                ("save", "complete"),
                ("clear",),
            ],
        )
        self.assertTrue(result.filter_disarmed)
        self.assertFalse(harness.filter.armed)

    def test_a_function_that_does_not_detach_restores_rather_than_continues(
        self,
    ) -> None:
        harness = Harness(observations=[ready(), ready()], fails=(AUDIO,))
        result = harness.run()

        self.assertIs(result.stage, LiveDisconnectStage.REMOVAL_INCOMPLETE)
        self.assertEqual(result.code, "fake.still_present")
        self.assertEqual(result.removed, ())
        # The second function is never attempted, and the restore covers
        # everything the transaction intended rather than what it believes.
        self.assertEqual(harness.detached, (AUDIO,))
        self.assertEqual(harness.removal.rescans, [PLAN_ORDER])
        self.assertEqual(result.restored, PLAN_ORDER)
        self.assertFalse(result.device_disturbed)
        self.assertIsNone(harness.store.record)

    def test_a_failed_restore_keeps_the_record_and_reports_a_disturbed_device(
        self,
    ) -> None:
        harness = Harness(
            observations=[ready(), ready()], fails=(GPU,), rescan_ok=False
        )
        result = harness.run()

        self.assertIs(result.stage, LiveDisconnectStage.REMOVAL_UNRECOVERABLE)
        self.assertTrue(result.device_disturbed)
        # The record is the only evidence of where the device actually is.
        self.assertIsNotNone(harness.store.record)
        self.assertEqual(harness.store.cleared, 0)
        self.assertTrue(result.filter_disarmed)

    def test_a_removal_the_bus_does_not_confirm_is_not_a_removal(self) -> None:
        """Both detaches report success and a function is still enumerated.

        A claim this process recorded is not evidence; the bus is asked
        separately and disagreeing with it restores rather than reports done.
        """
        harness = Harness(observations=[ready(), ready()], present=[(GPU,)])
        result = harness.run()

        self.assertIs(result.stage, LiveDisconnectStage.REMOVAL_INCOMPLETE)
        self.assertEqual(result.code, "live_disconnect.function_still_present")
        self.assertEqual(harness.removal.rescans, [PLAN_ORDER])

    def test_progress_that_cannot_be_recorded_stops_and_restores(self) -> None:
        """The detach landed and the record is behind, so it cannot continue.

        Recovery still works -- the intended set was stored before the first
        write and `reconcile` reads the bus -- but a sequence that can no
        longer record what it does next must not do anything else.
        """
        harness = Harness(observations=[ready(), ready()], fail_save=2)
        result = harness.run()

        self.assertIs(result.stage, LiveDisconnectStage.REMOVAL_INCOMPLETE)
        self.assertEqual(result.code, "live_disconnect.progress_not_recorded")
        self.assertEqual(harness.detached, (AUDIO,))
        self.assertEqual(harness.removal.rescans, [PLAN_ORDER])

    def test_the_filter_is_disarmed_even_when_the_removal_raises(self) -> None:
        harness = Harness(observations=[ready(), ready()])
        harness.removal.remove = lambda address: (_ for _ in ()).throw(
            OSError("bus exploded")
        )
        with self.assertRaises(OSError):
            harness.run()
        self.assertFalse(harness.filter.armed)
        self.assertEqual(harness.filter.disarm_calls, 1)



class DisplayReleaseTests(unittest.TestCase):
    """The step that unblocked #168 on the tested hardware."""

    def test_the_display_is_released_before_the_assessment_and_given_back_after(
        self,
    ) -> None:
        """Held across both.

        An assessment taken while the display was down, acted on after it came
        back, would describe a moment that no longer exists.
        """
        harness = Harness(
            observations=[ready(), ready()], present=[(), ()], display=DISPLAY_HELD
        )
        result = harness.run()

        self.assertIs(result.stage, LiveDisconnectStage.REMOVED)
        self.assertEqual(result.display_released, (98,))
        self.assertEqual(
            harness.events,
            [
                ("display_release", (98,)),
                ("save", "planned"),
                ("remove", AUDIO),
                ("save", "in_progress"),
                ("remove", GPU),
                ("save", "complete"),
                ("clear",),
                ("display_restore",),
            ],
        )

    def test_a_card_driving_nothing_takes_no_display_step(self) -> None:
        harness = Harness(observations=[ready(), ready()], present=[(), ()])
        result = harness.run()

        self.assertIs(result.stage, LiveDisconnectStage.REMOVED)
        self.assertEqual(result.display_released, ())
        self.assertEqual(
            result.display_release_code, "display_release.not_driving_a_display"
        )
        self.assertEqual(harness.display.handles, [])

    def test_without_approval_no_display_is_touched_and_the_sequence_continues(
        self,
    ) -> None:
        """Turning an output off is a separate authority from removing a device."""
        harness = Harness(observations=[blocked()], display=DISPLAY_HELD)
        result = harness.run(release_display=False)

        self.assertEqual(result.display_release_code, "display_release.not_approved")
        self.assertEqual(harness.display.handles, [])
        self.assertIs(result.stage, LiveDisconnectStage.NOT_SAFE_AFTER_RELEASE)
        self.assertEqual(result.code, "removal_safety.external_display_still_active")

    def test_a_refused_release_is_not_fatal_and_readiness_still_names_the_blocker(
        self,
    ) -> None:
        """This enables a removal; it does not gate one.

        A client holding the card refuses the release, and the sequence gives
        the same answer it gave before this step existed.
        """
        evidence = replace(DISPLAY_HELD, client_holders=("gamescope-session.service",))
        harness = Harness(observations=[blocked()], display=evidence)
        result = harness.run()

        self.assertIs(result.stage, LiveDisconnectStage.NOT_SAFE_AFTER_RELEASE)
        self.assertEqual(result.code, "removal_safety.external_display_still_active")
        self.assertEqual(
            result.display_release_code, "display_release.client_holds_the_card"
        )
        self.assertEqual(harness.display.handles, [])

    def test_a_release_that_fails_is_not_fatal_either(self) -> None:
        harness = Harness(
            observations=[blocked()], display=DISPLAY_HELD, display_fails=True
        )
        result = harness.run()

        self.assertIs(result.stage, LiveDisconnectStage.NOT_SAFE_AFTER_RELEASE)
        self.assertEqual(result.display_release_code, "fake.still_committed")
        self.assertEqual(result.display_released, ())

    def test_the_display_is_given_back_when_the_removal_refuses(self) -> None:
        harness = Harness(
            observations=[ready(), ready()],
            display=DISPLAY_HELD,
            lose_enforcement=True,
        )
        result = harness.run()

        self.assertIs(result.stage, LiveDisconnectStage.ENFORCEMENT_LOST)
        self.assertEqual(harness.events[-1], ("display_restore",))
        self.assertFalse(harness.display.handles[0].held)

    def test_the_display_is_given_back_when_the_removal_raises(self) -> None:
        harness = Harness(observations=[ready(), ready()], display=DISPLAY_HELD)
        harness.removal.remove = lambda address: (_ for _ in ()).throw(
            OSError("bus exploded")
        )
        with self.assertRaises(OSError):
            harness.run()

        self.assertFalse(harness.display.handles[0].held)
        self.assertFalse(harness.filter.armed)


class RecoveryTests(unittest.TestCase):
    """A record found at the start is settled before anything new is tried."""

    def test_a_half_detached_device_is_restored_and_nothing_new_is_attempted(
        self,
    ) -> None:
        record = record_progress(prior_transaction(), AUDIO, FunctionProgress.REMOVED)
        harness = Harness(record=record, present=[(GPU,)], observations=[ready()])
        result = harness.run()

        self.assertIs(result.stage, LiveDisconnectStage.RECOVERED_PRIOR_REMOVAL)
        self.assertEqual(result.code, "removal_transaction.partially_detached")
        self.assertFalse(result.released)
        # Restore everything intended, not only what the record believes gone.
        self.assertEqual(harness.removal.rescans, [PLAN_ORDER])
        self.assertEqual(harness.restarted, [])
        self.assertFalse(harness.filter.armed)
        self.assertIsNone(harness.store.record)

    def test_a_half_detached_device_that_will_not_restore_keeps_its_record(
        self,
    ) -> None:
        record = record_progress(prior_transaction(), AUDIO, FunctionProgress.REMOVED)
        harness = Harness(
            record=record, present=[(GPU,)], rescan_ok=False, observations=[ready()]
        )
        result = harness.run()

        self.assertIs(result.stage, LiveDisconnectStage.RECOVERY_FAILED)
        self.assertTrue(result.device_disturbed)
        self.assertIsNotNone(harness.store.record)
        self.assertEqual(harness.store.cleared, 0)

    def test_an_unreadable_record_refuses_without_arming_anything(self) -> None:
        harness = Harness(load_raises=True, observations=[ready()])
        result = harness.run()

        self.assertIs(result.stage, LiveDisconnectStage.RECORD_UNREADABLE)
        self.assertEqual(harness.restarted, [])
        self.assertEqual(harness.detached, ())
        self.assertFalse(harness.filter.armed)

    def test_a_record_whose_removal_never_started_is_cleared_and_the_run_continues(
        self,
    ) -> None:
        harness = Harness(
            record=prior_transaction(),
            present=[BOTH, ()],
            observations=[ready(), ready()],
        )
        result = harness.run()

        self.assertIs(result.stage, LiveDisconnectStage.REMOVED)
        self.assertEqual(harness.events[0], ("clear",))

    def test_a_removal_that_already_completed_reports_it_and_does_not_repeat_it(
        self,
    ) -> None:
        record = record_progress(prior_transaction(), AUDIO, FunctionProgress.REMOVED)
        record = record_progress(record, GPU, FunctionProgress.REMOVED)
        harness = Harness(record=record, present=[()], observations=[ready()])
        result = harness.run()

        self.assertIs(result.stage, LiveDisconnectStage.PRIOR_REMOVAL_COMPLETE)
        self.assertEqual(harness.detached, ())
        self.assertEqual(harness.removal.rescans, [])
        self.assertIsNone(harness.store.record)


if __name__ == "__main__":
    unittest.main()
