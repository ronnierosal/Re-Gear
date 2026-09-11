import unittest
from dataclasses import replace

from regear.application.whole_dock_teardown import WholeDockTeardown
from regear.domain.dock_teardown import (
    TeardownApproval, TunnelCapability, TunnelEvidence, UsbBranchEvidence,
    WritePermission,
)
from regear.ports.whole_dock_teardown import DockObservation


def observation():
    return DockObservation(
        "attachment", "generation",
        UsbBranchEvidence("usb-controller", True, True, storage_scan_complete=True),
        TunnelEvidence("router", True, TunnelCapability.SUPPORTED,
                       WritePermission.WRITABLE, True),
        (), True, True, True,
    )


class Port:
    def __init__(self):
        self.current = observation()
        self.owned = False
        self.events = []
        self.reads = 0
        self.change = lambda value, count: value
        self.fail_stage = None
        self.timeout = False

    def observe(self):
        self.reads += 1
        return self.change(self.current, self.reads)

    def claim(self, operation, current):
        if self.owned:
            return False
        self.owned = True
        self.events.append("claim")
        return True

    def record(self, operation, stage):
        if stage == self.fail_stage:
            raise OSError("journal unavailable")
        self.events.append(stage)

    def remove_usb(self, current):
        self.events.append("remove_usb")
        if self.timeout:
            raise TimeoutError()
        self.current = replace(self.current, usb=replace(self.current.usb, present=False))

    def deauthorize(self, current):
        self.events.append("deauthorize")
        self.current = replace(self.current, tunnel=replace(self.current.tunnel, authorized=False))


class WholeDockTests(unittest.TestCase):
    def setUp(self):
        self.port = Port()
        self.service = WholeDockTeardown(self.port)
        self.approval = TeardownApproval("usb-controller", "router")

    def run_service(self):
        return self.service.execute("operation", self.approval)

    def test_ordered_success_retains_inhibit_without_cable_clearance(self):
        result = self.run_service()
        self.assertTrue(result.software_down)
        self.assertFalse(result.safe_to_unplug)
        self.assertTrue(self.port.owned)
        self.assertEqual(self.port.events, ["claim", "prepared", "usb_remove_intent",
            "remove_usb", "usb_removed", "tunnel_remove_intent", "deauthorize", "software_down"])

    def test_storage_and_gpu_block_without_claim_or_mutation(self):
        for current in (
            replace(observation(), gpu_functions_present=("gpu",)),
            replace(observation(), usb=replace(observation().usb, mounted_storage=("disk",))),
            replace(observation(), usb=replace(observation().usb, storage_scan_complete=False)),
            replace(observation(), idle=False),
            replace(observation(), topology_complete=False),
        ):
            with self.subTest(current=current):
                self.port.current = current
                self.assertFalse(self.run_service().software_down)
                self.assertEqual(self.port.events, [])

    def test_device_change_after_claim_prevents_first_write(self):
        self.port.change = lambda v, n: replace(v, generation="replacement") if n >= 2 else v
        self.assertEqual(self.run_service().code, "dock_teardown.preflight_changed")
        self.assertNotIn("remove_usb", self.port.events)

    def test_new_gpu_before_tunnel_blocks_deauthorization(self):
        self.port.change = lambda v, n: replace(v, gpu_functions_present=("gpu",)) if n >= 4 else v
        self.assertFalse(self.run_service().software_down)
        self.assertIn("remove_usb", self.port.events)
        self.assertNotIn("deauthorize", self.port.events)

    def test_unknown_final_tunnel_is_not_down(self):
        self.port.change = lambda v, n: replace(v, tunnel=replace(v.tunnel, authorized=None)) if n >= 5 else v
        self.assertEqual(self.run_service().code, "dock_teardown.final_state_unverified")

    def test_timeout_never_deauthorizes_or_retries(self):
        self.port.timeout = True
        self.assertEqual(self.run_service().code, "dock_teardown.unresolved")
        fresh_service = WholeDockTeardown(self.port)
        self.assertEqual(fresh_service.execute("new-operation", self.approval).code,
                         "dock_teardown.transaction_owned")
        self.assertEqual(self.port.events.count("remove_usb"), 1)
        self.assertNotIn("deauthorize", self.port.events)

    def test_journal_failure_stops_before_corresponding_mutation(self):
        for stage, forbidden in [("usb_remove_intent", "remove_usb"),
                                 ("tunnel_remove_intent", "deauthorize")]:
            with self.subTest(stage=stage):
                self.setUp()
                self.port.fail_stage = stage
                self.assertEqual(self.run_service().code, "dock_teardown.unresolved")
                self.assertNotIn(forbidden, self.port.events)
                self.assertTrue(self.port.owned)

    def test_reentrant_call_does_not_overlap(self):
        original = self.port.remove_usb
        nested = []
        def remove(current):
            nested.append(self.run_service())
            original(current)
        self.port.remove_usb = remove
        self.assertTrue(self.run_service().software_down)
        self.assertEqual(nested[0].code, "dock_teardown.busy")


if __name__ == "__main__":
    unittest.main()
