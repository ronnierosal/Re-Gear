# Compatibility Test Mode: supervised hardware validation

This procedure is a future supervised validation gate for the dormant
Compatibility Test Mode collectors. It is not a deployment guide, an automatic
test, or permission to change display, GPU, controller, audio, sleep, process,
USB4, or eGPU state.

The current collectors are implemented and simulated only. They are not wired
to the production Decky plugin or a user interface. No observation made by the
remote SSH capture harness can complete this procedure.

## Preconditions

Perform this only when the maintainer is physically present at the certified
Ally X + GPD G1 setup and can see the active display and use a working control.

1. Start from a provenance-recorded single Re-Gear package following D0–D3 of
   [Deployment and validation strategy](DEPLOYMENT_VALIDATION.md). Do not mix
   frontend and backend builds.
2. Confirm Steam, Decky, internal display, built-in controls, and network are
   usable. Record a redacted before snapshot.
3. Keep a simple return path: no pending transition journal, no sleep request,
   no process-release operation, and no planned cable removal.
4. Select one installed Steam game with a known AppID. Start it normally and
   wait until Re-Gear can obtain two fresh, exact active-session observations.
5. Keep diagnostics bounded and explicitly enabled only for the test. Do not
   treat logs as proof of saved progress.

Any unknown/changed AppID, unverified rendering state, stale sample, missing
observer, unexpected display/control loss, or new G1/topology ambiguity is a
stop condition. Leave the G1 connected, cancel the test, retain the redacted
evidence, and return to the last known-good state before investigating.

## Graceful-exit evidence

This validates the narrow category **Graceful Exit Verified**, not autosave or
save-on-exit.

1. Arm the read-only watch only after the exact selected game is observed
   running.
2. The player exits that same game normally through its ordinary in-game or
   Steam flow. Re-Gear must not request, signal, close, save, or relaunch it.
3. Collect a later fresh, exact idle observation.

Pass criteria:

- The original exact AppID is bound before the player exits.
- A later observation is exact, Idle, and has a different semantic generation
  and sample ID.
- The result is only `graceful_exit_verified`, with a categorical hashed
  observation generation.
- The result requires explicit human review before catalog evidence could be
  created, and hardware evidence does not auto-promote a record.

Failure criteria:

- A different game starts, the original game remains running, evidence is
  unknown, or a generation/sample is reused.
- Re-Gear then enters Action Required, disables temporary diagnostics, and records
  no successful result.

This result makes no claim that progress was saved. Autosave and save-on-exit
need a separately reviewed, game-specific recipe/proof/mechanism validation as
described in [Game save](GAME_SAVE.md).

## External-render evidence

Validate this separately from graceful-exit evidence. It may begin only after a
separate approved display/eGPU experiment has already established a stable,
usable Docked-eGPU placement. Do not use Compatibility Test Mode to cause that
placement.

Pass criteria require the same baseline AppID, a fresh exact session bracket,
exact G1 engine-counter activity, and verified Docked-eGPU placement. Anything
else is Action Required; a connected G1, connector, or GPU client alone is not
external-render proof.

## Evidence and recovery record

For either test, retain only:

- source commit and package hash;
- Re-Gear and SteamOS version;
- categorical test outcome and reason;
- redacted before/after snapshots;
- whether controls, display, Steam, Decky, and SSH remained usable; and
- the explicit reviewer decision.

Do not retain usernames, paths, AppIDs, scope names, raw PCI/DRM/USB4 identity,
PIDs, command lines, or unredacted logs in the public result.

If the test stops or fails, do not retry with a different game, a restart,
suspend, disconnect, or process action during the same session. Capture the
failure, restore the known-good Portable or already-verified docked state, and
return to local diagnosis. A successful collector result is **Hardware
Validated** only for this narrow observation path; it is not a certification of
game saves, transitions, eGPU removal, or sleep.
