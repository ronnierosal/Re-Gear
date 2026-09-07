"""Pure bounded Linux BTF layout inspection; no kernel loading or authority.

Linux v6.16 include/uapi/linux/btf.h defines records; kernel/bpf/bpf_lsm.c
and include/linux/lsm_hook_defs.h define int bpf_lsm_file_receive(struct file*).
The chained prior-return context slot is NOT a second FUNC_PROTO parameter.
Pointer width is supplied explicitly by a separately verified target ABI.
"""
from dataclasses import dataclass
import struct

MAX_BYTES = 64 * 1024 * 1024
MAX_TYPES = 1000000


@dataclass(frozen=True)
class FileReceiveLayout:
    hook_btf_id: int
    file_btf_id: int
    inode_btf_id: int
    file_size: int
    inode_size: int
    file_inode_offset: int
    inode_mode_offset: int
    inode_rdev_offset: int
    pointer_size: int
    mode_size: int = 2
    rdev_size: int = 4


@dataclass(frozen=True)
class DmaBufReceiveLayout:
    receive: FileReceiveLayout
    file_fop_offset: int
    file_private_offset: int
    dma_ops_offset: int
    dma_priv_offset: int
    gem_dev_offset: int
    drm_primary_offset: int
    minor_dev_offset: int
    minor_index_offset: int
    minor_type_offset: int
    dma_btf_id: int
    gem_btf_id: int
    drm_btf_id: int
    minor_btf_id: int
    dma_size: int
    gem_size: int
    drm_size: int
    minor_size: int


def parse_file_receive_btf(raw, *, pointer_size):
    return _parse_receive(raw, pointer_size=pointer_size, dma=False)


def parse_dma_buf_receive_btf(raw, *, pointer_size):
    """Layout only, not exporter classification or proof of absent importers.

    The caller must first compare f_op with verified dma_buf_fops, then ops
    with verified amdgpu_dmabuf_ops before interpreting the two void pointers.
    Source: Linux v6.16 drivers/dma-buf/dma-buf.c and
    drivers/gpu/drm/amd/amdgpu/amdgpu_dma_buf.c. Runtime reads must also check
    pointer validity, minor.dev backpointer, nonnegative index and primary type.
    """
    return _parse_receive(raw, pointer_size=pointer_size, dma=True)


def _parse_receive(raw, *, pointer_size, dma):
    if type(pointer_size) is not int or pointer_size != 8:
        raise ValueError("independently verified 64-bit pointer ABI required")
    if type(raw) is not bytes or not 24 <= len(raw) <= MAX_BYTES:
        raise ValueError("invalid BTF size")
    magic, version, flags, header, toff, tlen, soff, slen = struct.unpack_from("<HBBIIIII", raw)
    if magic != 0xeb9f or version != 1 or flags != 0 or header != 24:
        raise ValueError("unsupported BTF header")
    ts, te, ss, se = header + toff, header + toff + tlen, header + soff, header + soff + slen
    if (not tlen or not slen or max(te, se) != len(raw) or te > len(raw) or se > len(raw)
            or not (te <= ss or se <= ts) or toff % 4 or tlen % 4):
        raise ValueError("invalid BTF sections")
    strings = raw[ss:se]
    if strings[0] != 0 or strings[-1] != 0:
        raise ValueError("invalid BTF string table")
    def name(offset):
        if offset >= len(strings):
            raise ValueError("invalid BTF name offset")
        end = strings.find(b"\0", offset)
        if end < 0 or end - offset > 4096:
            raise ValueError("unbounded BTF name")
        try:
            return strings[offset:end].decode("utf-8")
        except UnicodeError as error:
            raise ValueError("invalid BTF name") from error
    types = [None]
    refs = []
    position = ts
    while position < te:
        if position + 12 > te or len(types) > MAX_TYPES:
            raise ValueError("truncated or excessive BTF types")
        noff, info, value = struct.unpack_from("<III", raw, position)
        kind, vlen, flag = (info >> 24) & 31, info & 65535, bool(info >> 31)
        if info & ~0x9f00ffff or not 1 <= kind <= 19:
            raise ValueError("unsupported BTF type")
        if kind not in (4, 5, 6, 7, 17, 18, 19) and flag:
            raise ValueError("invalid BTF kind flag")
        if kind not in (4, 5, 6, 12, 13, 15, 19) and vlen:
            raise ValueError("invalid BTF type length")
        if kind == 12 and vlen > 2:
            raise ValueError("invalid BTF function linkage")
        size = ({1: 4, 3: 12, 14: 4, 17: 4}.get(kind, 0)
                + (12 * vlen if kind in (4, 5, 15, 19) else 8 * vlen if kind in (6, 13) else 0))
        position += 12
        if position + size > te:
            raise ValueError("truncated BTF payload")
        words = struct.unpack_from("<" + "I" * (size // 4), raw, position) if size else ()
        position += size
        types.append((name(noff), kind, value, flag, words))
        if kind in (2, 8, 9, 10, 11, 12, 13, 14, 17, 18):
            refs.append(value)
        if kind == 3:
            refs.extend(words[:2])
        if kind in (4, 5, 13):
            width = 8 if kind == 13 else 12
            for index in range(0, len(words), width // 4):
                name(words[index])
                refs.append(words[index + 1])
        if kind in (6, 19):
            for index in range(0, len(words), 2 if kind == 6 else 3):
                name(words[index])
        if kind == 15:
            refs.extend(words[::3])
    if any(ref >= len(types) for ref in refs):
        raise ValueError("BTF reference outside type table")

    def resolve(type_id):
        seen = set()
        while type_id:
            if type_id in seen or len(seen) >= 64:
                raise ValueError("cyclic or excessive BTF modifiers")
            seen.add(type_id)
            item = types[type_id]
            if item[1] not in (8, 9, 10, 11, 18):
                return type_id, item
            type_id = item[2]
        raise ValueError("unexpected void BTF type")

    def unique(kind, selected):
        matches = [(i, item) for i, item in enumerate(types[1:], 1) if item[1] == kind and item[0] == selected]
        if len(matches) != 1:
            raise ValueError("missing or ambiguous BTF identity: " + selected)
        return matches[0]

    def integer(type_id, size, encoding):
        _, item = resolve(type_id)
        if item[1] != 1 or item[2] != size or item[4] != ((encoding << 24) | (size * 8),):
            raise ValueError("unsupported BTF integer representation")

    def member(item, selected, width):
        words = item[4]
        matches = [(words[i + 1], words[i + 2]) for i in range(0, len(words), 3) if name(words[i]) == selected]
        if len(matches) != 1:
            raise ValueError("missing or ambiguous BTF member")
        type_id, offset = matches[0]
        if item[3]:
            if offset >> 24:
                raise ValueError("bitfield layout unsupported")
            offset &= 0xffffff
        if offset % (width * 8) or offset // 8 + width > item[2]:
            raise ValueError("unaligned or out-of-range BTF member")
        return type_id, offset // 8

    hook_id, hook = unique(12, "bpf_lsm_file_receive")
    _, proto = resolve(hook[2])
    if proto[1] != 13 or len(proto[4]) != 2:
        raise ValueError("receive hook requires exactly one file argument")
    integer(proto[2], 4, 1)
    file_id, file_type = unique(4, "file")
    inode_id, inode_type = unique(4, "inode")
    _, argument = resolve(proto[4][1])
    if argument[1] != 2 or resolve(argument[2])[0] != file_id:
        raise ValueError("receive argument is not file pointer")
    pointer_id, file_offset = member(file_type, "f_inode", pointer_size)
    _, pointer = resolve(pointer_id)
    if pointer[1] != 2 or resolve(pointer[2])[0] != inode_id:
        raise ValueError("file inode is not inode pointer")
    mode_id, mode_offset = member(inode_type, "i_mode", 2)
    rdev_id, rdev_offset = member(inode_type, "i_rdev", 4)
    integer(mode_id, 2, 0)
    integer(rdev_id, 4, 0)
    receive = FileReceiveLayout(hook_id, file_id, inode_id, file_type[2], inode_type[2],
                                file_offset, mode_offset, rdev_offset, pointer_size)
    if not dma:
        return receive

    def pointer_member(container, selected, target_id):
        member_id, offset = member(container, selected, pointer_size)
        _, pointer = resolve(member_id)
        if pointer[1] != 2:
            raise ValueError("expected pointer member: " + selected)
        if target_id == 0:
            if pointer[2] != 0:
                raise ValueError("expected void pointer: " + selected)
        elif resolve(pointer[2])[0] != target_id:
            raise ValueError("pointer target mismatch: " + selected)
        return offset

    fops_id, _ = unique(4, "file_operations")
    ops_id, _ = unique(4, "dma_buf_ops")
    dma_id, dma_type = unique(4, "dma_buf")
    gem_id, gem_type = unique(4, "drm_gem_object")
    drm_id, drm_type = unique(4, "drm_device")
    minor_id, minor_type = unique(4, "drm_minor")
    fop = pointer_member(file_type, "f_op", fops_id)
    private = pointer_member(file_type, "private_data", 0)
    ops = pointer_member(dma_type, "ops", ops_id)
    priv = pointer_member(dma_type, "priv", 0)
    gem_dev = pointer_member(gem_type, "dev", drm_id)
    primary = pointer_member(drm_type, "primary", minor_id)
    minor_dev = pointer_member(minor_type, "dev", drm_id)
    index_id, index_offset = member(minor_type, "index", 4)
    type_id, type_offset = member(minor_type, "type", 4)
    integer(index_id, 4, 1)
    integer(type_id, 4, 1)
    return DmaBufReceiveLayout(receive, fop, private, ops, priv, gem_dev, primary,
        minor_dev, index_offset, type_offset, dma_id, gem_id, drm_id, minor_id,
        dma_type[2], gem_type[2], drm_type[2], minor_type[2])
