from __future__ import annotations

import ctypes
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from hdm.adapters.steamos.drm_crtc import (  # noqa: E402
    GET_CRTC,
    GET_RESOURCES,
    MAX_CRTCS,
    CrtcRecord,
    DrmCrtcProbe,
)


NODE = "/dev/dri/card1"

#: What the tested Ally X reported for the eGPU, read unprivileged: one CRTC
#: driving the TV at 3840x2160 from framebuffer 133, three idle.
EGPU_CRTCS = (
    CrtcRecord(98, 133, True, 3840, 2160),
    CrtcRecord(102, 0, False, 0, 0),
    CrtcRecord(106, 0, False, 0, 0),
    CrtcRecord(110, 0, False, 0, 0),
)
IDLE_CRTCS = tuple(CrtcRecord(record.crtc_id, 0, False, 0, 0) for record in EGPU_CRTCS)


class FakeKernel:
    """Answer the two GET ioctls the probe is allowed to issue."""

    def __init__(self, crtcs=EGPU_CRTCS, *, count=None, raises=None, recount=None):
        self._crtcs = {record.crtc_id: record for record in crtcs}
        self._order = [record.crtc_id for record in crtcs]
        self._count = len(crtcs) if count is None else count
        self._raises = raises
        self._recount = recount
        self.requests: list[int] = []

    def __call__(self, descriptor, request, structure):
        self.requests.append(request)
        if self._raises is not None and len(self.requests) >= self._raises:
            raise OSError("fake.ioctl_failed")
        if request == GET_RESOURCES:
            if structure.crtc_id_ptr:
                array = (ctypes.c_uint32 * len(self._order)).from_address(
                    structure.crtc_id_ptr
                )
                for index, identifier in enumerate(self._order):
                    array[index] = identifier
                structure.count_crtcs = (
                    self._count if self._recount is None else self._recount
                )
            else:
                structure.count_crtcs = self._count
            return 0
        if request == GET_CRTC:
            record = self._crtcs[structure.crtc_id]
            structure.fb_id = record.fb_id
            structure.mode_valid = 1 if record.mode_valid else 0
            structure.mode.hdisplay = record.width
            structure.mode.vdisplay = record.height
            return 0
        raise AssertionError(f"unexpected ioctl {request:#x}")


def probe(kernel=None, *, open_fails=False, closed=None):
    closed = [] if closed is None else closed

    def open_node(node):
        if open_fails:
            raise OSError("fake.open_failed")
        return 11

    instance = DrmCrtcProbe(
        open_node=open_node,
        ioctl=kernel or FakeKernel(),
        close_fd=closed.append,
    )
    instance.closed = closed  # type: ignore[attr-defined]
    return instance


class ObservationTests(unittest.TestCase):
    def test_the_device_reading_is_reproduced_from_the_crtc_not_from_enabled(
        self,
    ) -> None:
        """The eGPU's committed mode, as the hardware actually reported it."""
        state = probe(FakeKernel(EGPU_CRTCS)).observe(NODE)

        self.assertTrue(state.complete)
        self.assertIs(state.mode_committed, True)
        self.assertEqual(len(state.crtcs), 4)
        self.assertEqual(len(state.committed), 1)
        committed = state.committed[0]
        self.assertEqual(
            (committed.crtc_id, committed.fb_id, committed.width, committed.height),
            (98, 133, 3840, 2160),
        )

    def test_a_card_driving_nothing_reports_a_verified_false(self) -> None:
        state = probe(FakeKernel(IDLE_CRTCS)).observe(NODE)

        self.assertTrue(state.complete)
        self.assertIs(state.mode_committed, False)
        self.assertEqual(state.committed, ())

    def test_a_mode_without_a_framebuffer_is_not_a_display_being_driven(self) -> None:
        """Both halves are required, and neither alone is presentation.

        A valid mode with nothing to scan out is not a display being driven,
        and a framebuffer with no mode is not being presented.
        """
        for fb_id, mode_valid in ((0, True), (133, False)):
            with self.subTest(fb_id=fb_id, mode_valid=mode_valid):
                crtcs = (CrtcRecord(98, fb_id, mode_valid, 3840, 2160),)
                state = probe(FakeKernel(crtcs)).observe(NODE)
                self.assertIs(state.mode_committed, False)

    def test_only_the_two_read_only_ioctls_are_ever_issued(self) -> None:
        """No GETCONNECTOR: its zero-count form makes the kernel probe.

        A probe is a detect on the wire rather than a read of state, and this
        module exists to observe.
        """
        kernel = FakeKernel(EGPU_CRTCS)
        probe(kernel).observe(NODE)

        self.assertEqual(set(kernel.requests), {GET_RESOURCES, GET_CRTC})
        self.assertEqual(kernel.requests.count(GET_CRTC), 4)


class UnknownTests(unittest.TestCase):
    """Not being able to look must never read as nothing being committed."""

    def test_a_node_that_cannot_be_opened_is_unknown_rather_than_inactive(self) -> None:
        state = probe(open_fails=True).observe(NODE)

        self.assertFalse(state.complete)
        self.assertIsNone(state.mode_committed)
        self.assertEqual(state.code, "drm_crtc.node_unavailable")
        self.assertEqual(state.crtcs, ())

    def test_an_ioctl_that_fails_is_unknown_and_still_closes_the_descriptor(
        self,
    ) -> None:
        closed: list[int] = []
        state = probe(FakeKernel(raises=1), closed=closed).observe(NODE)

        self.assertFalse(state.complete)
        self.assertIsNone(state.mode_committed)
        self.assertEqual(state.code, "drm_crtc.read_failed")
        self.assertEqual(closed, [11])

    def test_a_failure_partway_through_the_crtcs_discards_the_partial_reading(
        self,
    ) -> None:
        """Three of four CRTCs read is not evidence that the fourth is idle."""
        state = probe(FakeKernel(EGPU_CRTCS, raises=4)).observe(NODE)

        self.assertIsNone(state.mode_committed)
        self.assertEqual(state.crtcs, ())

    def test_an_implausible_crtc_count_is_refused_rather_than_allocated(self) -> None:
        state = probe(FakeKernel(EGPU_CRTCS, count=MAX_CRTCS + 1)).observe(NODE)

        self.assertIsNone(state.mode_committed)
        self.assertEqual(state.code, "drm_crtc.crtc_count_implausible")

    def test_a_crtc_set_that_changes_between_the_two_calls_is_unknown(self) -> None:
        state = probe(FakeKernel(EGPU_CRTCS, recount=2)).observe(NODE)

        self.assertIsNone(state.mode_committed)
        self.assertEqual(state.code, "drm_crtc.crtc_set_changed")

    def test_a_card_with_no_crtcs_drives_nothing_and_that_is_a_complete_answer(
        self,
    ) -> None:
        state = probe(FakeKernel((), count=0)).observe(NODE)

        self.assertTrue(state.complete)
        self.assertIs(state.mode_committed, False)
        self.assertEqual(state.code, "drm_crtc.no_crtcs")


class DescriptorTests(unittest.TestCase):
    def test_the_descriptor_is_released_on_every_path_that_opened_one(self) -> None:
        for kernel in (FakeKernel(EGPU_CRTCS), FakeKernel(raises=1)):
            with self.subTest(kernel=kernel):
                closed: list[int] = []
                probe(kernel, closed=closed).observe(NODE)
                self.assertEqual(closed, [11])

    def test_nothing_is_closed_when_nothing_was_opened(self) -> None:
        closed: list[int] = []
        probe(open_fails=True, closed=closed).observe(NODE)
        self.assertEqual(closed, [])


if __name__ == "__main__":
    unittest.main()
