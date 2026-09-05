# Prepared eGPU removal research — 2026-09-05

Status: diagnostic foundation only. No removal executor, new player ZIP,
remote deployment, hardware operation, or safe-unplug support is included.

## Findings

Linux 6.16 has different amdgpu callbacks for PCI removal and machine shutdown.
`amdgpu_pci_remove` calls DRM unplug, resumes/forbids runtime PM when applicable,
unloads KMS, disables the PCI device and waits for pending transactions.
`amdgpu_pci_shutdown` instead suspends device IP blocks. Consequently an attached
shutdown hang does not prove orderly PCI removal is impossible, and neither
path's existence proves success on this device. This is upstream source evidence;
the installed Valve kernel's exact patched source must still be compared.

Source: https://raw.githubusercontent.com/torvalds/linux/v6.16/drivers/gpu/drm/amd/amdgpu/amdgpu_drv.c

Thunderbolt deauthorization requires domain capability support. It destroys the
PCIe tunnel and acts like hot-remove. It must not be used as a shortcut to closing
GPU clients. Nor does deauthorization prove USB peripherals, other tunnels,
firmware, or the next authorization cycle are clean. The USB4 port offline
interface is documented for retimer firmware maintenance, not general GPU eject.

Source: https://www.kernel.org/doc/html/v6.16/admin-guide/thunderbolt.html

## Implemented diagnostic

`scripts/capture_egpu_removal_capabilities.py` inventories domain deauthorization
support, security/IOMMU state, router authorization, identity and NVM version.
It performs bounded sysfs reads only. Missing/malformed capability is unknown,
not false success. Domain association uses actual sysfs ancestry, never a name
prefix guess. GPU-to-router binding remains explicitly unverified, and
safe_to_unplug always remains false. Reports can include device UUIDs: retain
locally and redact before publishing. No shell command execution or write path.

Six local fixture tests cover unknown/malformed evidence, unsupported capability,
no guessed router binding, inventory bounds, and no removal authorization even
when the capability is present. Architecture and compile checks pass. Actual
Linux sysfs topology and hardware behavior remain untested for this collector.

## Remaining gates before a supervised experiment

1. Capture capability inventory and exact installed kernel lineage.
2. Bind the intended GPU and all sibling PCI/USB functions to the exact router;
   enumerate storage, audio, input, DRM clients and memory mappings. Incomplete
   visibility must block the trial; an empty process list is not sufficient.
3. Verify Portable display/render/audio, no game, stable device generation and
   no consumers reopening the GPU. Pause automatic reconnect transitions through
   the existing transition owner; do not race a teardown with automatic docking.
4. Review a separate narrowly scoped removal mechanism with before/after kernel
   evidence, bounded observation and recovery policy. A userspace timeout cannot
   cancel a blocked kernel sysfs write; never issue competing reset/retry writes.
5. First prove software release with the cable attached under supervision. Only
   a later explicitly approved hardware milestone may change unplug guidance.
6. Treat reconnect as a new identity/generation and re-run complete readiness.
   A clean firmware state is a test outcome, not an assumption.

## Separate controller evidence

The player reported successful full detached shutdown with the temporary console
settings, no visible diagnostic text, then a boot with controller failure but
working screen/audio. They also reported a charger-only boot with failed input.
These reports weaken an exclusively G1/forced-off explanation; charger causality
and SteamOS compatibility remain unproven. They do not establish a removal fix.
The user is away from the Ally; no hardware is to be operated during this work.
