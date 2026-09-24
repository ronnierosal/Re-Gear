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
the export reader is credited below.

## Gamescope PipeWire export protocol

The original read-only Python export reader implements the private
`gamescope_pipewire` v1 protocol using the existing Re-Gear Wayland transport.
Protocol names, signatures and opcode ordering derive from Valve's description
at Gamescope revision `05949f8149bb5d16b006624d319a76e2433caf4c`:
https://github.com/ValveSoftware/gamescope/blob/05949f8149bb5d16b006624d319a76e2433caf4c/protocol/gamescope-pipewire.xml

The protocol description carries this notice:

Copyright © 2021 Valve Corporation

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

## Native brightness and volume API contract

The Command Center utility adapter uses API contract evidence from Valve's Steam
client source archived by SteamDB / SteamTracking contributors at
[revision af2c67ecde70cf2c7a655326a0c7df1233732ce2](https://github.com/SteamDatabase/SteamTracking/blob/af2c67ecde70cf2c7a655326a0c7df1233732ce2/ClientExtracted/steamui/chunk~2dcc5aaf7.js),
and the Decky UI contributors' System Display/Audio type declarations distributed
with the existing `@decky/ui` dependency. The evidence establishes native method
names, callback payloads, normalized values, and the legacy `AllOutput = 1`
audio direction. Reuse type: interface research; no Steam implementation or
assets are copied. Re-Gear implements its own subscription lifetime, observation
store, user dispatch, and menu-generation guard. These references do not establish
compatibility with every installed Steam client.

## Automatic per-game graphics profiles

The design of Re-Gear's per-game graphics profiles was informed by two external
sources. Neither contributed code, tests, text or assets, and no source file
from either project is copied or adapted. Detailed evidence, including the
sources this work could not reach, is in
[graphics profiles research](docs/GRAPHICS_PROFILES_RESEARCH.md).

SteamTinkerLaunch by sonic2kk and contributors, GPL-3.0-or-later,
https://github.com/sonic2kk/steamtinkerlaunch — wiki page
[Configuration Files](https://github.com/sonic2kk/steamtinkerlaunch/wiki/Configuration-Files)
as read on 2026-09-22. An exact revision could not be pinned from the
implementing environment, which is recorded as an open item rather than
approximated. Reuse type: inspiration only. It informed the decision to key
per-game state by Steam AppID, which SteamTinkerLaunch stores under
`gamecfgs/id/<AppID>`. Re-Gear independently implements its backup, provenance
and restoration behavior; that page documents no backup of a game's own
configuration, so nothing there informed that design. Re-Gear additionally keys
state by canonical target path, which AppID alone does not distinguish.

The Unreal Engine `GameUserSettings.ini` layout used by Re-Gear's first schema
adapter was observed in a published UE4 configuration file,
[stereolabs/zed-unreal-examples](https://github.com/stereolabs/zed-unreal-examples/blob/master/UE4_Examples/Config/DefaultGameUserSettings.ini)
(MIT), as read on 2026-09-22. Reuse type: inspiration only — section names, the
`sg.*` scalability keys and the `Version` key, which are facts about a
configuration format. Re-Gear's fixture contents are written for this
repository, and no shipped game's configuration has been verified, so this
establishes a mechanism demonstration rather than support for any real game.

## Inert frame-generation provider model

The design of Re-Gear's inert frame-generation provider and target resolver was
informed by PancakeTAS and the LSFG-VK contributors. The pinned research baseline
is LSFG-VK tag `2.0.0`, commit
`2333707d55b68ddd8066fd95404c3b7d07e00d3a` (annotated tag object
`6a5450f91f7b2b6b1ad852957a111377d37b9023`):
https://lsfg-vk.dev/blog/release-v2.0.0/

Its provider constraints, environment contract, explicit player opt-out, and
separation between a provider plan and provider installation informed the model.
The environment contract reviewed for those boundaries is at:
https://lsfg-vk.dev/docs/configuration/environment-variables/
The pinned LSFG-VK license is CC BY-NC-ND 4.0:
https://git.lsfg-vk.dev/lsfg-vk/plain/LICENSE.txt?id=2333707d55b68ddd8066fd95404c3b7d07e00d3a
The Creative Commons license terms were reviewed at:
https://creativecommons.org/licenses/by-nc-nd/4.0/

Valve's Gamescope documentation informed the compositor and frame-limiter
boundary; AMD GPUOpen's FidelityFX Super Resolution 3 documentation informed the
distinction between generated presentation frames and the base render rate; and
the OptiScaler contributors' documentation informed the alternative-provider and
anti-cheat risk boundaries. These mutable sources were read on 2026-09-22:

- https://github.com/ValveSoftware/gamescope
- https://gpuopen.com/fidelityfx-super-resolution-3/
- https://github.com/optiscaler/OptiScaler

Reuse type for all sources in this section is research and inspiration only.
Re-Gear independently implements the inert provider interface, target selection,
evidence requirements, and fail-closed planning behavior. No upstream source
code, assets, DLLs, binaries, or dependencies were copied, adapted, bundled, or
executed. The proprietary Lossless Scaling application and its components must
be supplied by the user and are not redistributed by Re-Gear. These credits do
not establish production admission, license compatibility, or upstream
endorsement. Detailed evidence and current limitations are recorded in
[the frame-generation research note](docs/research/frame-generation.md).
