"""Pure x86-64 LSM file_receive fixture compiler; no load or authority.

Only exact cgroups and character devices are covered. DMA-buf and inherited
descriptors are OUT OF SCOPE; successful compilation gives no clearance.
Offsets must come from independently validated running-kernel BTF: file inode
pointer (8 bytes), inode mode (2 bytes), inode rdev (4 bytes).
References: https://docs.kernel.org/bpf/prog_lsm.html and Linux v6.16
include/uapi/linux/bpf.h, include/linux/kdev_t.h. Helpers 80 and 113 are
get_current_cgroup_id and probe_read_kernel respectively.
"""
import struct

from .device_filter_program import compile_device_filter


def compile_device_receive(cgroup_ids, devices, *, file_inode_offset,
                           inode_mode_offset, inode_rdev_offset):
    """Emit instructions only; caller must separately verify BTF field types."""
    if (type(cgroup_ids) is not tuple or not 1 <= len(cgroup_ids) <= 2
            or any(type(v) is not int or not 0 < v < 2**64 for v in cgroup_ids)
            or len(set(cgroup_ids)) != len(cgroup_ids)):
        raise ValueError('one or two distinct exact cgroup IDs required')
    compile_device_filter(devices)  # Share strict immutable device validation.
    for offset, size in ((file_inode_offset, 8), (inode_mode_offset, 2),
                         (inode_rdev_offset, 4)):
        if type(offset) is not int or not 0 <= offset <= 32767 - size:
            raise ValueError('bounded BTF byte offset required')
    insns, labels, jumps = [], {}, []
    def emit(op, dst=0, src=0, off=0, imm=0):
        signed = imm if imm < 2**31 else imm - 2**32
        insns.append((op, dst | src << 4, off, signed))
    def jump(op, label, dst=0, src=0, imm=0):
        jumps.append((len(insns), label))
        emit(op, dst, src, imm=imm)
    def read(base, offset, size, stack):
        emit(0xbf, 1, 10)
        emit(0x07, 1, imm=stack)
        emit(0xb7, 2, imm=size)
        emit(0xbf, 3, base)
        emit(0x07, 3, imm=offset)
        emit(0x85, imm=113)
        jump(0x55, 'deny', imm=0)
    emit(0x61, 0, 1, off=8)  # Prior LSM result: preserve any prior denial.
    jump(0x55, 'exit', imm=0)
    emit(0x79, 6, 1)
    emit(0x85, imm=80)
    for group in sorted(cgroup_ids):
        emit(0x18, 8, imm=group & 0xffffffff)
        emit(0, imm=group >> 32)
        jump(0x1d, 'scoped', src=8)
    jump(0x05, 'allow')
    labels['scoped'] = len(insns)
    jump(0x15, 'deny', dst=6)
    read(6, file_inode_offset, 8, -8)
    emit(0x79, 7, 10, off=-8)
    jump(0x15, 'deny', dst=7)
    read(7, inode_mode_offset, 2, -16)
    emit(0x69, 0, 10, off=-16)
    emit(0x54, imm=0xf000)
    jump(0x56, 'allow', imm=0x2000)
    read(7, inode_rdev_offset, 4, -24)
    emit(0x61, 0, 10, off=-24)
    for major, minor in sorted(devices):
        jump(0x16, 'deny', imm=(major << 20) | minor)
    labels['allow'] = len(insns)
    emit(0xb7, imm=0)
    jump(0x05, 'exit')
    labels['deny'] = len(insns)
    emit(0xb7, imm=-13)
    labels['exit'] = len(insns)
    emit(0x95)
    for index, label in jumps:
        op, regs, _, imm = insns[index]
        insns[index] = op, regs, labels[label] - index - 1, imm
    return b''.join(struct.pack('<BBhi', *row) for row in insns)
