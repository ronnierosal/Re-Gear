# Re-Gear 0.3.48 staged UI candidate

Staged for manual installation at `/home/deck/Re-Gear-0.3.48.zip`.
Source revision: `c04d8fd4c3c249da74b2ad005ec34c060210e781`.
SHA-256, verified locally and on Ally:
`f1bacbb3c39f3ac901e7d2775f0496599aa550646431d6c10c8e5b5a0f3fd3c7`.

Reviewed scoped PRs 7, 6, 5 were merged in that order with passing updated CI;
version-only PR8 merged after green CI. Broad historical PR3/main was not merged.
All shared ready commits and installed0.3.47 source0c77d12 are ancestors.

Includes compact popup baseline, late-detection waiting feedback, compact current
state rows, generic eGPU readiness labels, native section focus stops and
destination-aware display controls. No backend/controller listener/disconnect
flow changes. Paused combined disconnect/X shortcut excluded. GPU model display
deferred because the current snapshot does not expose a model-name field.

Checks:171 frontend tests;956 backend tests (6 skipped);typecheck, production
build, architecture, compileall, package checks, ZIP CRC/metadata and diff checks.
Independent focused source review found no blocker. On-device navigation and
visual validation are still pending; local checks do not prove hardware behavior.

Hardware owner confirmed full power-off, G1 disconnection, then normal controller
and audio after detached restart before staging. No install/restart/transition
was performed. Final installed readback remains0.3.47 at0c77d12.
Decky loader checksum remained
`876acc01bb35cd8e9a9d1700cd00dd68f7704d2a283260197b9857e66fef541f`.

Transfer used a unique temporary file, verified hash, then a no-clobber hard link.
Remote0.3.47 ZIP removed after new verification; local archive retained.
Unrelated Downloads/eGPUBridge archive preserved. Only0.3.48 ZIP remains at the
home-directory root. Keep G1 detached for manual installation and UI validation;
coordinate the next hardware test with its owner and freeze updates during it.
