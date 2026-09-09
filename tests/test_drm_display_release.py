from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from hdm.adapters.steamos.drm_crtc import GET_CRTC  # noqa: E402
from hdm.adapters.steamos.drm_display_release import (  # noqa: E402
    DROP_MASTER,
    SET_CRTC,
    SET_MASTER,
    DisplayReleaseOutcome,
    DrmDisplayRelease,
)


EGPU = "/dev/dri/card1"
#: The eGPU's committed CRTC on the tested hardware: mode valid, framebuffer 133.
COMMITTED = {98: (133, True)}


class FakeKernel:
    """Model just enough DRM to answer the four ioctls this adapter issues."""

    def __init__(
        self,
        state=None,
        *,
        master=True,
        set_crtc_fails=False,
        set_crtc_ignored=False,
        drop_fails=False,
        get_fails=False,
    ):
        self.state = dict(COMMITTED if state is None else state)
        self._master = master
        self._set_crtc_fails = set_crtc_fails
        self._set_crtc_ignored = set_crtc_ignored
        self._drop_fails = drop_fails
        self._get_fails = get_fails
        self.mastered = False
        self.dropped = False
        self.requests: list[int] = []

    def __call__(self, descriptor, request, structure):
        self.requests.append(request)
        if request == SET_MASTER:
            if not self._master:
                raise OSError(16, "fake.master_busy")
            self.mastered = True
            return 0
        if request == DROP_MASTER:
            if self._drop_fails:
                raise OSError(22, "fake.drop_failed")
            self.dropped = True
            return 0
        if request == SET_CRTC:
            if self._set_crtc_fails:
                raise OSError(13, "fake.set_crtc_failed")
            if not self._set_crtc_ignored:
                self.state[structure.crtc_id] = (0, False)
            return 0
        if request == GET_CRTC:
            if self._get_fails:
                raise OSError(5, "fake.get_failed")
            fb_id, mode_valid = self.state.get(structure.crtc_id, (0, False))
            structure.fb_id = fb_id
            structure.mode_valid = 1 if mode_valid else 0
            return 0
        raise AssertionError(f"unexpected ioctl {request:#x}")


def build(kernel=None, *, open_fails=False):
    opened: list[str] = []
    closed: list[int] = []

    def open_node(node):
        opened.append(node)
        if open_fails:
            raise OSError("fake.open_failed")
        return 12

    adapter = DrmDisplayRelease(
        open_node=open_node, ioctl=kernel or FakeKernel(), close_fd=closed.append
    )
    adapter.opened = opened  # type: ignore[attr-defined]
    adapter.closed = closed  # type: ignore[attr-defined]
    return adapter


class ReleaseTests(unittest.TestCase):
    def test_the_console_held_crtc_is_turned_off_and_verified_by_reading_it_back(
        self,
    ) -> None:
        kernel = FakeKernel()
        adapter = build(kernel)

        result, held = adapter.release(EGPU, (98,))

        self.assertIs(result.outcome, DisplayReleaseOutcome.RELEASED)
        self.assertEqual(result.released, (98,))
        self.assertTrue(kernel.mastered)
        self.assertEqual(kernel.state[98], (0, False))
        self.assertIsNotNone(held)
        self.assertTrue(held.held)
        self.assertIs(held.still_released(), True)
        # The descriptor is still open: that is what keeps the display off.
        self.assertEqual(adapter.closed, [])

    def test_only_the_card_it_was_given_is_ever_opened(self) -> None:
        """The internal panel's card is never opened, mastered or modified."""
        adapter = build()
        adapter.release(EGPU, (98,))
        self.assertEqual(adapter.opened, [EGPU])

    def test_a_write_the_kernel_ignored_is_reported_rather_than_assumed(self) -> None:
        """SETCRTC returning without error is not evidence the mode went."""
        kernel = FakeKernel(set_crtc_ignored=True)
        adapter = build(kernel)

        result, held = adapter.release(EGPU, (98,))

        self.assertIs(result.outcome, DisplayReleaseOutcome.STILL_COMMITTED)
        self.assertEqual(result.code, "display_release.mode_still_committed")
        self.assertIsNone(held)
        # Restored rather than left with the display in a state nobody asked for.
        self.assertEqual(adapter.closed, [12])

    def test_a_failed_write_restores_and_reports_the_errno(self) -> None:
        adapter = build(FakeKernel(set_crtc_fails=True))

        result, held = adapter.release(EGPU, (98,))

        self.assertIs(result.outcome, DisplayReleaseOutcome.STILL_COMMITTED)
        self.assertEqual(result.code, "display_release.write_failed:13")
        self.assertIsNone(held)
        self.assertEqual(adapter.closed, [12])

    def test_master_that_is_refused_stops_before_any_write(self) -> None:
        kernel = FakeKernel(master=False)
        adapter = build(kernel)

        result, held = adapter.release(EGPU, (98,))

        self.assertIs(result.outcome, DisplayReleaseOutcome.NOT_MASTER)
        self.assertIsNone(held)
        self.assertNotIn(SET_CRTC, kernel.requests)
        self.assertEqual(adapter.closed, [12])

    def test_a_card_that_cannot_be_opened_attempts_nothing(self) -> None:
        adapter = build(open_fails=True)

        result, held = adapter.release(EGPU, (98,))

        self.assertIs(result.outcome, DisplayReleaseOutcome.UNAVAILABLE)
        self.assertIsNone(held)
        self.assertEqual(adapter.closed, [])

    def test_crtcs_that_do_not_name_a_target_are_refused_without_opening_the_card(
        self,
    ) -> None:
        adapter = build()
        for crtcs in ((), [98], (0,), ("98",), (98, -1)):
            with self.subTest(crtcs=crtcs):
                result, held = adapter.release(EGPU, crtcs)
                self.assertIs(result.outcome, DisplayReleaseOutcome.UNAVAILABLE)
                self.assertEqual(result.code, "display_release.crtcs_invalid")
                self.assertIsNone(held)
        self.assertEqual(adapter.opened, [])


class HandleTests(unittest.TestCase):
    """The release lasts exactly as long as the descriptor does."""

    def test_restoring_drops_master_and_closes_which_is_what_restores_the_console(
        self,
    ) -> None:
        kernel = FakeKernel()
        adapter = build(kernel)
        _, held = adapter.release(EGPU, (98,))

        held.restore()

        self.assertTrue(kernel.dropped)
        self.assertEqual(adapter.closed, [12])
        self.assertFalse(held.held)
        self.assertIs(held.still_released(), False)

    def test_restoring_twice_releases_the_descriptor_once(self) -> None:
        adapter = build()
        _, held = adapter.release(EGPU, (98,))

        held.restore()
        held.restore()

        self.assertEqual(adapter.closed, [12])

    def test_a_drop_that_fails_still_closes_the_descriptor(self) -> None:
        """Closing is what triggers the kernel's restore, so it must happen."""
        adapter = build(FakeKernel(drop_fails=True))
        _, held = adapter.release(EGPU, (98,))

        held.restore()

        self.assertEqual(adapter.closed, [12])
        self.assertFalse(held.held)

    def test_leaving_the_context_restores_the_display(self) -> None:
        adapter = build()
        _, held = adapter.release(EGPU, (98,))

        with held:
            self.assertTrue(held.held)
        self.assertFalse(held.held)
        self.assertEqual(adapter.closed, [12])

    def test_an_exception_inside_the_context_still_restores(self) -> None:
        adapter = build()
        _, held = adapter.release(EGPU, (98,))

        with self.assertRaises(RuntimeError):
            with held:
                raise RuntimeError("disconnect failed")
        self.assertEqual(adapter.closed, [12])

    def test_a_release_that_can_no_longer_be_read_is_unknown_not_still_held(
        self,
    ) -> None:
        kernel = FakeKernel()
        adapter = build(kernel)
        _, held = adapter.release(EGPU, (98,))
        kernel._get_fails = True

        self.assertIsNone(held.still_released())

    def test_a_mode_that_came_back_reads_as_no_longer_released(self) -> None:
        kernel = FakeKernel()
        adapter = build(kernel)
        _, held = adapter.release(EGPU, (98,))
        kernel.state[98] = (140, True)

        self.assertIs(held.still_released(), False)


if __name__ == "__main__":
    unittest.main()
