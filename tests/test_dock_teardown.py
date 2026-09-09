from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from hdm.domain.dock_teardown import (  # noqa: E402
    DockTeardownState,
    TeardownApproval,
    TunnelEvidence,
    UsbBranchEvidence,
    decide_dock_teardown,
)


#: The dock's USB controller as the tested Ally X reports it once the GPU has
#: been software-removed: still enumerated, nothing mounted, nothing plugged in.
USB = UsbBranchEvidence(
    controller_bdf="0000:09:00.0",
    present=True,
    scan_complete=True,
    mounted_storage=(),
    storage_scan_complete=True,
)

#: The G1's Thunderbolt router, authorized and writable.
TUNNEL = TunnelEvidence(
    sysfs_id="0-1", authorized=True, deauthorizable=True, scan_complete=True
)


def approval_for(usb, tunnel):
    """The answer an operator would give having been shown exactly this reading."""
    return TeardownApproval(
        controller_bdf=usb.controller_bdf,
        tunnel_sysfs_id=tunnel.sysfs_id,
        disconnecting=tuple(usb.input_devices) + tuple(usb.other_devices),
    )


def decide(**over):
    request = {
        "usb": USB,
        "tunnel": TUNNEL,
        "gpu_functions_present": (),
        "gpu_scan_complete": True,
    }
    request.update(over)
    # An approval about this exact reading, unless the case supplies its own.
    request.setdefault("approval", approval_for(request["usb"], request["tunnel"]))
    return decide_dock_teardown(**request)


class PermittedTests(unittest.TestCase):
    def test_a_removed_gpu_and_an_idle_branch_may_be_torn_down(self) -> None:
        decision = decide()

        self.assertIs(decision.state, DockTeardownState.PERMITTED)
        self.assertTrue(decision.permitted)

    def test_approval_is_the_last_thing_checked(self) -> None:
        # An operator working a sequence learns the substantive blocker even
        # when it has not approved the step yet.
        decision = decide(approval=None)

        self.assertIs(decision.state, DockTeardownState.APPROVAL_REQUIRED)
        self.assertFalse(decision.permitted)

    def test_a_substantive_refusal_outranks_a_missing_approval(self) -> None:
        decision = decide(approval=None, gpu_functions_present=("0000:08:00.0",))

        self.assertEqual(decision.code, "dock_teardown.gpu_still_attached")

    def test_a_dock_already_down_has_nothing_to_do(self) -> None:
        decision = decide(
            usb=replace(USB, present=False),
            tunnel=replace(TUNNEL, authorized=False),
        )

        self.assertIs(decision.state, DockTeardownState.ALREADY_DOWN)
        self.assertFalse(decision.permitted)


class GpuFirstTests(unittest.TestCase):
    """Deauthorizing the tunnel under a bound GPU is the operation invariant
    10 forbids, reached from software instead of from the cable."""

    def test_a_gpu_still_attached_refuses(self) -> None:
        decision = decide(gpu_functions_present=("0000:08:00.0", "0000:08:00.1"))

        self.assertIs(decision.state, DockTeardownState.REFUSED)
        self.assertEqual(decision.code, "dock_teardown.gpu_still_attached")

    def test_one_function_left_behind_is_still_attached(self) -> None:
        decision = decide(gpu_functions_present=("0000:08:00.1",))

        self.assertEqual(decision.code, "dock_teardown.gpu_still_attached")

    def test_a_gpu_scan_that_did_not_finish_refuses_first_of_all(self) -> None:
        # A teardown that cannot prove the GPU is gone cannot prove it is not
        # a surprise removal.
        decision = decide(gpu_scan_complete=False)

        self.assertEqual(decision.code, "dock_teardown.gpu_scan_incomplete")


class MountedStorageTests(unittest.TestCase):
    """The reason this operation is more dangerous than removing the GPU.

    A lost frame is a lost frame. A filesystem removed with dirty pages
    outstanding is somebody's save files.
    """

    def test_a_mounted_filesystem_refuses_absolutely(self) -> None:
        decision = decide(
            usb=replace(USB, mounted_storage=("/run/media/deck/BACKUP",))
        )

        self.assertIs(decision.state, DockTeardownState.REFUSED)
        self.assertEqual(decision.code, "dock_teardown.mounted_storage")

    def test_the_blocking_mounts_are_named_so_a_player_can_act(self) -> None:
        decision = decide(
            usb=replace(
                USB, mounted_storage=("/run/media/deck/BACKUP", "/run/media/deck/GAMES")
            )
        )

        self.assertEqual(
            decision.blocking_mounts,
            ("/run/media/deck/BACKUP", "/run/media/deck/GAMES"),
        )

    def test_approval_never_overrides_a_mounted_filesystem(self) -> None:
        # Not a warning to click through. Re-Gear does not unmount anything to
        # make a disconnect look possible.
        decision = decide(
            usb=replace(USB, mounted_storage=("/run/media/deck/BACKUP",)),
        )

        self.assertIs(decision.state, DockTeardownState.REFUSED)

    def test_a_storage_scan_that_did_not_finish_is_not_an_empty_branch(self) -> None:
        # The fail-open this codebase has removed more than once. Here it would
        # cost someone their files rather than a prompt.
        decision = decide(usb=replace(USB, storage_scan_complete=False))

        self.assertEqual(decision.code, "dock_teardown.storage_scan_incomplete")

    def test_an_empty_mount_list_from_a_finished_scan_is_evidence(self) -> None:
        decision = decide(
            usb=replace(USB, mounted_storage=(), storage_scan_complete=True)
        )

        self.assertTrue(decision.permitted)

    def test_storage_on_a_branch_already_gone_cannot_block(self) -> None:
        # Nothing is mounted on a controller that is no longer enumerated; a
        # stale reading must not deadlock the second half of the teardown.
        decision = decide(
            usb=replace(
                USB,
                present=False,
                mounted_storage=("/run/media/deck/STALE",),
                storage_scan_complete=False,
            )
        )

        self.assertTrue(decision.permitted)


class StorageInUseTests(unittest.TestCase):
    """Unmounted is not unused, and the difference costs files.

    A drive can be written to with no mount in sight: swap on it, a stacked
    device over it, or a filesystem mounted in a container's own namespace.
    """

    def test_swap_on_the_branch_refuses(self) -> None:
        decision = decide(
            usb=replace(USB, storage_in_use=("sda2: in use as swap",))
        )

        self.assertIs(decision.state, DockTeardownState.REFUSED)
        self.assertEqual(decision.code, "dock_teardown.storage_in_use")

    def test_a_stacked_device_refuses(self) -> None:
        decision = decide(usb=replace(USB, storage_in_use=("sda: in use by dm-0",)))

        self.assertEqual(decision.code, "dock_teardown.storage_in_use")

    def test_the_blocking_uses_are_named_so_a_player_can_act(self) -> None:
        decision = decide(
            usb=replace(
                USB, storage_in_use=("sda2: in use as swap", "sdb: in use by md0")
            )
        )

        self.assertEqual(
            decision.blocking_uses,
            ("sda2: in use as swap", "sdb: in use by md0"),
        )

    def test_approval_never_overrides_a_device_in_use(self) -> None:
        decision = decide(
            usb=replace(USB, storage_in_use=("sda: in use by dm-0",))
        )

        self.assertIs(decision.state, DockTeardownState.REFUSED)

    def test_a_mount_is_reported_under_its_own_code(self) -> None:
        # "Unmount it" is not the instruction that clears swap, so the two
        # blockers do not share a code.
        mounted = decide(usb=replace(USB, mounted_storage=("/run/media/deck/A",)))
        in_use = decide(usb=replace(USB, storage_in_use=("sda: in use by dm-0",)))

        self.assertNotEqual(mounted.code, in_use.code)

    def test_a_mount_carries_the_other_uses_alongside_it(self) -> None:
        # So a player clearing the mount also learns what else is holding it.
        decision = decide(
            usb=replace(
                USB,
                mounted_storage=("/run/media/deck/A",),
                storage_in_use=("sda2: in use as swap",),
            )
        )

        self.assertEqual(decision.blocking_mounts, ("/run/media/deck/A",))
        self.assertEqual(decision.blocking_uses, ("sda2: in use as swap",))

    def test_use_on_a_branch_already_gone_cannot_block(self) -> None:
        decision = decide(
            usb=replace(
                USB,
                present=False,
                storage_in_use=("sda: stale",),
                storage_scan_complete=False,
            )
        )

        self.assertTrue(decision.permitted)


class TunnelTests(unittest.TestCase):
    def test_an_unidentified_tunnel_refuses(self) -> None:
        decision = decide(tunnel=replace(TUNNEL, sysfs_id=""))

        self.assertEqual(decision.code, "dock_teardown.tunnel_unidentified")

    def test_an_unreadable_authorized_flag_is_not_a_tunnel_that_is_down(self) -> None:
        # Reporting a dock as detached on the strength of a file that could not
        # be read is the whole failure mode this feature has to avoid.
        decision = decide(tunnel=replace(TUNNEL, authorized=None))

        self.assertEqual(decision.code, "dock_teardown.tunnel_state_unknown")

    def test_a_tunnel_that_cannot_be_brought_down_refuses_before_anything_else(
        self,
    ) -> None:
        # Discovering this afterwards leaves a player with no dock USB, no
        # clearance, and a recovery to perform.
        decision = decide(tunnel=replace(TUNNEL, deauthorizable=False))

        self.assertEqual(decision.code, "dock_teardown.tunnel_not_deauthorizable")

    def test_a_tunnel_scan_that_did_not_finish_refuses(self) -> None:
        decision = decide(tunnel=replace(TUNNEL, scan_complete=False))

        self.assertEqual(decision.code, "dock_teardown.tunnel_scan_incomplete")

    def test_a_tunnel_already_down_needs_no_write_permission(self) -> None:
        # Nothing left to deauthorize, so being unable to is not a blocker.
        decision = decide(
            usb=replace(USB, present=False),
            tunnel=replace(TUNNEL, authorized=False, deauthorizable=False),
        )

        self.assertIs(decision.state, DockTeardownState.ALREADY_DOWN)


class ConsequenceTests(unittest.TestCase):
    """What disconnects is reported, not refused. It is the player's call."""

    def test_devices_that_will_disconnect_travel_with_every_decision(self) -> None:
        usb = replace(
            USB,
            input_devices=("Xbox Wireless Controller",),
            other_devices=("USB Audio", "Realtek Ethernet"),
        )

        decision = decide(usb=usb)

        self.assertEqual(
            decision.disconnecting,
            ("Xbox Wireless Controller", "USB Audio", "Realtek Ethernet"),
        )
        self.assertTrue(decision.permitted)

    def test_a_controller_on_the_dock_is_not_a_blocker(self) -> None:
        # It will disconnect and the player must be told, but the handheld's
        # built-in controller survives, so they keep control of the machine.
        decision = decide(
            usb=replace(USB, input_devices=("Xbox Wireless Controller",))
        )

        self.assertTrue(decision.permitted)

    def test_consequences_are_reported_even_when_refusing(self) -> None:
        # So a player deciding whether to unmount knows what else it costs.
        decision = decide(
            usb=replace(
                USB,
                mounted_storage=("/run/media/deck/BACKUP",),
                input_devices=("Xbox Wireless Controller",),
            )
        )

        self.assertIs(decision.state, DockTeardownState.REFUSED)
        self.assertEqual(decision.disconnecting, ("Xbox Wireless Controller",))


class ClaimTests(unittest.TestCase):
    """Producing a permitted decision authorises one bounded teardown.

    Whether an unplug may follow is issue #147 and the owner's decision. This
    function must not be readable as having made it, so nothing it returns
    mentions the cable at all.
    """

    def test_no_code_this_function_emits_mentions_unplugging(self) -> None:
        decisions = [
            decide(),
            decide(approval=None),
            decide(approval=approval_for(USB, replace(TUNNEL, sysfs_id="0-9"))),
            decide(gpu_scan_complete=False),
            decide(gpu_functions_present=("0000:08:00.0",)),
            decide(tunnel=replace(TUNNEL, sysfs_id="")),
            decide(tunnel=replace(TUNNEL, authorized=None)),
            decide(tunnel=replace(TUNNEL, deauthorizable=False)),
            decide(tunnel=replace(TUNNEL, scan_complete=False)),
            decide(usb=replace(USB, scan_complete=False)),
            decide(usb=replace(USB, storage_scan_complete=False)),
            decide(usb=replace(USB, mounted_storage=("/run/media/deck/X",))),
            decide(
                usb=replace(USB, present=False),
                tunnel=replace(TUNNEL, authorized=False),
            ),
        ]

        for decision in decisions:
            for word in ("unplug", "cable", "safe_to_remove", "disconnect_cable"):
                self.assertNotIn(word, decision.code, decision.code)

    def test_every_state_is_reachable_and_carries_a_distinct_code(self) -> None:
        # A state with no code of its own would report a teardown as refused
        # without saying which fact refused it.
        codes = {
            decide().code,
            decide(approval=None).code,
            decide(gpu_functions_present=("0000:08:00.0",)).code,
            decide(
                usb=replace(USB, present=False),
                tunnel=replace(TUNNEL, authorized=False),
            ).code,
        }

        self.assertEqual(len(codes), 4)


class ApprovalBindingTests(unittest.TestCase):
    """An approval is an answer about one reading, not a standing permission.

    Every substantive fact is re-read on each decision, so a stale answer can
    never outvote one. What binding adds is that an answer cannot quietly
    transfer to a *different* teardown that happens to also be permitted.
    """

    def test_an_answer_about_another_dock_does_not_carry_over(self) -> None:
        # Same cable, different dock. Every fact still permits, and it is still
        # not the teardown anybody agreed to.
        other = replace(USB, controller_bdf="0000:0c:00.0")

        decision = decide(usb=other, approval=approval_for(USB, TUNNEL))

        self.assertIs(decision.state, DockTeardownState.APPROVAL_REQUIRED)
        self.assertEqual(decision.code, "dock_teardown.approval_superseded")
        self.assertFalse(decision.permitted)

    def test_an_answer_about_another_tunnel_does_not_carry_over(self) -> None:
        decision = decide(approval=approval_for(USB, replace(TUNNEL, sysfs_id="0-9")))

        self.assertEqual(decision.code, "dock_teardown.approval_superseded")

    def test_an_answer_shown_different_consequences_does_not_carry_over(self) -> None:
        # The operator agreed knowing a keyboard would drop. A headset has
        # since appeared on the branch, so they were shown a different list
        # than the one that would now happen.
        agreed = replace(USB, input_devices=("Keyboard",))
        now = replace(USB, input_devices=("Keyboard",), other_devices=("Headset",))

        decision = decide(usb=now, approval=approval_for(agreed, TUNNEL))

        self.assertEqual(decision.code, "dock_teardown.approval_superseded")
        self.assertEqual(decision.disconnecting, ("Keyboard", "Headset"))

    def test_the_matching_answer_still_permits(self) -> None:
        now = replace(USB, input_devices=("Keyboard",), other_devices=("Headset",))

        decision = decide(usb=now, approval=approval_for(now, TUNNEL))

        self.assertIs(decision.state, DockTeardownState.PERMITTED)

    def test_never_answered_and_answered_about_something_else_are_distinct(self) -> None:
        # Downstream must be able to tell "you have not been asked" from
        # "things changed since you answered".
        missing = decide(approval=None).code
        superseded = decide(
            approval=approval_for(USB, replace(TUNNEL, sysfs_id="0-9"))
        ).code

        self.assertNotEqual(missing, superseded)
        self.assertEqual(missing, "dock_teardown.approval_required")

    def test_a_substantive_refusal_still_outranks_a_superseded_answer(self) -> None:
        # Binding must not reorder the refusals. A mounted filesystem is the
        # answer, not a stale approval, because unmounting is what the player
        # has to do either way.
        decision = decide(
            usb=replace(USB, mounted_storage=("/run/media/deck/BACKUP",)),
            approval=approval_for(USB, replace(TUNNEL, sysfs_id="0-9")),
        )

        self.assertIs(decision.state, DockTeardownState.REFUSED)
        self.assertEqual(decision.code, "dock_teardown.mounted_storage")


if __name__ == "__main__":
    unittest.main()
