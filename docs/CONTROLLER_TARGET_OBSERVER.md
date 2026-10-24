# Bounded virtual-controller timing observer

Issue #506 owns this standalone diagnostic and its fixtures. It has no production
registration, RPC, command-line entry point, background worker or automatic
device discovery. Importing the module performs no I/O. Development validation
uses synthetic records and injected or completely mocked syscall ports only.
This is not permission to run it on a device.

## Caller contract

A separately authorized caller must freshly verify one virtual evdev target and
supply `VerifiedTarget`: its exact `/dev/input/eventN` path, filesystem device,
inode and character-device identity, a local monotonic verification time, virtual
target provenance, the two verified virtual key codes named `menu` and `a`, and
the input-event ABI. These labels are caller-supplied roles, not guesses about a
particular controller or raw R4 mapping. There are no default key codes.

The receipt must be at most two monotonic seconds old, with no future timestamp.
The observer does not establish virtual identity from a boolean: the caller must
retain the independent identification evidence. Symlinks, non-character nodes,
identity mismatch and malformed, stale or unsupported receipts are rejected.
Identity is checked before open, on the opened descriptor, and before each read.
The descriptor is opened once with `O_RDONLY | O_NONBLOCK | O_CLOEXEC |
O_NOFOLLOW`; there is no reopen, scan, write, ioctl, grab, injection, remapping,
permission change, profile change, command execution or service operation.

The real adapter is Linux-only and rejects an ABI inconsistent with the native
long size or byte order before accessing a node. Synthetic fixtures cover
32/64-bit and little/big-endian decoding. Fixture coverage does not qualify any
installed kernel, Decky runtime, target or hardware profile.

## Bounds and results

`observe(target, io=..., limits=..., cancelled=...)` is synchronous and explicit.
The default observation deadline is 45 monotonic seconds; a caller may shorten
but cannot extend it. Poll requests are at most 100 ms (default 50 ms), also
limited by remaining time. Cancellation/deadline are checked before opening,
after polling, before/after reading and during decoding. Cleanup always runs.
There is no promise to preempt a kernel syscall or scheduler delay; native timing
and descriptor behavior remain unqualified until the separately approved trial.

Defaults bound input to 2,048 records and output to 64 facts. Hard ceilings are
4,096 records, 128 facts and 4,096 poll iterations. Each read requests at most 32
records, bounded by the remaining record allowance. Unrelated input still counts
toward the bound, but its values are never emitted.

Facts contain only fixed role labels, press/release/repeat/duplicate-press or
overlap kind, relative microsecond offsets and durations for observed intervals.
They contain no node path, device identities, raw key codes, absolute kernel
timestamps, raw input bytes, file contents or exception text. A release without
an observed press has no duration. A repeat alone establishes no prior press
duration or complete chord. Duplicate press events do not reset a held interval.
Only overlapping intervals with both presses observed produce overlap duration.

Partial/truncated or oversized reads, disconnect, read/poll errors, identity loss,
invalid event values, kernel timestamp regression/excessive span, local clock
regression, `SYN_DROPPED`, cancellation or a bound stop collection. Event loss is
not recovered with ioctl. Kernel timestamps are checked independently from the
local monotonic lifetime clock; no clock-changing ioctl is issued. A close error
reports `descriptor_closed=False`; no close/reopen retry risks a reused descriptor.
The caller must treat that outcome as unresolved cleanup, not successful capture.

`timing_valid` means only that the returned prefix ended at deadline/cancellation
without a detected timing/input error. It does not mean that a chord completed,
that either button was initially released, that a mapping works, or that any
native acceptance gate passed. An incomplete observed press remains incomplete.
Virtual-output silence cannot establish whether raw R4 emitted anything or what
Steam consumed. A positive translated event is not evidence of Steam handling.

## Later supervised evidence and rollback

Class C/hardware-required remains. No live device was opened during this software
milestone. A later session needs fresh explicit authorization for each capture,
fresh exact target/ABI/readability evidence and a neutral screen where A cannot
confirm or launch anything. Observe the working manual chord once, stop and
inspect; only a separate approved step may observe R4 once. Preserve installed
0.3.190 and the existing Controller/lifecycle ownership and rollback artifacts.
No deployment, installation, plugin package, restart, InputPlumber test, evtest,
firmware, target/profile, power or persistent permission action follows.

Software validation includes the fixture suite, architecture, applicable backend
and golden checks, compilation, exact-source CI and independent review. Bind the
commit, base and source-review artifact checksum before proposing a device step.
Rollback for this unregistered source seam is reverting its isolated commit;
there is no installed change to roll back.

Protocol references (documentation only; no third-party code copied):
[Linux input event codes](https://docs.kernel.org/input/event-codes.html) and
[Linux evdev interface](https://www.kernel.org/doc/html/latest/input/input.html).
