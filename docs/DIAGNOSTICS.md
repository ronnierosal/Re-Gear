# Read-only diagnostics

## Purpose

The plugin exposes one privacy-safe JSON snapshot. It observes current state and
derives a mode; it does not write configuration, restart services, control a
display, select a GPU, or signal a process. In 0.2 the Decky lifecycle also owns
the narrowly scoped login1 sleep-inhibitor lease.

From a source checkout on SteamOS:

```text
PYTHONPATH=backend python -m hdm.cli
PYTHONPATH=backend python -m hdm.cli --compact
```

Installing the Python project exposes the `hdm-diagnose` console entry point.
A normal Decky ZIP does not install `pyproject.toml` or a global console script;
from an installed plugin tree the current equivalent is:

```text
PYTHONPATH=<plugin-root>/backend python3 -m hdm.cli --compact
```

Do not claim that `hdm-diagnose` is globally installed by Decky until packaging
adds and verifies that launcher.

## Standard diagnostic interface roadmap

The current CLI emits the privacy-safe snapshot only. Phase 2 will provide one
architecture-appropriate packaged command (target UX: `hdm diagnostics`) backed
by a shared read-only composition rather than scraping Decky UI output. It must
remain bounded and include:

- HDM semantic version, full/short commit, build/artifact identity, and installed
  deployment record when available
- placement, health, game, host/eGPU profile, display/render, and link state
- bounded current transaction, recent transitions/failures, and recovery state
- relevant service state without arbitrary `journalctl` output
- categorical evidence gaps and collection timings

The report must be shared by the packaged CLI, Decky troubleshooting, remote
capture, and support collection where their privilege and lifecycle allow. A
separate CLI process cannot invent in-memory Decky action history or transaction
state; unavailable sources stay explicit. Deeper support collection remains a
separate preview/approval flow. No command may dump unrestricted logs, paths,
process identity, raw hardware IDs, addresses, or account/game identity.

Delivery adapters call `DiagnosticsApi.get_snapshot()` to receive the same
versioned dictionary without parsing CLI output. The Decky plugin is a thin
root-privileged wrapper around this API. Its explicit public allowlist also
covers support preview/export, reversible presentation preparation, guarded
process release, categorical Docked-iGPU watcher status/acknowledgement, and
explicit temporary verbose-logging controls. Transition approval or execution
is not public.

Build the Decky package from a source checkout with:

```text
pnpm install --frozen-lockfile
pnpm typecheck
pnpm build
python scripts/check_plugin_package.py .
python scripts/build_plugin.py
```

The distributable archive is written under `out/`. Its Quick Access view shows
the inferred mode, categorical system health, running-game state, render GPU
role, active display kind, hardware support tier, blockers, sleep-protection
state, and read-only eGPU disconnect readiness. It also shows progressive
connection readiness and the total snapshot duration. System health reuses the
same snapshot and does not create another collection loop. Refresh and
warning-preference controls do not change system state or release the
inhibitor. Support export writes only after an exact redacted preview and
one-time approval.

An optional controller-friendly troubleshooting section is off by default. It
derives categorical state, confidence, blocker codes, client categories,
resource types, and stage timings from the existing snapshot. It does not issue
hardware mutation and does not render stable hardware IDs, connector names,
vendor IDs, or process IDs. It also shows the categorical Docked-iGPU watcher
stage. If that read-only watcher enters Action Required, the only offered action
acknowledges and cancels its private watch so observation can resume; it cannot
approve or execute promotion. Closing/reopening the plugin hides the section
again. The section also shows only categorical controller/audio peripheral
observation state (mapped or unmapped plus evidence codes). It never exposes
input paths, sound-card paths, device names, addresses, or private bindings,
and it grants no controller or audio handoff authority.

When a future reviewed read-only source supplies the existing bounded
HDM-overhead assessment, Troubleshooting can display only observed cost plus
**game impact unknown**, deferred, incomplete, or unavailable. It never renders
the raw code or identity, does not claim performance safety, and does not start
or schedule a measurement collector.

While Quick Access or that section is hidden, HDM does not request its separate
Docked-iGPU, temporary-logging, peripheral-inventory, or action-history
statuses. Opening the section uses the existing snapshot refresh loop to request
them once per refresh; hiding Quick Access or the section clears those optional
values again. The always-rendered Decky panel uses at most one essential UI
snapshot every five seconds while Quick Access is closed; reopening it returns
to the ordinary adaptive cadence. This keeps normal gameplay observation limited
to the essential snapshot. Backend sleep protection is independent of this UI
cadence.

Even while the section is visible, those nonessential checks wait until the
same snapshot reports an exact idle game state. Running or unknown game state
retains only the essential snapshot and shows a short deferred message. This
does not pause the underlying safety snapshot, sleep protection, or any
already-enabled temporary diagnostic logging.

The essential snapshot likewise defers the expensive whole-process G1
client-resource scan while game state is running or unknown. Disconnect
readiness stays explicitly incomplete and unsafe in that interval; it never
uses the deferred scan to imply that removal is safe. The scan resumes only
after an exact idle observation.

The Quick Access panel does not convert that intentional incomplete readiness
into rapid polling. While a game is running it refreshes the essential snapshot
at most every five seconds; unknown game state uses the normal three-second
stable cadence. The player can still request an immediate read-only refresh.

Every packaged Decky archive includes static build metadata. The observed-state
view shows the HDM version and the first twelve characters of the source commit
only when the archive was built from a clean committed checkout. It shows
`uncommitted` or `unavailable` instead of guessing. This is provenance for the
installed package, not hardware-validation or certification evidence.

Troubleshooting may show a supplied public build comparison only when complete
schema-1 version, revision, and categorical match evidence is present. It never
compares local source itself; unavailable or malformed input stays unavailable.

The same view displays the snapshot's existing categorical health state
(`Ready`, `Recovering`, `Degraded`, or `Attention Required`) and bounded public
health blockers. The controller-facing attention section maps only recognized
health blockers to short messages, collapses unknown codes to one generic
review message, and never renders raw codes. It does not add a collection loop,
infer a workflow, change placement, or authorize any action. Older payloads
show health as unavailable rather than guessing.

The same snapshot may include a categorical eGPU attach-readiness status. It
uses the already collected topology delta and next snapshot only; it does not
add an RPC or polling loop, create a transition permit, or automatically dock.

Journey status keeps its first controller-facing view compact: it displays only
read-only sources that are currently connected, or one `Not connected` row when
none are. The explicit detail view retains every source and its unwired state.
Opening detail reveals that section without moving controller focus from its
toggle, so it can be closed immediately. This is presentation only and does not
request, infer, or authorize a journey action.

The same optional section may show up to three recent actions from the existing
bounded in-memory event log. Each row contains only time, a categorical action
kind, outcome, and event code. It persists nothing new and never exposes event
details, correlation IDs, hardware identity, or process identity.
Public action codes are bounded to the documented lowercase categorical format;
malformed codes are rejected before delivery.
Verified snapshot attach, removal, and display-loss candidates may appear as
topology actions; recording one never starts recovery or changes hardware state.

Support Preview includes the same bounded categorical peripheral state when the
read-only observer is available. It includes only complete/exact flags and
evidence codes; no private binding, inventory path, name, address, or sample
identity is exported.

## Evidence sources

- `/sys/class/dmi/id`: host profile
- `/sys/class/drm`: GPU, connector, mode, and hashed EDID observations
- `/sys/bus/pci/devices`: PCI identity/topology plus current link status for the
  exact already-verified eGPU bridge
- `/sys/bus/thunderbolt/devices`: authorization and hashed USB4 identity
- `/proc/<pid>/cmdline`: unique Steam Gamescope session and output arguments
- `/proc/<pid>/environ`: Mesa Vulkan selector cross-check
- `/proc/<pid>/fd`, `comm`, `stat`, and `cgroup`: exact certified-eGPU DRM and
  audio resource holders, bounded process names, process-instance fingerprints,
  and Steam-game ownership
- `/sys/class/block`, `/proc/self/mountinfo`, and `/proc/swaps`: storage routed
  through the certified G1 topology and whether it is mounted or swap-backed
- `/sys/fs/cgroup/user.slice`: running Steam game scopes for the observed
  Gamescope owner and an exact AppID only when recognized scope names agree
- `systemctl --user list-units`: fallback scope inventory when the user cgroup
  hierarchy is unavailable
- `/sys/class/input` and `/sys/class/sound`: read-only candidate inventory for
  controller/audio diagnostics; paths are hashed privately and are never shown
  in the Decky payload

The primary game detector reads the Gamescope owner's current cgroup hierarchy,
which avoids crossing from Decky's root service into a user D-Bus session. The
only subprocess fallback allowed is the exact read-only systemd scope inventory.
It runs without a shell. The root fallback uses a fixed `runuser`/`env` prefix
whose username and UID are derived from the Gamescope process owner. All
alternate commands and mutation-shaped arguments are rejected by the command
boundary.

Scope-derived AppID identity is currently retained only inside the read-only
game scan. Multiple/future scope formats leave it unknown, and it is not present
in the public schema or support bundle.

The production Docked-iGPU observer resolves the exact Gamescope user and binds
each watch to a hash of the Gamescope PID, Linux start time, and UID. A missing
or changed process generation fails closed. It attempts to arm only from exact
running Docked-iGPU evidence. Its serialized lifecycle uses a fifteen-second
ineligible cadence and five-second active cadence. Watch-only promotion-ready
is visible for one active interval and then cleared; Action Required quiesces
until acknowledgement. A supervisor retries transient startup or runner failure
after thirty seconds. The public
status contains only stage, reason code, bounded next-poll timing, and boolean
inspection/acknowledgement flags. Watch ID, AppID, scopes, profile identities,
eGPU identity, and observation generations remain private. The production
composition has no supervised-preview port, so `inspection_available` remains
false and no transition authority can be created.

## Interpretation

`confidence` is explicit:

- `verified`: required sources agree
- `observed`: data exists but does not meet a certification rule
- `unknown`: a required source is missing, unreadable, conflicting, or ambiguous

`blockers` explain why a later transition would be unsafe. A successful
diagnostic command can still report an Unknown or Degraded mode; command success
means the report was produced, not that the machine is safe to mutate.

Snapshot schema 2 adds `disconnect_readiness`. Schema 3 adds `sleep_guard`,
including whether the guard is required, active, and verified. A disconnected eGPU is not an
error and reports `applicable: false`. With an exact certified G1 present, the
scan fails closed unless both card and render nodes, every visible process FD,
and attached-storage usage can be inspected. Any exact resource holder or
mounted/swap storage makes `ready` false. This is evidence only: HDM does not
signal a process or remove hardware.

The report also has a top-level diagnostics schema `2`. It retains schema 1's
allowlisted stage names and millisecond durations for DRM, Gamescope, game
state, PCI, USB4, host, eGPU identity, disconnect clients, and total snapshot
collection. Timings carry no paths, device addresses, connector names, process
identifiers, or command output. Schema `2` adds the versioned
`hardware_profiles` record. It reports exact/absent/unknown host and eGPU profile
resolution plus independent typed capability rows for transport, display,
audio, controller, power-button, sleep, and removal behavior. Each row contains
only an axis, categorical value, confidence, and evidence basis. Delivery schema
`2` carries this record to Decky without exposing DMI strings, PCI/DRM names,
USB4 hashes, EDIDs, or stable device identities. Unknown or incomplete profile
sets keep composed handoff capabilities Unknown.

The CLI never acquires an inhibitor. The root Decky backend polls only the host,
DRM, PCI, and USB4 identity needed for the sleep lease. Candidate G1 presence
acquires a login1 `sleep`/`block` inhibitor; verified absence and plugin unload
release it. Unknown observations hold the current state. The exact
`systemd-inhibit` holder and its no-op child both carry Linux parent-death
signals, so plugin failure tears down the holder chain and releases the lock.

HDM verifies Portable only when the unique Steam Gamescope process, its
environment, one boot VGA GPU, and one active internal connector agree. It
verifies TV Docked only when the exact certified G1 topology, Gamescope GPU
selectors, and one connected external connector agree.

On the validated Ally X SteamOS build, the normal `deck` user cannot read the
Gamescope process environment even though it owns the process. An unprivileged
source-checkout run will therefore report `gamescope_environment_unreadable` and
leave render GPU and mode unknown. This is expected; do not weaken the rule.
The root Decky adapter exists specifically to make that protected environment
observable without changing the snapshot or inference policy.

## Privacy boundary

The Decky JSON output excludes command lines, DMI strings, PCI bus addresses,
raw or hashed hardware identity, connector names, vendor/device IDs, usernames,
hostnames, home paths, IP addresses, systemd stderr, PIDs, and process-instance
IDs. eGPU clients expose only a bounded `comm` name and categorical kind,
resource types, eligibility, and reason. Exact identities remain backend-only
for revalidation and never cross the Decky RPC boundary. Raw process start
times may exist only in the private backend snapshot used to defeat PID reuse;
they are stripped from Decky delivery and support export together with
cgroup paths, file-descriptor targets, and device paths.

Raw hardware evidence belongs in supervised, redacted test captures and is not
part of this default payload.

Support Preview performs one additional bounded game/GPU evidence pass only
when the user invokes that existing action. Idle or unknown game state skips
deep process and DRM inspection. For one exact running Steam game, HDM brackets
private runtime identity and samples the independently resolved internal and G1
render nodes within one shared snapshot/runtime window. Either target being
Unknown marks the comparison incomplete. The support event contains only categorical game exactness,
runtime type, client/activity states and counts, reason codes, and placement.
AppID, scopes, PIDs, process start times, executable data, PCI addresses, DRM
nodes, stable IDs, and evidence generations never enter the preview. Failure of
this optional pass records a categorical unavailable event and does not prevent
the base support preview.

## Temporary verbose logging policy

Normal bounded HDM events remain available for support bundles. Additional
verbose events are off by default and require explicit player confirmation.
The only allowed durations are 30 minutes, one hour, two hours (the default
selection), and until reboot. There is no permanent option.

The policy uses a monotonic deadline, returns automatically to normal logging at
expiry, sanitizes details before in-memory retention, and retains the existing
rotating event cap. Consent is held only in memory, so a plugin/service restart
disables verbose logging. An until-reboot
session also checks the current boot identity on every status/event operation;
a changed or unreadable identity disables the session fail closed. Boot identity
is used only for equality and is never exported.

Decky now exposes the four allowlisted durations, a Steam-native confirmation,
an identity-free status/countdown, and an immediate disable action inside the
opt-in troubleshooting section. While enabled, normal snapshot refresh records
one additional sanitized categorical event containing only mode, game state,
support tier, blocker codes, and up to 32 existing collector stage/duration
rows. The existing 128-event rotation remains authoritative. No raw snapshot,
arbitrary system log, durable consent, path, process identity, hardware
identity, or upload is introduced.

Audio handoff results also use normal journey events: component `audio`, stage
`select_tv` or `restore_portable`, a categorical `audio.*` result code, target,
and success boolean. No sink names, node IDs, or PCI identities are exported.
These describe default-sink selection, not proof of audible output or movement
of every existing stream. Reporting failure cannot interrupt the handoff.

Low-frequency connection-journey changes are normal events and do not require
verbose logging. Exact G1 presence, categorical attach-readiness changes,
automatic or supervised presentation attempts/results, Portable-return results,
and shutdown-request attempts/results record bounded monotonic `elapsed_ms`,
`stage_elapsed_ms`, and operation `duration_ms` where applicable. They also
write the same categorical code and timing to Decky's service journal. The
timeline begins only after HDM observes relevant hardware or a transition
request; it cannot measure the player's physical cable action. It resets after
verified absence and never records PCI IDs, DRM nodes, connector names, stable
identity, process identity, or physical-power-off success. A successful
power-off request always records `poweroff_complete=false` because only the
player can verify that fans and LEDs actually stopped.

Logging consent and support-export consent remain separate. Verbose events stay
in memory unless the player later creates and reviews a support bundle. The
controller-visible flow and expiry countdown remain unverified on hardware.
