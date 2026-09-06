# Re-Gear 0.3.51 staging - 2026-09-05

Reviewed PR #13 and version-only PR #14 merged into codex/compact-branding-ui.
Staged `/home/deck/Re-Gear-0.3.51.zip`, source revision
`b08d797cf0aa2ad33eed3401a3fa193a37615c5e`; local and final remote SHA-256:
`22f9042ff55011bc84a20f9c6fcdc37a9b0e0c0122b6b3d2cf9ec20894b6df78`.

The plugin-owned display hotkey remains subscribed outside Quick Access,
shares execution/modal locks, and preserves required result acknowledgements
for mounted and later-mounted panels. No shutdown or live-removal hotkey added.
Existing 0.3.50 UI ancestry is preserved. Reproducible bundle checks pass in CI.

180 frontend tests and 958 backend tests passed (six skipped), plus typecheck,
architecture, compilation, build, package and archive integrity checks. Both
foundation checks passed for PR #13 and #14. Native hotkey delivery remains
unverified. Installed readback before and after staging remained 0.3.50 revision
`e07bfb6e657ff3c30fc2f0fa3d84a94e87f869e9`. No installation, service restart,
or hardware transition performed. With G1 attached, manual installation must
wait for confirmed full power-off, detach, and detached boot coordinated by the
hardware owner. Superseded remote 0.3.50 ZIP removed after final hash verification;
the local historical archive remains available.

CURRENT_STATE.md could not be patched because its existing bytes are not valid
UTF-8. Its encoding was preserved; this focused record owns this staging event.
