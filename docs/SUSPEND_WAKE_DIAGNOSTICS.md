# G1 suspend/wake diagnostics

The Ally X + GPD G1 currently has an observed immediate-wake/suspend reliability
issue. Re-Gear does not infer its cause from the G1 being connected, nor does it
change any wake-source setting while unattended.

## Read-only evidence

The remote capture payload and an explicitly requested redacted support-bundle
preview may resolve the exact certified G1 profile and read only the existing
PCI `power/wakeup` and `power/runtime_status` attributes for the verified bridge
and its verified PCI functions. Their public output contains only:

- whether the exact G1 topology was applicable;
- the categorical bridge wake-capability state;
- aggregate enabled/disabled/unknown wake-capability counts; and
- aggregate active/suspended/unknown runtime-power counts.

PCI addresses, USB4 identities, paths, process identities, wakeup counters, and
raw sysfs values are not exported. An enabled capability is not proof that the
device caused a wake; a disabled or unreadable value is not proof that sleep is
safe. This evidence cannot release the G1 sleep guard, authorize disconnect, or
change device configuration.

Support-bundle collection is explicit and previewed before export. Wake evidence
is collected only for that preview; it is not part of Re-Gear's regular snapshot or
polling loop.

The remote-capture parser accepts wake evidence only when it matches this exact
aggregate schema and bounded count range. A malformed, extra-field, or
identity-bearing wake payload is rejected rather than retained as diagnostic
evidence.

`python scripts/compare_wake_captures.py BEFORE.json AFTER.json` compares two
already validated saved captures locally. It reports only whether aggregate
capability/runtime counts changed; it never connects to the Ally or exposes a
PCI function identity. An unchanged comparison is still inconclusive: it is
not proof of a wake cause, successful suspend, or suspend safety.

## Supervised validation gate

Actual suspend investigation is D6-only. With the player present and a known
recovery route, capture redacted before/live/after reports and record boot ID,
uptime continuity, kernel/AER observations, display/control/network health, and
the categorical wake diagnostics. Test one explicitly approved condition at a
time (G1 absent, then G1 attached) and stop immediately on a black display,
lost input/SSH, GPU reset/AER activity, unexpected teardown, or uncertain
result.

Do not disable a wake source, change PCI power control, reset USB4, unbind a
driver, suspend, or disconnect the G1 through the remote harness. A future
hardware conclusion requires repeatable supervised evidence that the system
actually suspended and restored a usable docked or portable state; until then,
the current G1 profile remains disconnect-before-sleep/shutdown-before-disconnect.
