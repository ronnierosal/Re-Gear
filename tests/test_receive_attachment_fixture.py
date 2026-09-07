import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from scripts import probe_receive_attachment_fixture as fixture
from hdm.delivery.device_filter_btf import FileReceiveLayout
from hdm.delivery.device_filter_lifecycle import LaunchBinding, PairedStage


class AttachmentFixtureTests(unittest.TestCase):
    def setUp(self):
        self.binding = LaunchBinding('a'*64, 'fixture', 'gamescope-session.service',
            'b'*32, 1000, 123, 456, 1, 789, 'c'*64, 100.)
        self.layout = FileReceiveLayout(1, 2, 3, 64, 64, 8, 0, 4, 8)
        self.controller = Mock()
        def attach(*args, policy):
            return SimpleNamespace(launch_authorized=False, disconnect_clearance=False,
                ownership=SimpleNamespace(stage=PairedStage.RECEIVE_CONFIRMED),
                program_sha256=policy.program_sha256)
        self.controller.attach.side_effect = attach
        self.factory = Mock(return_value=self.controller)

    def run_publisher(self, **kwargs):
        with patch.object(fixture.os, 'major', return_value=1, create=True), \
             patch.object(fixture.os, 'minor', return_value=3, create=True):
            fixture.publish_controller(object(), self.binding, 9, self.layout, 259,
                controller_factory=self.factory, read_btf=lambda: b'btf', **kwargs)

    def test_changed_live_layout_prevents_controller_call(self):
        with patch.object(fixture, 'parse_file_receive_btf', return_value=None):
            with self.assertRaises(ValueError):
                self.run_publisher(observe_denial=lambda: True)
        self.factory.assert_not_called()

    def test_denial_required_after_controller_result(self):
        with patch.object(fixture, 'parse_file_receive_btf', return_value=self.layout):
            with self.assertRaises(ValueError):
                self.run_publisher(observe_denial=lambda: False)
        self.controller.attach.assert_called_once()

    def test_authorizing_result_cannot_pass_fixture(self):
        self.controller.attach.side_effect = None
        self.controller.attach.return_value = SimpleNamespace(launch_authorized=True)
        denial = Mock(return_value=True)
        with patch.object(fixture, 'parse_file_receive_btf', return_value=self.layout):
            with self.assertRaises(ValueError):
                self.run_publisher(observe_denial=denial)
        denial.assert_not_called()


if __name__ == '__main__':
    unittest.main()
