from dataclasses import replace
import struct
import unittest

from backend.hdm.delivery.device_filter_btf import FileReceiveLayout, DmaBufReceiveLayout
from backend.hdm.delivery.dma_receive_program import compile_dma_receive

FOPS=0xffff800000001000
OPS=0xffff800000002000
LAYOUT=DmaBufReceiveLayout(FileReceiveLayout(1,2,3,128,128,24,30,40,8),
    48,56,8,16,24,32,8,16,20,4,5,6,7,64,64,64,64)


def evaluate(code, *, prior=0,group=9,mode=0x8180,dev=0x100003,
             index=4,kind=0,fops=FOPS,ops=OPS,back=5000,fail=0,null_at=None):
    memory={}
    def put(addr,value,width):
        for i,b in enumerate((value & ((1<<(width*8))-1)).to_bytes(width,'little')): memory[addr+i]=b
    def get(addr,width): return int.from_bytes(bytes(memory[addr+i] for i in range(width)),'little')
    for addr,value,width in ((1000,2000,8),(1008,prior,8),(2024,3000,8),
        (3030,mode,2),(3040,dev,4),(2048,fops,8),(2056,4000,8),
        (4008,ops,8),(4016,4500,8),(4524,5000,8),(5032,6000,8),
        (6008,back,8),(6016,index,4),(6020,kind,4)):
        put(addr,0 if addr==null_at else value,width)
    regs=[0]*11; regs[1]=1000; regs[10]=10000
    rows=list(struct.iter_unpack('<BBhi',code)); pc=0; reads=0
    for _ in range(1000):
        op,packed,off,imm=rows[pc]; pc+=1; d=packed&15; s=packed>>4
        if op in (0x61,0x69,0x79): regs[d]=get(regs[s]+off,{0x61:4,0x69:2,0x79:8}[op])
        elif op==0xbf: regs[d]=regs[s]
        elif op==0xb7: regs[d]=imm & (2**64-1)
        elif op==0x07: regs[d]=(regs[d]+imm)&(2**64-1)
        elif op==0x54: regs[d]&=imm&0xffffffff
        elif op==0x18:
            assert rows[pc][:3]==(0,0,0)
            regs[d]=(imm&0xffffffff)|((rows[pc][3]&0xffffffff)<<32); pc+=1
        elif op==0x85:
            if imm==80: result=group
            elif imm==113:
                reads+=1; result=-14 if reads==fail else 0
                if not result: put(regs[1],get(regs[3],regs[2]),regs[2])
            else: raise AssertionError('helper')
            regs[0]=result&(2**64-1); regs[1:6]=[None]*5
        elif op==0x05: pc+=off
        elif op in (0x15,0x55,0x16,0x56,0x1d,0x5d):
            a=regs[d]; b=regs[s] if op in (0x1d,0x5d) else imm&(2**64-1)
            if op in (0x16,0x56): a&=0xffffffff; b&=0xffffffff
            if (a!=b if op in (0x55,0x56,0x5d) else a==b): pc+=off
        elif op==0x95:
            result=regs[0]&0xffffffff
            return (result if result<2**31 else result-2**32),reads
        else: raise AssertionError(hex(op))
    raise AssertionError('unterminated')


class DmaReceiveTests(unittest.TestCase):
    def build(self,**changes):
        args=dict(layout=LAYOUT,dma_buf_fops=FOPS,amdgpu_dmabuf_ops=OPS,
                  allowed_internal_primary_minor=4)
        args.update(changes)
        return compile_dma_receive((9,2**64-1),((1,3),(4095,1048575)),**args)

    def test_internal_export_and_non_dma_allow(self):
        self.assertEqual(evaluate(self.build())[0],0)
        self.assertEqual(evaluate(self.build(),fops=FOPS+8)[0],0)

    def test_external_unknown_exporter_and_bad_relationship_deny(self):
        for changes in (dict(index=5),dict(index=-1),dict(index=2**20),
                        dict(kind=2),dict(back=5008),dict(ops=OPS+8)):
            self.assertEqual(evaluate(self.build(),**changes)[0],-13)

    def test_prior_and_exact_scope(self):
        self.assertEqual(evaluate(self.build(),prior=-1),(-1,0))
        self.assertEqual(evaluate(self.build(),group=10),(0,0))
        self.assertEqual(evaluate(self.build(),group=2**64-1,index=5)[0],-13)

    def test_every_read_failure_and_null_pointer_denies(self):
        count=evaluate(self.build())[1]
        self.assertEqual(count,11)
        for failure in range(1,count+1):
            self.assertEqual(evaluate(self.build(),fail=failure)[0],-13)
        for address in (1000,2024,2048,2056,4008,4016,4524,5032,6008):
            self.assertEqual(evaluate(self.build(),null_at=address)[0],-13)

    def test_character_policy_still_exact(self):
        for dev in (0x100003,0xffffffff):
            self.assertEqual(evaluate(self.build(),mode=0x2180,dev=dev)[0],-13)
        self.assertEqual(evaluate(self.build(),mode=0x2180,dev=0x100004)[0],0)

    def test_layout_symbols_and_minor_validation(self):
        for key in ('dma_buf_fops','amdgpu_dmabuf_ops'):
            for value in (True,0,-1,2**64,FOPS+1,0x800000000000):
                with self.assertRaises(ValueError): self.build(**{key:value})
        for value in (-1,2**20,True):
            with self.assertRaises(ValueError): self.build(allowed_internal_primary_minor=value)
        for layout in (None,replace(LAYOUT,minor_index_offset=63),
                       replace(LAYOUT,gem_dev_offset=True),replace(LAYOUT,gem_dev_offset=1),replace(LAYOUT,dma_btf_id=0),
                       replace(LAYOUT,receive=replace(LAYOUT.receive,pointer_size=4))):
            with self.assertRaises(ValueError): self.build(layout=layout)
        self.assertEqual(evaluate(self.build(allowed_internal_primary_minor=1048575),index=1048575)[0],0)


if __name__=='__main__': unittest.main()
