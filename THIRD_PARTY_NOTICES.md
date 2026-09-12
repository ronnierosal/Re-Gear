# Third-party notices

Re-Gear was designed using validated behavior and engineering lessons from the
MIT-licensed eGPUBridge project:

- Source: https://github.com/ronnierosal/eGPUBridge
- Frozen reference commit: `ef04f65f1d35887ada69ef6a11807e6db0ae1c0d`
- Original copyright: Copyright (c) 2026 Vova + GPT

The root-to-user systemd query design was informed by the frozen reference's
validated SteamOS behavior. No eGPUBridge source file was copied into this
repository. If a later change copies or substantially derives implementation
code, the relevant MIT copyright and permission notice must accompany that
portion.

## Steam app-details request helper

`src/steam-app-details-request.ts` adapts the one-request subscription and
timeout approach from `getAppDetails` in
[mcarlucci/decky-storage-cleaner, src/utils.ts](https://github.com/mcarlucci/decky-storage-cleaner/blob/932e6876dbf94b6feb4b033401139b193f9cc79a/src/utils.ts).

Upstream revision: `932e6876dbf94b6feb4b033401139b193f9cc79a`.
Attribution: mcarlucci and the Storage Cleaner contributors.
Upstream [LICENSE](https://github.com/mcarlucci/decky-storage-cleaner/blob/932e6876dbf94b6feb4b033401139b193f9cc79a/LICENSE)
contains GNU GPL version 3, whose full text is included in this repository's
`LICENSE`. Preserve this notice when distributing the adapted source. No
separate proprietary/OEM relicensing rights are claimed for this contribution.

Re-Gear changes include dependency injection, abort support, strict AppID bounds,
handling immediate/duplicate/late callbacks, and fail-closed exception cleanup.
The helper is not connected to a live Steam source by this change. It contains
no storage deletion, backup, or cloud synchronization operations from the plugin.

## PipeWire stream candidate evidence

The private stream candidate parser is an independent implementation informed
by PipeWire's protocol-provided client credentials and node ownership behavior
at revision `1cd56b0615bb8bd112d9a2865a41cfdf638692f6`:

- https://github.com/PipeWire/pipewire/blob/1cd56b0615bb8bd112d9a2865a41cfdf638692f6/src/modules/module-protocol-native.c#L657-L663
- https://github.com/PipeWire/pipewire/blob/1cd56b0615bb8bd112d9a2865a41cfdf638692f6/src/pipewire/impl-client.c#L183-L185
- https://github.com/PipeWire/pipewire/blob/1cd56b0615bb8bd112d9a2865a41cfdf638692f6/src/modules/module-adapter.c#L199-L202

Credit: PipeWire contributors. No PipeWire source code is copied or bundled by
this increment. The documented credential and lingering-node semantics inform
the parser's limits: a matching node/client join remains a candidate, not proof
of stream ownership, rendering or TV output. Research toward Valve's private
Gamescope stream export is separately linked in `docs/DOCKED_IGPU_LIVE_TRIAL.md`;
no implementation of that export protocol is included in this increment.

## Gamescope performance protocol

The original Python read-only wire client implements the private
`gamescope_control` v6 protocol. Protocol names, signatures and opcode ordering
were derived from Valve's protocol description at Gamescope revision
`3521d6bf058110ea09198db9e5ca87f395c25b9e`:
https://github.com/ValveSoftware/gamescope/blob/3521d6bf058110ea09198db9e5ca87f395c25b9e/protocol/gamescope-control.xml

The protocol description carries this notice:

Copyright © 2023 Valve Corporation

Permission is hereby granted, free of charge, to any person obtaining a
copy of this software and associated documentation files (the "Software"),
to deal in the Software without restriction, including without limitation
the rights to use, copy, modify, merge, publish, distribute, sublicense,
and/or sell copies of the Software, and to permit persons to whom the
Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice (including the next
paragraph) shall be included in all copies or substantial portions of the
Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR
OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE,
ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
OTHER DEALINGS IN THE SOFTWARE.
