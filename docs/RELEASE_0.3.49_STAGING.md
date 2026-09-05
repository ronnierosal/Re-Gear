# Re-Gear 0.3.49 manual-install candidate

Staged: `/home/deck/Re-Gear-0.3.49.zip`.
Revision: `ab039af3eecca4668364e347a8042c042664e032`.
SHA-256, local and remote verified:
`60b059e1c33ae574f3085e17d5de6b7a051b72777bb1070eaef3f4f7b30e56ff`.

Reviewed PR9 and version-only PR10 merged after green CI. Includes explicit
native Field section focus, smaller popup, dynamic driver GPU name with eGPU
fallback. Presentation names excluded from default snapshot serialization and
transition fingerprints; name-only generation/sample invariance covered.
All ready ancestors and installed0.3.48 sourcec04d8fd preserved.

173 frontend tests;958 backend tests (6 skipped);typecheck/build, architecture,
compileall, package validation and ZIP CRC/metadata checks passed. Native D-pad
sequence and new popup fit still require player testing after manual install.

Hardware owner confirmed detached normal screen/audio/controller. Read-only
preflight observed USB4 host only and single boot GPU. No hardware transitions,
installation or service restarts. Final installed readback remains0.3.48 c04d8fd.
Patched Loader SHA256 unchanged:
`876acc01bb35cd8e9a9d1700cd00dd68f7704d2a283260197b9857e66fef541f`.

Uploaded unique temporary path, verified checksum, finalized using no-clobber
hard link, then removed temporary and superseded remote0.3.48 ZIP. Local0.3.48
archive retained; unrelated eGPUBridge archive untouched. Only0.3.49 ZIP remains
in /home/deck/. Keep G1 detached for installation; hardware owner coordinates
subsequent trials with version freeze.
