# Third-party notices

HDM was designed using validated behavior and engineering lessons from the
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
