"""Pure, bounded compiler for an exact character-device cgroup deny policy.

Returns little-endian Linux eBPF instructions, suitable for the x86_64 target;
does not load, attach, authorize, or verify enforcement. Existing/open or passed
descriptors are outside this program's scope. A return of one permits only this
filter's decision, and does not override other kernel access controls.

Encoding references (Linux v6.16, not a claim about the installed kernel):
https://github.com/torvalds/linux/blob/v6.16/include/uapi/linux/bpf.h
https://github.com/torvalds/linux/blob/v6.16/include/linux/kdev_t.h
"""

import struct


MAX_DEVICES = 16
MAX_MAJOR = (1 << 12) - 1
MAX_MINOR = (1 << 20) - 1


def compile_device_filter(devices: tuple[tuple[int, int], ...]) -> bytes:
    """Deny all accesses to 1..16 distinct exact Linux character devices.

    Only immutable tuples of built-in integers are accepted. Sorting makes
    equivalent policies byte-identical. No wildcard, path, or executable input
    is accepted. Major/minor values use Linux's 12/20-bit device-number range.
    """
    if type(devices) is not tuple or not 1 <= len(devices) <= MAX_DEVICES:
        raise ValueError("device policy must contain 1..16 device tuples")
    for pair in devices:
        if type(pair) is not tuple or len(pair) != 2:
            raise ValueError("device must be an exact major/minor tuple")
        major, minor = pair
        if (type(major) is not int or type(minor) is not int
                or not 0 <= major <= MAX_MAJOR or not 0 <= minor <= MAX_MINOR):
            raise ValueError("device numbers must be Linux-range integers")
    if len(set(devices)) != len(devices):
        raise ValueError("duplicate device")

    # Fields: opcode, destination/source packed nibbles, offset, immediate.
    # LDX W loads unsigned context words. AND32 retains only device type;
    # JNE32 compares the entire unsigned word without sign-extension ambiguity.
    insns = [
        (0x61, 0x12, 0, 0),       # r2 = ctx->access_type
        (0x54, 0x02, 0, 0xffff),  # r2 &= 0xffff
        (0x56, 0x02, 2 + 4 * len(devices), 2),  # non-char -> allow
        (0x61, 0x13, 4, 0),       # r3 = ctx->major
        (0x61, 0x14, 8, 0),       # r4 = ctx->minor
    ]
    for major, minor in sorted(devices):
        insns.extend((
            (0x56, 0x03, 3, major),  # unequal major -> next rule
            (0x56, 0x04, 2, minor),  # unequal minor -> next rule
            (0xb4, 0x00, 0, 0),     # deny
            (0x95, 0x00, 0, 0),
        ))
    insns.extend(((0xb4, 0x00, 0, 1), (0x95, 0x00, 0, 0)))
    return b"".join(struct.pack("<BBhi", *insn) for insn in insns)
