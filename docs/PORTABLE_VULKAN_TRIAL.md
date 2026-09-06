# Supervised one-shot Portable Vulkan launch

Status: installed in Re-Gear 0.3.53; the trial is not yet hardware validated.
This is a session launch-policy trial, not eGPU removal or safe unplug support.

Local verification: 1023 backend tests completed (eight platform skips), 181
frontend tests, typecheck, architecture, compilation, build and package contract
checks passed. All 11 store fixture tests also passed on Linux, including the
permission and symlink cases skipped on Windows. Independent bounded review and
real-file journal tests caught and resolved recovery-cancellation and metadata
ordering defects. No hardware transition was exercised.

## Bounded milestone

Continue the prepared-disconnect work using the existing presentation owner and
normal Gamescope session restart. No new process signal, driver, PCI, USB4, sleep
or device-removal operation is introduced. Ordinary Portable requests and
automatic transitions do not opt in. A separate developer-supervised approval
RPC issues a short-lived, single-use permit with trial mode bound to that exact
plan and observation generation; the existing Portable execute RPC consumes it.
The trial requires an exact idle TV-Docked source, current original launch
policy and existing verified profile/binding/integration gates.

## Launch and recovery

The mechanism persists the original launch config, expected normal Portable
config, operation, boot/attachment binding, internal identity and a bounded
deadline before changing config or requesting the existing session restart.
The wrapper durably consumes the one-shot record before validation or exec.
It rechecks boot, attachment, config, internal DRM card/connector ownership,
idle game scopes, Mesa layer availability and conflicting routing environment.
It changes only the new child arguments/environment; parent/session-manager
environment is never changed. A rejected or repeated launch uses ordinary
policy. A crash after consumption cannot replay the trial.

Recovery participation is bound to the exact trial-owned transition journal.
Recovery first cancels remaining trial authority, even when observation is
unknown. Restoring the original config and restarting retain existing identity,
idle and integration gates. A conflicting later config is not overwritten.
Records remain retained and block another trial; there is no automatic cleanup
or retrial. A future explicitly reviewed reconciliation step is required.

The only new RPC is `approve_supervised_portable_vulkan_trial`. It accepts no
device paths, commands, PIDs, environment or caller-selected GPU. Execute its
returned token through `execute_supervised_portable_switch`. Do not expose this
experimental approval in normal UI or automatic preferences.

## Evidence boundaries and hardware gate

`portable_trial.application_unverified` deliberately reports that a successful
Portable transition does not prove the trial applied. The consumed marker is
not an exec-success receipt. Explicit acknowledgement remains required and
automatic completion retains the Portable hold. Inspect new-session argv and
environment plus the player-visible Ally display/audio/controller result.
Then capture complete privileged G1 descriptors, mappings, client allocations,
storage and sibling-device evidence. Vulkan restriction is not a DRM sandbox.
No result from this trial can say safe to unplug.

Before any supervised run: install a fully verified combined artifact with G1
disconnected, confirm Portable health, then separately supervise attach and
idle TV-Docked readiness. Keep the cable attached throughout launch/recovery
and resource verification. Software removal and physical unplug are separate,
unimplemented milestones. Current policy remains shutdown before disconnect.
