from dataclasses import replace
import unittest
from pathlib import Path
from backend.hdm.ports.presentation_activation import GamescopeUserContext

from backend.hdm.delivery.device_filter_trial_config import (
    render_trial_dropin, session_trial_expectation)
from backend.hdm.delivery.device_filter_dropin_store import NAME
from backend.hdm.delivery.device_filter_session_entry import SessionEntryPurpose
from tests.test_device_filter_runtime_store import bundle


STATE_ASSIGNMENT = 'HDM_STATE_ROOT=/home/deck/.local/share/handheld-dock-mode'


class TrialConfigTests(unittest.TestCase):
    def setUp(self):
        self.runtime = bundle()
        self.user = GamescopeUserContext("deck", 1000, 1000, Path("/home/deck"), Path("/run/user/1000"), Path("/run/user/1000/bus"))

    def test_exact_commands_and_no_unrelated_reset(self):
        for unit, role in [('gamescope-session.service', 'session'), ('steam-launcher.service', 'steam')]:
            rendered = render_trial_dropin(self.runtime, unit, user=self.user)
            self.assertEqual(rendered.path, '/etc/systemd/user/' + unit + '.d/' + NAME)
            self.assertEqual(rendered.content, ('[Service]\nExecStart=\nExecStart="/usr/bin/python3" "-I" "'
                + self.runtime.path + '" "' + role + '"\nEnvironment="' + STATE_ASSIGNMENT + '"\n').encode())

    def test_reject_changed_archive_argv_and_state_path(self):
        for changed in [replace(self.runtime, archive=b'changed'),
                        replace(self.runtime, session_argv=('/bin/sh', '-c', 'unsafe'))]:
            with self.assertRaises(ValueError):
                render_trial_dropin(changed, 'gamescope-session.service', user=self.user)
        with self.assertRaises(ValueError):
            render_trial_dropin(self.runtime, 'other.service', user=self.user)
        with self.assertRaises(ValueError):
            render_trial_dropin(self.runtime, 'gamescope-session.service', user=replace(self.user, home=Path('/home/unsafe%path')))

    def test_preserves_drm_janitor_and_environment(self):
        janitor = '/usr/lib/systemd/user/gamescope-session.service.d/drm_janitor.conf'
        early = '/etc/systemd/user/gamescope-session.service.d/10-native.conf'
        expectation = session_trial_expectation(self.runtime, user=self.user,
            existing_dropins=(early, janitor), existing_environment=('NATIVE_SETTING=retained',))
        self.assertEqual(expectation.dropins, (early, render_trial_dropin(self.runtime,
            'gamescope-session.service', user=self.user).path, janitor))
        self.assertEqual(expectation.environment, ('NATIVE_SETTING=retained', STATE_ASSIGNMENT))
        self.assertIs(expectation.purpose, SessionEntryPurpose.PREPARE_WITHHOLD)

    def test_updates_state_assignment_without_duplicate(self):
        expectation = session_trial_expectation(self.runtime, user=self.user, existing_dropins=(),
            existing_environment=('HDM_STATE_ROOT=/old', 'KEEP=1'))
        self.assertEqual(expectation.environment, (STATE_ASSIGNMENT, 'KEEP=1'))

    def test_rejects_user_dropin_and_ambiguous_basename(self):
        for paths in [('/home/deck/.config/systemd/user/gamescope-session.service.d/90-user.conf',),
                      ('/usr/lib/systemd/user/gamescope-session.service.d/' + NAME,)]:
            with self.assertRaises(ValueError):
                session_trial_expectation(self.runtime, user=self.user, existing_dropins=paths, existing_environment=())

    def test_existing_designated_path_not_duplicated(self):
        target = render_trial_dropin(self.runtime, 'gamescope-session.service', user=self.user).path
        result = session_trial_expectation(self.runtime, user=self.user, existing_dropins=(target,), existing_environment=())
        self.assertEqual(result.dropins, (target,))
