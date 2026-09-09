# Controllers

**Audience:** players and input contributors<br>
**Reviewed:** 2026-09-08<br>
**Maturity:** routing foundations implemented; broader controls in development or research

Controller work aims to keep the built-in and external controls usable, make
navigation predictable, and expose supported configuration without interfering
with games. The [product contract](https://github.com/ronnierosal/Re-Gear/blob/main/docs/PRODUCT.md)
and [UI contract](https://github.com/ronnierosal/Re-Gear/blob/main/docs/UI_SPEC.md)
own the common behavior. Exact device/transport evidence belongs in
[compatibility records](Supported-Hardware).

## Capability areas

| Area | Intended benefit | Current status and remaining gate |
|---|---|---|
| Navigation and shortcuts | Reach display and disconnect workflows from a controller | Routing foundations exist; configurable combinations and physical delivery need separate implementation and native tests |
| Extra buttons | Use supported device-specific buttons without losing ordinary controls | Exact-device routing and a standalone diagnostic foundation exist; distinct input signals and Steam menu delivery remain unverified |
| Gyro | Make supported motion input understandable and reliable | Source research in [PR #154](https://github.com/ronnierosal/Re-Gear/pull/154), open at this review; no universal support or implemented gyro controls claimed |
| Rumble | Adjust supported intensity while preserving game effects | Research/backlog; sending a test vibration is not persistent game-effect gain control |
| Controller LEDs | Configure supported brightness, colors, or effects | Research/backlog; internal driver capability does not establish an available settings API |
| Player order | Keep built-in and external controllers usable while choosing order | Research/backlog; provider ordering, Steam order, and a game's player slots require separate evidence |

## How configuration should behave

Physical buttons request the same guarded actions as the interface. A shortcut
must not skip readiness checks or confirmation. The future controller module
will distinguish supported, unavailable, and unknown capabilities rather than
offering controls that cannot be verified.

For extra buttons, USB, wireless dongle, and Bluetooth need independent evidence.
An input that duplicates a stick click cannot safely become a global menu shortcut.
The [device-specific button investigation](https://github.com/ronnierosal/Re-Gear/blob/main/docs/RAIKIRI_CONTROLLER_SUPPORT.md)
records the existing foundation and limitations; its diagnostic is not launched
by the plugin.

**Priority:** controller capability and usability work, with hardware testing
performed separately. Next gates are exact input/provider discovery, bounded
adapters, UI integration, and reconnect/gameplay tests. This guide does not claim
that the research features are installed or working on a particular handheld.

## Troubleshooting and lessons

[Raikiri II extra-button troubleshooting](Raikiri-II-Troubleshooting) explains the
recorded Bluetooth L3/R3 duplication, PC-mode activation/capture investigation,
and unfinished native menu mapping. Transport-specific evidence stays separate
from the general controller feature direction.
