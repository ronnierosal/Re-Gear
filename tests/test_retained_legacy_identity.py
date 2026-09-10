"""Pin the former-name strings that a rename must never touch.

Re-Gear was Handheld Dock Mode. The product name has moved and the code and
docs should follow it, but a handful of strings are not the product's name --
they are the identity of things that already exist on a player's device, and
renaming them does not rename what is on disk. It orphans it.

This file exists because that failure has already happened once. Issue #167:
renaming the plugin directory from HandheldDockMode to Re-Gear left the managed
Gamescope drop-in pointing at the old path on every installed device. Nothing
could repair it, `session_ready` was never true, and display switching sat at
"Checking" indefinitely. The fix was to teach the code to recognise its own
former rendering and migrate it -- which only works for as long as the former
strings stay exactly as they were written.

So each assertion below is about a device, not a preference. The comment on
each says what breaks if it changes. A rename sweep that trips one of these has
found the boundary between the product's name and its installed footprint.

None of this argues against the rename. It argues for doing it everywhere the
name is only a name, and nowhere it is an address.

Pinned elsewhere, listed here so the inventory is findable in one place. Each
already has an assertion in the test named beside it; what those lack is the
reason, which is how a sweep talks itself past them:

- ``X-HDM-Content-SHA256`` -- an HTTP header a server reads.
  ``tests/test_support_submission_adapter.py``
- ``REPORT_ID_RE = ^HDM-[A-Z0-9]{6,16}$`` -- validates ids the *server* returns,
  so the format is not ours to change unilaterally.
  ``tests/test_support_submission.py``
- the ``"hdm"`` version key in the support-bundle payload -- a wire format a
  reader already parses. ``tests/test_support_bundle.py``
- ``HDM-support-<timestamp>.json`` -- the filename written into a player's
  Downloads, which they may already have sent somewhere.
  ``tests/test_support_bundle.py``
- ``HDM_STATE_ROOT`` -- an environment variable rendered into the installed
  drop-in, so it is bytes on disk as well as a name. Covered below.
- ``HDM shutdown checkpoint: stage=`` -- emitted to journald and parsed by a
  regex in ``scripts/capture_shutdown_evidence.py``. Renaming one side breaks
  the scraper contract silently, since nothing fails until evidence is missing.
- ``hdm.hideAttachedEgpuSleepWarning`` and its legacy partner -- localStorage
  keys holding a player's dismissal.
  ``frontend-tests/retained-legacy-identity.test.mjs``

Deliberately not frozen: ``backend/hdm/`` is packaged into the Decky archive and
validated by the signed installer, so renaming it changes the installed tree.
That is a coordinated release, not a sweep -- out of scope here rather than
forbidden forever.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from hdm.adapters.steamos import inhibitor_guard  # noqa: E402
from hdm.adapters.steamos.gamescope_user import GamescopeUserContext  # noqa: E402
from hdm.delivery import gamescope_integration, runtime_state  # noqa: E402
from hdm.delivery.gamescope_integration import GamescopeIntegrationStore  # noqa: E402

SPEC = importlib.util.spec_from_file_location(
    "ally_deploy_helper_identity", ROOT / "scripts" / "ally_deploy_helper.py"
)
assert SPEC and SPEC.loader
_helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(_helper)


def _store(root: Path) -> GamescopeIntegrationStore:
    """A store shaped like an install, so assertions read real rendered output.

    Deliberately not a grep of the source file: a test that searches the module
    for its own literal passes whether or not the value is ever used.
    """
    home = root / "home" / "deck"
    home.mkdir(parents=True)
    plugin = root / "plugin"
    shim = plugin / "bin" / "gamescope"
    shim.parent.mkdir(parents=True)
    shim.write_text("#!/usr/bin/python3\n", encoding="utf-8")
    uid = getattr(os, "getuid", lambda: 1000)()
    gid = getattr(os, "getgid", lambda: 1000)()
    user = GamescopeUserContext(
        "deck", uid, gid, home,
        Path("/run/user") / str(uid), Path("/run/user") / str(uid) / "bus",
    )
    return GamescopeIntegrationStore(
        plugin_root=plugin, user=user,
        effective_uid=lambda: 0, set_owner=lambda path, u, g: None,
    )


class ManagedDropInIdentityTests(unittest.TestCase):
    """The drop-in is a file this project wrote onto someone else's machine."""

    def test_the_drop_in_keeps_the_filename_already_written_to_devices(self) -> None:
        # Every install has this exact filename under
        # ~/.config/systemd/user/gamescope-session.service.d/. Renaming it here
        # does not rename it there: it leaves the old file in place, unmanaged
        # and still on the PATH, and writes a second one beside it.
        self.assertEqual(
            gamescope_integration.DROPIN_NAME, "90-handheld-dock-mode.conf"
        )

    def test_the_rendered_drop_in_still_opens_with_the_marker_on_disk(self) -> None:
        # status() compares the file's content against expected_text(). Change
        # this line and every installed drop-in stops matching, reporting as
        # `managed_dropin_modified` -- the code's word for "a player edited
        # this, leave it alone". It would refuse to repair its own file.
        with tempfile.TemporaryDirectory() as directory:
            rendered = _store(Path(directory)).expected_text()

        self.assertTrue(
            rendered.startswith(
                "# Managed by Handheld Dock Mode. Remove only through HDM.\n"
            ),
            rendered.splitlines()[:1],
        )

    def test_the_former_plugin_directory_stays_recognisable(self) -> None:
        # This is the #167 migration itself. The code recognises a drop-in it
        # wrote under the old plugin directory and repairs it. The moment this
        # string changes, such a drop-in becomes unrecognised again and every
        # device still carrying one is stranded exactly as before.
        self.assertIn(
            "HandheldDockMode", gamescope_integration.SUPERSEDED_PLUGIN_NAMES
        )

    def test_the_shim_marker_identifies_shims_already_installed(self) -> None:
        # _shim_ready() looks for these bytes inside the installed shim to
        # decide whether it is ours. A renamed marker makes every installed
        # shim read as foreign, and activation refuses on shim_unavailable.
        self.assertEqual(
            gamescope_integration.SHIM_MARKER,
            "Handheld Dock Mode Gamescope argument shim",
        )


class StateRootIdentityTests(unittest.TestCase):
    """State roots are addresses. A renamed address is a different directory."""

    def test_the_root_owned_state_directory_keeps_its_path(self) -> None:
        # /var/lib/handheld-dock-mode holds root-owned control state and the
        # deployment public key on installed devices. Renaming it here points
        # the code at an empty path and silently abandons what is there --
        # including the key the signed installer verifies against.
        self.assertEqual(
            runtime_state.DEFAULT_RUNTIME_STATE_ROOT,
            Path("/var/lib/handheld-dock-mode"),
        )

    def test_the_state_root_name_is_asserted_not_merely_defaulted(self) -> None:
        # The guard is deliberate: a caller cannot pass a renamed root either.
        with self.assertRaises(ValueError):
            runtime_state.RootOwnedRuntimeState(Path("/var/lib/re-gear"))

    def test_the_user_state_root_is_rendered_into_the_drop_in(self) -> None:
        # HDM_STATE_ROOT is written into the managed drop-in, so this name is
        # part of the bytes on disk as well as a directory that already holds
        # state for every install.
        with tempfile.TemporaryDirectory() as directory:
            store = _store(Path(directory))
            rendered = store.expected_text()

        self.assertEqual(store.state_root.name, "handheld-dock-mode")
        self.assertIn("HDM_STATE_ROOT=", rendered)
        self.assertIn("share/handheld-dock-mode", rendered)


class InstalledIdentityTests(unittest.TestCase):
    def test_the_sleep_inhibitor_keeps_the_name_it_registers_under(self) -> None:
        # This is the `who` a live systemd inhibitor lock reports. An operator
        # reading `systemd-inhibit --list` during a supervised run matches it
        # against recorded evidence; renaming it mid-investigation makes the
        # lock look like someone else's.
        self.assertEqual(inhibitor_guard.INHIBITOR_WHO, "Handheld Dock Mode")

    def test_the_installer_still_recognises_a_legacy_install(self) -> None:
        # The signed helper refuses to install over an old-name plugin
        # directory and directs the operator to a supervised cutover. If it
        # stops recognising the name it stops refusing, and the two trees end
        # up side by side with the loader free to pick either.
        self.assertEqual(_helper.LEGACY_NAME, "HandheldDockMode")


if __name__ == "__main__":
    unittest.main()
