# Controller provider catalog contract

Task: [#485](https://github.com/ronnierosal/Re-Gear/issues/485).
This is an inert software prerequisite for future controller settings. No
production module imports it. It changes no default controller, input timing,
profile, lifecycle, settings, RPC, UI, device or service behavior.

## Boundaries and read envelope

`ControllerProviderReader.read_snapshot()` supplies one `ProviderReadFrame`.
There is no installed reader, D-Bus dependency, command runner or filesystem
transport. The envelope is a Re-Gear injection contract, **not** a claim that
an installed daemon supports `GetManagedObjects` or any collection method.
The future reader must establish a coherent snapshot, read permissions,
provider/version compatibility, bounded transport and connection epoch.

`objects` is a plain dictionary from object path to interface dictionaries,
then property names to `PropertyRead(state, value)`. Values are decoded plain
data. Missing, unsupported and failed reads are categorical and have no value.
`interface_states` supplies explicit interface observations; interfaces present
in the object data also evidence declaration. Declaration does not prove read
permission, mutation support or successful device behavior.

`InputPlumberCatalogAdapter.collect_catalog()` requests one injected frame and
normalizes it. It keeps no prior snapshot, poller, background task or cache.
Reader failure/provider loss yields unavailable evidence with no old devices,
profile or order. Exception messages are never retained. No writer, capture,
interception, target/profile mutation, timer, reconnect or unload hook exists.

## Evidence semantics

`Observation` distinguishes known (including an empty tuple or empty profile
path), unknown, unsupported and error. Private normalized observations are
immutable copies. Source, composite, ordinary virtual target and D-Bus target
are separate provider roles; source role does not certify physical origin.
Unrecognized interfaces stay unclassified. Multiple interfaces on one path
produce one observation; identical names on different paths remain distinct.

Composite `Capabilities`, `TargetCapabilities` and `OutputCapabilities` remain
separate. Event-device `SupportedKeys` is numeric supported-key metadata, not a
captured press, semantic mapping, independently usable vendor button or proof
that R4 is distinguishable. Aggregate composite capabilities are not assigned
to individual sources or targets. `IdBustype` stays reported metadata; transport
is known only when source Udev `Properties.ID_BUS` explicitly reports `usb` or
`bluetooth`. Neither establishes a tested connection mode or built-in/external
identity.

`SourceDevicePaths`, `TargetDevices` and `DbusDevices` build explicit relations.
Missing references create no synthetic devices. References to incompatible
roles or one source/target shared by multiple composites remain ambiguous.
Two target/D-Bus views of one path remain one node. Association only describes
this supplied snapshot; an unreferenced source is not assumed to be external.

Manager `Version` and `GamepadOrder` are observed independently. Order is kept
as reported, including missing composite references. It is never Steam/game
Player 1/2 or discovery order. Profile name/path and persistent ID are private
reported metadata. The parser does not read profile files, serialize profiles,
bind reconnects by persistent ID, or prove persistent mappings/effective targets.

Epoch is supplied by the reader, not inferred from names, discovery position,
paths or generic IDs. The safe public summary derives opaque keys from epoch
and path; keys expire with epoch changes and confer no mutation authority.
It deliberately exposes counts/categorical states rather than raw interface
names, versions, capability text, device labels, profile paths or identifiers.
Physical origin, built-in/external identity and Steam order remain unknown;
effective target verification remains false.

Parser limits bound object/interface/property counts, list/string sizes, total
UTF-8 text bytes, data nodes and depth; injected limits can only reduce the
reviewed ceilings. Cycles, invalid UTF-8 and non-data objects are rejected. Oversized frames
yield no catalog devices. Malformed per-object/property reads preserve other
valid observations with categorical gaps; no values are silently truncated.
`enumeration_complete` is false for a partial/malformed normalized frame.

## Validation and future work

Inline sanitized fixtures cover multiple/identical devices, duplicate virtual
views, ambiguous/missing relationships, profiles, distinct capability evidence,
missing/malformed/denied properties, provider loss, epochs, bounds, immutable
copies, privacy and the absence of file/process/network I/O. Architecture,
compilation, applicable integration/golden checks, exact CI and independent
review precede integration. Software results do not certify hardware support.

Installed daemon introspection, a live read transport, production/RPC/UI wiring,
settings/profile persistence, selector mutations, physical-button capture and
mapping, ordering or suppression each require separately accepted scope and
ownership. A target request completing would still not prove effective targets;
the OS may own them. Preserve Ally X SteamOS behavior and canceled #479. There
is no Steam-file polling or mapper implementation in this slice.

## Source attribution

The independently written contract/parser uses public protocol facts as
evidence, with no copied upstream implementation, tests, text or assets:

- [InputPlumber composite API at ea60d873cca17edd1cb655ede26f557108135252](https://github.com/ShadowBlip/InputPlumber/blob/ea60d873cca17edd1cb655ede26f557108135252/src/dbus/interface/composite_device.rs).
- [InputPlumber manager at the same revision](https://github.com/ShadowBlip/InputPlumber/blob/ea60d873cca17edd1cb655ede26f557108135252/src/dbus/interface/manager.rs).
- [Event source](https://github.com/ShadowBlip/InputPlumber/blob/ea60d873cca17edd1cb655ede26f557108135252/src/dbus/interface/source/evdev.rs) and [Udev source](https://github.com/ShadowBlip/InputPlumber/blob/ea60d873cca17edd1cb655ede26f557108135252/src/dbus/interface/source/udev.rs).
- OpenGamepadUI's [selector](https://github.com/ShadowBlip/OpenGamepadUI/blob/0db5812f21e98d0a5ac70bb1b5a674f2f369c22c/core/ui/card_ui/gamepad/gamepad_settings.gd) and [mapper](https://github.com/ShadowBlip/OpenGamepadUI/blob/0db5812f21e98d0a5ac70bb1b5a674f2f369c22c/core/ui/card_ui/gamepad/gamepad_mapper.gd) motivate the future workflow; neither is implemented or adapted here.

InputPlumber is GPL-3.0-or-later. OpenGamepadUI's README and RPM metadata differ
(GPL-3.0-or-later versus GPL-3.0-only); Bazzite's Apache-2.0 repository license
does not relicense components. Any future material reuse and shared notices
change needs license/attribution review and accepted path scope first. See
[source attribution](SOURCE_ATTRIBUTION.md).

Rollback is a normal revert of these unused modules, tests and contract.
Documentation impact: Wiki; player feature publication remains separate.
