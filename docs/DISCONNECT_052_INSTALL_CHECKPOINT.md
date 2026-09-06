# Disconnect diagnostics installation checkpoint

Re-Gear 0.3.52 is installed through Decky's native lifecycle. Source and hash
are recorded in CURRENT_STATE.md. Installed revision is c028223b1940; scanner
SHA256 matches the local source. Loader reports the previous plugin stopped in
0.1 seconds and the new plugin loaded. Live startup reports Portable, Idle,
no blockers and events ready. G1 is disconnected. The prior ZIP is retained.

During the supervised installation preparation, the player reported normal
shutdown with G1 attached: fan stopped and power lights off, charging light
remaining. The player then disconnected G1 while off and booted detached.
Built-in controls did not work on that boot. A read-only input-device listing
and bounded kernel log were retained locally before the requested normal restart.

The player clarified that controller failure intermittently follows shutdown
and startup, including with G1 connected. This is a recurring player-reported
symptom, not an established G1 cause or an effect of the uninstalled candidate.
The successful physical shutdown report applies to this cycle only.

Controls, screen and audio recovered after the normal restart, as reported by
the player before installation. Installation and runtime verification then passed.
Next work: recoverable session launch integration remains pending; this package
improves resource detection only and does not release G1 or permit live unplug.
