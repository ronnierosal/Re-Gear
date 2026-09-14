# Safety and eGPU handling

Read the result and the instructions for your exact build before changing a dock
connection. A status label alone is not proof that a powered cable can be removed.

## For players — no technical background needed

One supervised v0.3.98 disconnect/unplug/replug cycle succeeded on its recorded
configuration. It has not established repeatability, other-hardware qualification
or sleep. Follow [the eGPU guide](egpu.md) for the procedure and limits. Outside
the exact supervised acceptance, restore handheld operation and shut down before
physical disconnection. Do not treat a missing picture as successful teardown.

Software reconnect is out of scope after the earlier unusual-heat incident.
Do not repeatedly retry a failed operation or use a developer command to turn an
intentionally disconnected, still-cabled dock back on. Report the result and build.

## Technical details — for advanced users and contributors

[Safety invariants](../../SAFETY_INVARIANTS.md), especially 10 and 20, remain
release-gate authority. The [lifecycle matrix](../technical/egpu-lifecycle.md)
preserves the success, earlier failures, exact artifact and evidence limits.
Read-only readiness tests do not execute a disconnect or qualify physical removal.
