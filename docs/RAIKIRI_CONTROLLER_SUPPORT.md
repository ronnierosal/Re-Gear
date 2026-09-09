# Raikiri II menu support foundation

Target: left extra button opens Steam's main menu; right extra button opens
Quick Access, matching the user's built-in Ally controls. USB cable, wireless
dongle, and Bluetooth require independent evidence.

Implemented: pure menu routing with exact device/transport matching, explicit
verification, press-edge deduplication, reconnect baselining, and suppression
of simultaneous extra-button chords. Menu actions are separate from HDM dock,
power, and GPU actions. Tests use synthetic button identifiers only.

Also implemented locally: standalone experimental Linux diagnostic
`scripts/raikiri_probe.py`, including passive capture, opt-in single activation,
and source-derived candidate decoding. Tests are synthetic, not hardware
recordings. No Steam menu delivery, enabled Raikiri profiles, configuration UI,
or installation exists. The plugin does not import or launch this tool.

## Hardware integration gate

1. Record actual controller identity, firmware, PC/Xbox mode, transport, and
   input interfaces without storing serial numbers in public diagnostics.
2. Observe left extra, right extra, L3, R3, and Xbox button separately using
   read-only capture. Do not grab devices or change controller configuration.
3. Establish whether extra buttons have distinct evdev or vendor HID signals.
   Never map ordinary stick-click events globally to menus. If indistinguishable,
   report the limitation and investigate firmware/vendor protocol separately.
4. Bind a decoder/profile only to verified identity and transport. The pure
   router consumes ordered full snapshots from that decoder, not raw packets.
   Maintain one state per device/transport; reset on profile replacement,
   disconnect, lost capture, or decoding failure. Use a new session on reconnect.
5. Verify the supported Steam menu delivery mechanism before wiring an opt-in
   adapter. Preserve normal game input; avoid duplicate menus if Steam already
   handles the buttons. No keyboard injection or virtual controller is enabled.
6. Test press/hold/release, both extras together, stick clicks, reconnect,
   plugin unload, normal gameplay, and all three transports on the real unit.

## Experimental diagnostic (2026-09-06)

Tracking: [issue #23](https://github.com/ronnierosal/Re-Gear/issues/23).
Exact target is USB PC-mode dongle `0b05:1c92`; Bluetooth and other products
are rejected. A descriptor-matched vendor endpoint must contain B0 input/output
and B3 input, each 64 bytes including report ID, under FF03/FFC3 usages.
Discovery uses sysfs, then validates identity and descriptor again on the opened
handle. Missing permission or an unexpected descriptor stops the probe; it does
not install udev rules, bind drivers, grab gamepad input, or repair devices.

Source evidence:
- [RaikiriMapper SetKeyEvent](https://github.com/notyesbut/RaikiriMapper/blob/c579915baf819a530ad6f6cb65e06f960f2a7a5a/src/RaikiriMapper.Windows/SetKeyEventProtocol.cs)
  uses `B0 51 36 01 00 01` padded to 64 bytes, including report ID.
- [Reader](https://github.com/notyesbut/RaikiriMapper/blob/c579915baf819a530ad6f6cb65e06f960f2a7a5a/src/RaikiriMapper.Windows/RaikiriPaddleReaderService.cs)
  identifies ACK `B0 51 36 01` and rejection `B0 FF AA`. The author's
  nonpersistent/idempotent claim is not independent firmware validation.
- [ShadowLink](https://github.com/Retholtz/ShadowLink/blob/60639a2a08feef911a58238d098f9b2d3324e4b5/app/src/main/java/com/retholtz/shadowlink/Hardware.kt#L290-L300)
  decodes B3 bank 2, bytes 5/6 as Command/Library. Physical left/right assignment
  and release behavior still require player captures. Rear bank 0 labels are
  diagnostic candidates, not certified physical paddle numbering.

These protocol facts were independently implemented without copying upstream
code. Every decoded button remains `verified: false`. No event reaches the menu
router. Unlike the reference mapper, this diagnostic sends only one 64-byte
command: no retry, 65-byte fallback, or passive continuation after rejection.
Pre-write packets are recorded as baseline and cannot acknowledge activation.
Timeout/rejection stops; acknowledgement alone never proves working buttons.
Do not run concurrent ASUS writers: the protocol has no transaction nonce and
cannot distinguish another application's acknowledgement after our write.

Offline commands (Windows or Linux; no device I/O):

```text
python scripts/raikiri_probe.py --help
python scripts/raikiri_probe.py replay capture.jsonl
python -m unittest discover -s tests -p test_raikiri_probe.py -v
```

Future supervised Linux session only; these were NOT run on hardware:

```text
python scripts/raikiri_probe.py list
python scripts/raikiri_probe.py capture --label baseline --seconds 10 --output baseline.jsonl
python scripts/raikiri_probe.py capture --enable-events --label extra-left --seconds 20 --output extra-left.jsonl
```

Wait for the flushed `ready` record before pressing the labeled button. Files
are exclusively created with mode 0600 and never overwritten. Capture is bounded
to 120 seconds and 4096 reports. Raw vendor data stays local; do not publish it
without review. No serial, raw device path, or host identity is added to JSONL.
Disconnect/error closes the handle, leaves a stopped record, and never retries.
The probe does not send a disable command on exit because no reviewed inverse
is established; stream persistence/reset remains a hardware test question.
The three-second acknowledgement deadline starts after the single OS write
returns; kernel/device I/O latency is not covered by that deadline. Linux hidraw
report-ID handling follows the [kernel API](https://docs.kernel.org/hid/hidraw.html).

First compare a rear paddle positive control, each front extra, and actual
L3/R3 in separately labeled captures. Repeat release/hold and mixed inputs,
then cold reconnect before designing runtime delivery. No reports or unknown
layout is a diagnostic result, never grounds for guessing offsets or IDs.

## Router integration limits

The future adapter must own the active capture epoch and discard all callbacks
from retired sessions; session strings alone are not ordered. Reset state when
the active capture changes. Simultaneous suppression applies only to buttons in
one snapshot: staggered left then left+right can already emit a left action.
Do not claim protection against physical programming chords without actual
timing evidence or a separately designed delay policy.

ASUS documents default R3/L3 behavior and GP Companion requirements in its
[Raikiri II FAQ](https://rog.asus.com/us/support/faq/1056259/).
That documentation is context, not proof of this unit's Linux reports.
