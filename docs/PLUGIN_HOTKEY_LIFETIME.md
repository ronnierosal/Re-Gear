# Plugin-lifetime display shortcut candidate

Back/View + Y held for three seconds is now registered at plugin initialization,
not inside the Quick Access Content effect. Confirmation and guarded TV/Portable
requests are owned by the plugin. Content shares modal and execution locks so
panel actions and global shortcuts cannot overlap. Plugin unload unregisters
input, cancels a hold, closes its modal, and suppresses execution if approval
returns after unload. Panel cleanup no longer closes the plugin-owned modal.

The player observed the chord closing Quick Access without confirmation. Panel
lifetime is a plausible contributor, not proven root cause: alwaysRender was
already enabled. Native button IDs, Steam event delivery and snapshot gating
still require hardware verification. No button remapping or safety-gate bypass.

179 frontend tests, typecheck and production build pass. Five new tests cover
panel-free confirmation, explicit confirmation before execution, plugin cleanup,
unload during approval, and shared action locking/blockers. Existing modal-host
source test now normalizes Windows line endings. No backend mutation changes.
No shutdown or live release route is exposed by the hotkey.

Not deployed or packaged. Review and integrate through the UI release owner;
never overwrite the installed 0.3.50 ZIP. With G1 connected, do not restart Decky
or install this build. Native acceptance must later cover panel closed/open,
both switch directions, early release, disconnecting a controller, repeat holds,
and refused transitions. Safe-unplug support remains absent.
