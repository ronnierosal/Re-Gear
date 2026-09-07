"""Experimental pure AMD-export receive filter; no load or disconnect authority.

Importer attachments and inherited descriptors remain outside scope. Kernel
symbol addresses embedded in output are ephemeral privileged data: never log,
persist, or publish these bytes. Layout and symbols require live authentication.
Linux v6.16 dma-buf.c, amdgpu_dma_buf.c and drm_prime.c define the private
pointer interpretations, guarded by exact operations-table identity below.
"""
import struct

from .device_filter_btf import DmaBufReceiveLayout, FileReceiveLayout
from .device_receive_program import compile_device_receive


def compile_dma_receive(cgroup_ids, devices, *, layout, dma_buf_fops,
                        amdgpu_dmabuf_ops, allowed_internal_primary_minor):
    if type(layout) is not DmaBufReceiveLayout or type(layout.receive) is not FileReceiveLayout:
        raise ValueError('typed validated BTF layout required')
    r = layout.receive
    if (type(r.pointer_size) is not int or r.pointer_size != 8
            or type(r.mode_size) is not int or r.mode_size != 2
            or type(r.rdev_size) is not int or r.rdev_size != 4):
        raise ValueError('unsupported field widths')
    compile_device_receive(cgroup_ids, devices, file_inode_offset=r.file_inode_offset,
        inode_mode_offset=r.inode_mode_offset, inode_rdev_offset=r.inode_rdev_offset)
    for address in (dma_buf_fops, amdgpu_dmabuf_ops):
        if type(address) is not int or not 0xffff800000000000 <= address < 2**64 or address % 8:
            raise ValueError('canonical aligned x86-64 kernel symbol required')
    if dma_buf_fops == amdgpu_dmabuf_ops:
        raise ValueError('distinct operations symbols required')
    if type(allowed_internal_primary_minor) is not int or not 0 <= allowed_internal_primary_minor < 2**20:
        raise ValueError('exact internal primary minor required')
    for ident in (r.hook_btf_id,r.file_btf_id,r.inode_btf_id,layout.dma_btf_id,
                  layout.gem_btf_id,layout.drm_btf_id,layout.minor_btf_id):
        if type(ident) is not int or not 0 < ident < 2**32:
            raise ValueError('invalid BTF type identity')
    fields = ((r.file_inode_offset,8,r.file_size),(r.inode_mode_offset,2,r.inode_size),
        (r.inode_rdev_offset,4,r.inode_size),(layout.file_fop_offset,8,r.file_size),
        (layout.file_private_offset,8,r.file_size),(layout.dma_ops_offset,8,layout.dma_size),
        (layout.dma_priv_offset,8,layout.dma_size),(layout.gem_dev_offset,8,layout.gem_size),
        (layout.drm_primary_offset,8,layout.drm_size),(layout.minor_dev_offset,8,layout.minor_size),
        (layout.minor_index_offset,4,layout.minor_size),(layout.minor_type_offset,4,layout.minor_size))
    for offset,width,size in fields:
        if (type(offset) is not int or type(size) is not int or not 0 < size <= 2**24
                or offset % width or not 0 <= offset <= min(32767-width,size-width)):
            raise ValueError('field outside bounded structure')
    rows, labels, fixups = [], {}, []
    def emit(op,d=0,s=0,off=0,imm=0):
        rows.append((op,d|(s<<4),off,imm if imm < 2**31 else imm-2**32))
    def jump(op,label,d=0,s=0,imm=0):
        fixups.append((len(rows),label)); emit(op,d,s,imm=imm)
    def constant(reg,value):
        emit(0x18,reg,imm=value & 0xffffffff); emit(0,imm=value>>32)
    def read(base,offset,size,dest=0):
        emit(0xbf,1,10); emit(0x07,1,imm=-8)
        emit(0xb7,2,imm=size); emit(0xbf,3,base); emit(0x07,3,imm=offset)
        emit(0x85,imm=113); jump(0x55,'deny')
        emit({8:0x79,4:0x61,2:0x69}[size],dest,10,off=-8)
    def pointer(base,offset,dest):
        read(base,offset,8,dest); jump(0x15,'deny',d=dest)
    emit(0x61,0,1,off=8); jump(0x55,'exit')
    emit(0x79,6,1); emit(0x85,imm=80)
    for group in sorted(cgroup_ids):
        constant(8,group); jump(0x1d,'scoped',s=8)
    jump(0x05,'allow')
    labels['scoped']=len(rows)
    jump(0x15,'deny',d=6)
    pointer(6,r.file_inode_offset,7)
    read(7,r.inode_mode_offset,2)
    emit(0x54,imm=0xf000); jump(0x56,'nonchar',imm=0x2000)
    read(7,r.inode_rdev_offset,4)
    for major,minor in sorted(devices): jump(0x16,'deny',imm=(major<<20)|minor)
    jump(0x05,'allow')
    labels['nonchar']=len(rows)
    pointer(6,layout.file_fop_offset,7)
    constant(8,dma_buf_fops); jump(0x5d,'allow',d=7,s=8)
    pointer(6,layout.file_private_offset,7)
    pointer(7,layout.dma_ops_offset,9)
    constant(8,amdgpu_dmabuf_ops); jump(0x5d,'deny',d=9,s=8)
    pointer(7,layout.dma_priv_offset,7)
    pointer(7,layout.gem_dev_offset,9)
    pointer(9,layout.drm_primary_offset,7)
    read(7,layout.minor_type_offset,4); jump(0x56,'deny',imm=0)
    pointer(7,layout.minor_dev_offset,8); jump(0x5d,'deny',d=8,s=9)
    read(7,layout.minor_index_offset,4)
    # Equality to a validated 20-bit positive value also rejects negative and
    # out-of-range signed int representations without signed-jump ambiguity.
    jump(0x56,'deny',imm=allowed_internal_primary_minor)
    labels['allow']=len(rows); emit(0xb7,imm=0); jump(0x05,'exit')
    labels['deny']=len(rows); emit(0xb7,imm=-13)
    labels['exit']=len(rows); emit(0x95)
    for index,label in fixups:
        op,regs,_,imm=rows[index]; rows[index]=(op,regs,labels[label]-index-1,imm)
    return b''.join(struct.pack('<BBhi',*row) for row in rows)
