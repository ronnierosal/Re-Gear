# G1 audio activation candidate — 2026-09-04

## Evidence and decision

The supervised 0.3.22 attach reached the exact GPU at 94.5 seconds, then timed
out waiting for audio at 120.9 seconds. With the TV powered on at its HDMI
input, read-only capture found connected HDMI and EDID but inactive output;
the audio function had snd_hda_intel and an ALSA card. PipeWire's profile was
Off, HDMI profiles unavailable, and ELD lacked valid monitor information.
Evidence: release-worktree out/ally-0.3.22-audio-diagnosis.json,
out/ally-0.3.22-audio-card-diagnosis.json and out/ally-0.3.22-hdmi-eld.json.
Audio becoming available after display activation remains a hardware hypothesis.
The maintainer authorized this local sequencing candidate and tests.

## Contract

0.3.25 preserves exact identity, Up link, HDMI/EDID, session, idle game,
consent, journal acknowledgement, settling and one-shot gates. Before display
activation, audio requires readable PipeWire and one valid non-G1 rollback
sink. Zero G1 sinks means pending activation; multiple sinks remain blocked.
The shared mechanism durably saves and reads back rollback audio before target
configuration or restart. After restart it requires two matching exact G1
sink observations, selects that sink and verifies the default. Availability
is bounded by 40 observations and ten monotonic seconds, with command timeouts
capped by the remaining budget. Selection/default verification retain their
existing separate command bounds. No profiles, drivers, or buses are forced.

Config restoration alone is not proof of recovery after a queued restart.
Normal and interrupted recovery now execute the existing source mechanism,
including audio restoration, and verify a changed generation at the source
placement. Gamescope PID is part of that generation. A source-display snapshot
cannot substitute for audio recovery. Ordinary already-satisfied requests
remain no-ops; this change is limited to failed/interrupted recovery.

## Verification and deployment gate

Local validation passed: 954 backend tests (six skipped), 110 frontend tests,
architecture, compilation, TypeScript, production build and package checks.
Regression includes missing/ambiguous sinks, invalid rollback, save failure,
late sinks, slow reads, partially changed defaults and source-display recovery.
A separate read-only review checked sequencing and elapsed-time bounds.
This is not installed or hardware validated. Install only after shutdown,
confirmed power-off, detach and detached boot. One supervised attach must verify
TV picture, render/output, audio, terminal result and Portable rollback.
Shutdown-before-disconnect remains mandatory.
