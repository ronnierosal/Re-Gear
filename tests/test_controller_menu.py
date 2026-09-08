import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from hdm.domain.controller_menu import (
    ControllerMenuProfile, ControllerTransport, MenuAction, MenuBinding,
    MenuInput, MenuState, route_menu_input,
)


class ControllerMenuTests(unittest.TestCase):
    def setUp(self):
        # Synthetic identifiers, not real Raikiri report mappings.
        self.profile = ControllerMenuProfile("fixture", ControllerTransport.USB, (
            MenuBinding("extra:left", MenuAction.MAIN_MENU),
            MenuBinding("extra:right", MenuAction.QUICK_ACCESS),
        ), verified=True)

    def event(self, sequence, *buttons, **changes):
        return replace(MenuInput("fixture", ControllerTransport.USB, "session-a",
                                 sequence, frozenset(buttons), True), **changes)

    def baseline(self):
        return route_menu_input(self.profile, self.event(0)).state

    def test_both_menus_across_each_transport(self):
        for transport in ControllerTransport:
            profile = replace(self.profile, transport=transport)
            for source, action in (("extra:left", MenuAction.MAIN_MENU),
                                   ("extra:right", MenuAction.QUICK_ACCESS)):
                with self.subTest(transport=transport, source=source):
                    baseline = route_menu_input(profile, self.event(0, transport=transport)).state
                    result = route_menu_input(profile, self.event(1, source, transport=transport), baseline)
                    self.assertEqual(result.action, action)

    def test_hold_repeat_release_and_repress(self):
        state = self.baseline()
        actions = []
        for event in (self.event(1, "extra:left"), self.event(1, "extra:left"),
                      self.event(2, "extra:left"), self.event(3), self.event(4, "extra:left")):
            result = route_menu_input(self.profile, event, state)
            state = result.state
            actions.append(result.action)
        self.assertEqual(actions, [MenuAction.MAIN_MENU, None, None, None, MenuAction.MAIN_MENU])

    def test_unverified_and_wrong_device_or_transport_block(self):
        for event in (self.event(1, "extra:left", verified=False),
                      self.event(1, "extra:left", device="other"),
                      self.event(1, "extra:left", transport=ControllerTransport.BLUETOOTH),
                      self.event(1, "extra:left", session=""), self.event(-1, "extra:left")):
            result = route_menu_input(self.profile, event, self.baseline())
            self.assertIsNone(result.action)
            self.assertEqual(result.state, MenuState())
        result = route_menu_input(replace(self.profile, verified=False), self.event(1, "extra:left"), self.baseline())
        self.assertIsNone(result.action)

    def test_reconnect_held_button_requires_release(self):
        state = self.baseline()
        for event in (self.event(1, "extra:left", session="new"),
                      self.event(2, "extra:left", session="new"), self.event(3, session="new")):
            result = route_menu_input(self.profile, event, state)
            self.assertIsNone(result.action)
            state = result.state
        self.assertEqual(route_menu_input(self.profile, self.event(4, "extra:left", session="new"), state).action,
                         MenuAction.MAIN_MENU)

    def test_stick_clicks_and_firmware_chord_do_not_open_menus(self):
        state = self.baseline()
        for event in (self.event(1, "l3", "r3"), self.event(2, "extra:left", "extra:right"),
                      self.event(3, "extra:left"), self.event(4)):
            result = route_menu_input(self.profile, event, state)
            self.assertIsNone(result.action)
            state = result.state

    def test_stale_release_does_not_rearm_held_button(self):
        state = route_menu_input(self.profile, self.event(2, "extra:right"), self.baseline()).state
        result = route_menu_input(self.profile, self.event(1), state)
        self.assertEqual(result.state, state)
        self.assertIsNone(route_menu_input(self.profile, self.event(3, "extra:right"), result.state).action)

    def test_duplicate_binding_rejected(self):
        with self.assertRaises(ValueError):
            replace(self.profile, bindings=(self.profile.bindings[0], self.profile.bindings[0]))


if __name__ == "__main__":
    unittest.main()
