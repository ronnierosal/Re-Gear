# Troubleshooting

**Audience:** supervised testers and support reviewers<br>
**Reviewed:** 2026-09-06<br>
**Maturity:** diagnostic guidance; not permission to mutate hardware

Use Re-Gear's bounded snapshot and support preview described in
[Diagnostics](https://github.com/ronnierosal/Re-Gear/blob/main/docs/DIAGNOSTICS.md).
Do not begin by posting raw logs or hardware identities.

## Common symptoms

### The eGPU is connected but Re-Gear does not recognize it

Check the categorical host profile, eGPU profile, USB4 authorization, required
topology functions, driver bindings, and link state. A GPU ID alone is not proof
of a supported eGPU profile. Incomplete or ambiguous evidence should remain
Unknown.

### The display connector says connected, but the TV is blank

Connector presence does not prove active output. Review the observed Gamescope
output, active display category, render GPU, restart generation, verification
stage, and recovery result. Earlier supervised attempts produced exactly this
symptom and safely returned to Portable. The cause was first a mismatched
private launch binding and then a root-created config that the Gamescope user
could not read. The corrected path subsequently completed one watched TV
transition. See the detailed
[historical device-specific incident](Ally-X-and-GPD-G1-Docking-Incident).

### The TV works, but sound still comes from the handheld

Display success does not establish audio success. Inspect the current default
SteamOS loopback sink and associate an external candidate with the freshly
verified eGPU audio function. PipeWire numeric node IDs are transient: resolve
one immediately before use, never store or accept one from the UI, and preserve
a verified Portable rollback target. Automatic default-sink selection has been observed in a supervised cycle, but
each new build and repeated cycle still needs its own verification.

### A TV transition falls back to the handheld

That fallback can be correct safety behavior. Record the exact build revision,
transition stage, public reason code, and whether Portable recovery was verified.
Do not repeatedly retry a hardware transition without diagnosing the earliest
divergence.

### Sleep or disconnect remains blocked

Treat stale, loading, incomplete, unavailable, or unknown evidence as a real
blocker. Clearing process clients alone does not establish safe physical eGPU removal.
Follow the exact profile policy; current validation requires shutdown before disconnect.

### The installed result does not match the source checkout

Compare the installed build metadata with the intended clean repository
revision and artifact manifest. A ZIP filename or timestamp is not provenance.
Do not claim a fix is installed until the runtime reports the expected identity.

## Reporting an issue

Start with [Help Improve Re-Gear](Help-Improve-Re-Gear) for support-preview steps, optional diagnostic commands, and a report checklist.

Search [open and closed GitHub issues](https://github.com/ronnierosal/Re-Gear/issues?q=is%3Aissue) first and update a matching issue when appropriate.

Include the symptom, expected behavior, Re-Gear version/revision, evidence category,
reproduction steps, and the redacted support preview. State whether the result
was simulated, installed, or intentionally tested on named hardware. Never
include credentials, private addresses, raw identifiers, or an unrestricted log
dump.

## Known disconnect and reconnect findings

Returning to the handheld can restore picture, controls, and sound while Steam,
Gamescope, or the audio service still owns external resources. This is the active
[resource-release experiment (#51)](https://github.com/ronnierosal/Re-Gear/issues/51),
with [audio ownership tracked separately (#52)](https://github.com/ronnierosal/Re-Gear/issues/52).
Do not interpret a normal Portable screen or silent audio as unplug permission.
Use the reviewed support preview above when reporting a result; no raw logs or
experimental probe scripts are needed for a player report.

Keep these distinct symptoms separate until evidence establishes a shared cause:

- [Delayed eGPU detection (#17)](https://github.com/ronnierosal/Re-Gear/issues/17).
- [Shutdown not completing (#18)](https://github.com/ronnierosal/Re-Gear/issues/18): lost networking alone does not establish power-off.
- [Built-in controls missing after startup (#19)](https://github.com/ronnierosal/Re-Gear/issues/19).
- [Sleep/power button failing when detached (#16)](https://github.com/ronnierosal/Re-Gear/issues/16): deferred separately from resource release.
- [Popup dismissal interrupting docking (#27)](https://github.com/ronnierosal/Re-Gear/issues/27) and [TV profile/HDMI readiness (#28)](https://github.com/ronnierosal/Re-Gear/issues/28).
- [Future sleep/wake restoration (#29)](https://github.com/ronnierosal/Re-Gear/issues/29): design and validation work, not an available live-disconnect capability.
