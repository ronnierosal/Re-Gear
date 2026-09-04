# Remote read-only validation

## Previous-boot shutdown evidence

After the maintainer confirms safe poweroff and a later boot, use the separate
developer-only reader when investigating the attached-G1 shutdown delay:

```text
python scripts/capture_shutdown_evidence.py --host <ally-ip> --identity-file <ssh-key>
```

It runs one fixed previous-boot journal query, bounded to 2,000 rows, 4 MiB and
10 seconds. Only allowlisted symptom counts, HDM unload checkpoint timings, and
coverage categories leave the remote process. Raw logs, paths, identities, and
exception text are not returned. The fixed payload hash identifies the reader,
not the prior boot's installed build. It writes no remote files, never uses sudo,
and does not enable persistent journaling or change shutdown behavior.

The schema-2 collector accepts `--boot previous|current` and
`--scope shutdown|kernel|services|plugin`. Default shutdown scope selects only
kernel, systemd and HDM-loader records; separate kernel/service/plugin reads
prevent a busy source from crowding another out of the bounded tail. Byte-array
MESSAGE values are decoded only within a 4 KiB UTF-8 bound; omitted, undecodable
and ambiguous values remain explicit coverage gaps. Raw message text never
leaves the remote classifier. Shutdown-phase counts do not prove poweroff.

For a separately supervised poweroff, begin a bounded live capture first:

```text
python scripts/capture_shutdown_live.py --host <ally-ip> --identity-file <ssh-key> \
  --seconds 180 --output out/shutdown-live-<unique-session>.jsonl
```

Wait for `Live shutdown capture ready` before the player requests shutdown.
This observes only newly arriving current-boot records for 30–300 seconds, up
to 2,000 rows / 4 MiB, and writes validated categorical summaries to an exclusive
local JSONL file. It changes no remote files or services. The reader terminates
only its own journalctl child; the local watchdog terminates only its own SSH
client. SSH loss and capture expiry are evidence boundaries, never physical
poweroff proof. Read retained previous-boot scopes after a later safe boot to
look for evidence after SSH disappeared. Missing late records remain unknown.

No previous journal, permission denial, malformed or size-limited output are
explicit evidence gaps. Even an observed tail is not a complete shutdown trace.
Plugin unload can mean an update. An unload-complete marker, journal EOF, or new
boot never proves physical poweroff; that field remains `unknown`. Do not use the
reader to authorize unplugging. See [shutdown review](G1_SHUTDOWN_REVIEW_2026-09-03.md).

The maintainer may capture bounded Ally state over SSH without installing a
remote agent, opening a listener, or writing a file on the handheld.

## Command

From the repository on the development computer:

```text
python scripts/remote_capture.py --host <ally-ip> --identity-file <ssh-key>
```

When the unprivileged report is incomplete, a second fixed read-only mode may
be used if the Ally already permits non-interactive sudo for the SSH account:

```text
python scripts/remote_capture.py --host <ally-ip> --identity-file <ssh-key> --root-read-only
```

The wrapper validates the destination, invokes OpenSSH without a shell, and
streams the fixed `remote_capture_payload.py` source to the Ally's `python3 -`
stdin. The payload imports HDM's installed read-only diagnostics, builds the same
bounded redacted support representation, and returns one JSON object on stdout.
It creates, edits, or removes no remote file.

The root read-only mode changes only the fixed remote interpreter command to
`sudo -n /usr/bin/python3 -`. It does not accept a remote executable, command,
path, PID, or shell fragment. The payload reports the categorical execution
privilege and the wrapper rejects a root request if the payload did not actually
run as root. Failure of passwordless non-interactive sudo stops the capture; the
wrapper does not prompt or retry with another mechanism. The operating system
may retain its normal sudo/audit record even though the collector itself writes
no remote files.

An unprivileged connection failure reports one fixed local category, such as
`ssh.authentication_failed`, `ssh.host_key_unverified`,
`ssh.connection_refused`, or `ssh.connection_timed_out`. HDM never prints SSH
stderr, remote commands, credentials, or host details. The harness does not
retry with a guessed account, key, port, or transport; correct SSH access must
already be configured before a later read-only capture is attempted.

The local result is created exclusively under `out/remote-captures/` by default.
Existing files are never overwritten. The report includes:

- collector source SHA-256 and no-write declaration
- hashed boot identity and bounded uptime
- categorical Steam/Gamescope/Decky process health counts without PIDs
- installed HDM version, static archive build label, and hashes of its fixed
  package manifest and critical plugin files. The label is only a short source
  revision from a clean archive and its version must agree with the installed
  package manifest; `uncommitted`, `unavailable`, invalid, or internally
  inconsistent metadata remains inconclusive.
- redacted HDM profile, GPU/display, game, blocker, and disconnect observations
- categorical G1 PCI wake-capability/runtime aggregates when the exact profile
  can be resolved (no PCI identity is returned)
- categorical collection errors

The report excludes hostnames, usernames, network addresses, PIDs, command
lines, environment values, raw hardware identifiers, and private paths.

To confirm that a saved capture's installed fixed files match this checkout,
without opening SSH again or printing hashes, run:

```text
python scripts/compare_capture_provenance.py out/remote-captures/capture-<timestamp>.json
```

It reports only `match`, `mismatch`, or `inconclusive`. A match is package
provenance evidence only; it does not prove the plugin is loaded, healthy, or
hardware validated.

## Important limitation

The streamed collector is not the live Decky plugin process. It therefore does
not own or observe the Decky-managed login1 sleep-inhibitor lease. The output
sets `sleep_guard.active` to `null`, gives the check result `not_observed`, and
records `plugin_lifecycle_sleep_guard_not_observed` as a limitation. Never use a
remote capture to claim the sleep guard is active or inactive.

An unprivileged SSH session may also be unable to read Gamescope's protected
environment. That is reported as incomplete evidence and remains fail closed.
Root read-only mode can complete more procfs evidence, but it still cannot
observe the separate Decky plugin process's live sleep-inhibitor lease and does
not authorize a transition or hardware action.

## Allowed use

- package and installed-file provenance
- read-only before/live/after snapshots
- game-state and disconnect-blocker investigation
- simulator/result retrieval
- deciding whether a supervised test is ready to begin

## Prohibited use

The harness has no command for suspend, reboot, service restart, process signal,
display/GPU/controller/audio mutation, USB4 reset, or eGPU removal. Do not extend
it with arbitrary remote commands, paths, PIDs, or shell fragments. Any action
that may remove SSH, networking, or visible control belongs to the supervised
D6 stage in [Deployment and validation strategy](DEPLOYMENT_VALIDATION.md).
