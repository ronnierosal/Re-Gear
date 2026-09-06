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
of the exact GPD G1 profile. Incomplete or ambiguous evidence should remain
Unknown.

### The display connector says connected, but the TV is blank

Connector presence does not prove active output. Review the observed Gamescope
output, active display category, render GPU, restart generation, verification
stage, and recovery result. Earlier supervised attempts produced exactly this
symptom and safely returned to Portable. The cause was first a mismatched
private launch binding and then a root-created config that the Gamescope user
could not read. The corrected path subsequently completed one watched TV
transition. See the detailed
[Ally X and GPD G1 incident](Ally-X-and-GPD-G1-Docking-Incident).

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
blocker. Clearing process clients alone does not make physical G1 removal safe.
The current profile still requires shutdown before disconnect.

### The installed result does not match the source checkout

Compare the installed build metadata with the intended clean repository
revision and artifact manifest. A ZIP filename or timestamp is not provenance.
Do not claim a fix is installed until the runtime reports the expected identity.

## Reporting an issue

Search [open and closed GitHub issues](https://github.com/ronnierosal/Re-Gear/issues?q=is%3Aissue) first and update a matching issue when appropriate.

Include the symptom, expected behavior, Re-Gear version/revision, evidence category,
reproduction steps, and the redacted support preview. State whether the result
was simulated, installed, or intentionally tested on named hardware. Never
include credentials, private addresses, raw identifiers, or an unrestricted log
dump.
