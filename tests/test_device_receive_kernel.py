import ctypes
import errno
import unittest
from unittest.mock import patch
from backend.hdm.delivery.device_receive_kernel import (
    FileReceiveLink, ReceiveLoadAttr, ReceiveLinkInfo, InfoAttr, ReceiveIdentity, ProgramIdAttr, ReceivePinAbsent)


class ReceivePersistenceTests(unittest.TestCase):
    def setUp(self):
        self.calls=[]; self.closed=[]; self.failure=None; self.error=errno.EPERM
        self.expected=ReceiveIdentity(7,8,9,1)
        self.actual=self.expected
        self.program_type=29; self.program_id=8
        def syscall(number, command, pointer, size):
            self.assertEqual(number,321)
            attr=pointer._obj
            self.calls.append(command)
            if command==self.failure:
                ctypes.set_errno(self.error); return -1
            if command in (6,7):
                self.assertEqual(ctypes.string_at(attr.pathname),b'/proc/self/fd/12/'+b'a'*64)
                self.assertEqual(attr.file_flags,0)
                self.assertEqual(attr.bpf_fd,30 if command==6 else 0)
                return 0 if command==6 else 30
            if command==13:
                self.assertEqual(size,16)
                self.assertEqual((attr.prog_id,attr.next_id,attr.open_flags,attr.fd_by_id_token_fd),(8,0,0,0))
                return 40
            if command==15:
                if attr.bpf_fd==40:
                    info=(ctypes.c_uint32*2).from_address(attr.info)
                    info[0],info[1]=self.program_type,self.program_id
                else:
                    info=ReceiveLinkInfo.from_address(attr.info)
                    info.type=2;info.attach_type=27
                    info.id=self.actual.link_id;info.prog_id=self.actual.program_id
                    info.target_btf_id=self.actual.hook_btf_id;info.target_obj_id=self.actual.target_obj_id
                return 0
            raise AssertionError('unexpected command')
        with patch('platform.system',return_value='Linux'),patch('platform.machine',return_value='x86_64'):
            self.owner=FileReceiveLink(syscall=syscall,close_fd=self.closed.append)

    def test_identity_bounds(self):
        for values in ((True,8,9,1),(7,0,9,1),(7,8,2**32,1),(7,8,9,0),(7,8,9,False)):
            with self.assertRaises(ValueError):ReceiveIdentity(*values)

    def test_pin_exclusive_kernel_failure_has_no_retry(self):
        self.owner.link_fd=30
        self.owner.pin(12,'a'*64,self.expected)
        self.assertEqual(self.calls,[15,6])
        self.failure=6;self.error=errno.EEXIST;self.calls=[]
        with self.assertRaises(FileExistsError):self.owner.pin(12,'a'*64,self.expected)
        self.assertEqual(self.calls,[15,6]);self.assertEqual(self.closed,[])

    def test_recover_exact_identity_and_close_only_descriptor(self):
        self.assertEqual(self.owner.recover(12,'a'*64,self.expected),30)
        self.assertEqual(self.owner.link_identity(),self.expected)
        self.owner.close()
        self.assertEqual(self.closed,[30]);self.assertNotIn(34,self.calls)

    def test_only_object_get_enoent_is_typed_pin_absence(self):
        self.failure=7;self.error=errno.ENOENT
        with self.assertRaises(ReceivePinAbsent):self.owner.recover(12,'a'*64,self.expected)
        self.assertEqual(self.closed,[])
        self.failure=15
        with self.assertRaises(FileNotFoundError) as caught:self.owner.recover(12,'a'*64,self.expected)
        self.assertNotIsInstance(caught.exception,ReceivePinAbsent)
        self.assertEqual(self.closed,[30])

    def test_close_enoent_is_not_pin_absence(self):
        self.actual=ReceiveIdentity(6,8,9,1)
        def failed_close(fd):raise FileNotFoundError(errno.ENOENT,'close failed')
        self.owner._close_fd=failed_close
        with self.assertRaises(FileNotFoundError) as caught:self.owner.recover(12,'a'*64,self.expected)
        self.assertNotIsInstance(caught.exception,ReceivePinAbsent)
        self.assertIsNone(self.owner.link_fd)

    def test_mismatch_acquired_fd_closed_no_mutation(self):
        for actual in (ReceiveIdentity(6,8,9,1),ReceiveIdentity(7,6,9,1),ReceiveIdentity(7,8,6,1),ReceiveIdentity(7,8,9,2)):
            self.actual=actual;self.calls=[];self.closed.clear()
            with self.assertRaises(ValueError):self.owner.recover(12,'a'*64,self.expected)
            self.assertEqual(self.calls,[7,15]);self.assertEqual(self.closed,[30])
            self.assertIsNone(self.owner.link_fd)

    def test_preowned_and_invalid_token_no_syscall(self):
        for field in ('link_fd','program_fd'):
            setattr(self.owner,field,99)
            with self.assertRaises(RuntimeError):self.owner.recover(12,'a'*64,self.expected)
            setattr(self.owner,field,None)
        for token in ('a'*63,'A'*64,'../'+ 'a'*64):
            with self.assertRaises(ValueError):self.owner.recover(12,token,self.expected)
        self.assertEqual(self.calls,[]);self.assertEqual(self.closed,[])

    def test_program_probe_uapi_and_closure(self):
        self.assertEqual(ProgramIdAttr.open_flags.offset,8)
        self.assertTrue(self.owner.probe_program_present(8))
        self.assertEqual(self.calls,[13,15]);self.assertEqual(self.closed,[40])

    def test_program_absence_only_enoent_and_mismatch_closes(self):
        self.failure=13;self.error=errno.ENOENT
        self.assertFalse(self.owner.probe_program_present(8));self.assertEqual(self.closed,[])
        self.error=errno.EPERM
        with self.assertRaises(PermissionError):self.owner.probe_program_present(8)
        self.failure=None
        for kind,identifier in ((15,8),(29,9)):
            self.program_type=kind;self.program_id=identifier;self.closed.clear()
            with self.assertRaises(ValueError):self.owner.probe_program_present(8)
            self.assertEqual(self.closed,[40])


class ReceiveKernelTests(unittest.TestCase):
    def setUp(self):
        self.calls, self.closed = [], []
        self.fail = None
        self.bad_hook = False
        self.bad_target_object = False
        self.log = b'fixture verifier log'
        def syscall(number, command, pointer, size):
            self.assertEqual(number, 321)
            attr = pointer._obj
            self.calls.append(command)
            if command == 5:
                self.assertEqual((attr.prog_type,attr.expected_attach_type,attr.attach_btf_id),(29,27,123))
                self.assertEqual((attr.prog_btf_fd,attr.attach_btf_obj_fd),(0,0))
                self.assertEqual(ctypes.string_at(attr.license), b'GPL')
                ctypes.memmove(attr.log_buf,self.log+b'\0',len(self.log)+1)
            if command == self.fail:
                ctypes.set_errno(errno.EPERM)
                return -1
            if command == 5: return 10
            if command == 28:
                self.assertEqual((attr.prog_fd,attr.target_fd,attr.attach_type,attr.flags),(10,0,27,0))
                return 11
            if command == 15:
                if attr.bpf_fd == 10:
                    array = (ctypes.c_uint32*2).from_address(attr.info)
                    array[0],array[1]=29,321
                else:
                    info=ReceiveLinkInfo.from_address(attr.info)
                    info.type,info.id,info.prog_id=2,987,321
                    info.attach_type=27
                    info.target_btf_id=124 if self.bad_hook else 123
                    info.target_obj_id=0 if self.bad_target_object else 1
                return 0
            self.fail('unexpected syscall')
        with patch('platform.system', return_value='Linux'), patch('platform.machine', return_value='x86_64'):
            self.owner=FileReceiveLink(syscall=syscall,close_fd=self.closed.append)
        self.program=b'\x95'+b'\0'*7

    def test_uapi_offsets_and_exact_link_identity(self):
        self.assertEqual(ReceiveLoadAttr.attach_btf_id.offset,108)
        self.assertEqual(ReceiveLoadAttr.attach_btf_obj_fd.offset,112)
        self.assertEqual(ReceiveLinkInfo.attach_type.offset,16)
        self.assertEqual(self.owner.load_attach(self.program,hook_btf_id=123),987)
        self.assertEqual(self.calls,[5,15,28,15])
        self.assertEqual(self.owner.link_identity(),ReceiveIdentity(987,321,123,1))
        self.assertEqual(self.owner.verifier_log,self.log.decode())
        self.owner.close();self.owner.close()
        self.assertEqual(self.closed,[11,10])

    def test_failed_load_or_attach_closes_owned_descriptors(self):
        for failure,closed in ((5,[]),(28,[10])):
            self.fail=failure;self.closed.clear()
            with self.assertRaises(OSError):self.owner.load_attach(self.program,hook_btf_id=123)
            self.assertEqual(self.closed,closed)
            self.assertIsNone(self.owner.program_fd)
            self.assertIsNone(self.owner.link_fd)
            self.assertEqual(self.owner.verifier_log,self.log.decode())

    def test_wrong_hook_closes_link_before_program(self):
        self.bad_hook=True
        with self.assertRaises(ValueError):self.owner.load_attach(self.program,hook_btf_id=123)
        self.assertEqual(self.closed,[11,10])

    def test_zero_target_object_rejected_on_attach(self):
        self.bad_target_object=True
        with self.assertRaises(ValueError):self.owner.load_attach(self.program,hook_btf_id=123)
        self.assertEqual(self.closed,[11,10])

    def test_invalid_input_has_no_syscall(self):
        for program,hook in ((b'',123),(b'x',123),(b'x'*4104,123),(self.program,True),(self.program,0)):
            with self.assertRaises(ValueError):self.owner.load_attach(program,hook_btf_id=hook)
        self.assertEqual(self.calls,[])

    def test_no_implicit_replacement(self):
        self.owner.load_attach(self.program,hook_btf_id=123)
        count=len(self.calls)
        with self.assertRaises(RuntimeError):self.owner.load_attach(self.program,hook_btf_id=123)
        self.assertEqual(len(self.calls),count)
        self.owner.close()

    def test_verify_load_only_queries_identity_then_closes(self):
        self.assertEqual(self.owner.verify_load(self.program, hook_btf_id=123), 321)
        self.assertEqual(self.calls, [5, 15])
        self.assertEqual(self.closed, [10])
        self.assertIsNone(self.owner.program_fd)
        self.assertIsNone(self.owner.link_fd)
        self.assertEqual(self.owner.verifier_log, self.log.decode())

    def test_verify_load_failure_never_attaches_and_closes_only_owned(self):
        for command, closed in ((5, []), (15, [10])):
            self.calls.clear(); self.closed.clear(); self.fail = command
            with self.assertRaises(OSError):
                self.owner.verify_load(self.program, hook_btf_id=123)
            self.assertNotIn(28, self.calls)
            self.assertEqual(self.closed, closed)
            self.assertIsNone(self.owner.program_fd)
            self.assertEqual(self.owner.verifier_log, self.log.decode())

    def test_verify_load_rejects_preowned_without_closing_it(self):
        for field in ('program_fd', 'link_fd'):
            setattr(self.owner, field, 99)
            with self.assertRaises(RuntimeError):
                self.owner.verify_load(self.program, hook_btf_id=123)
            self.assertEqual(getattr(self.owner, field), 99)
            setattr(self.owner, field, None)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.closed, [])

    def test_verify_load_identity_refusal_closes_program(self):
        with patch.object(self.owner, 'program_id', side_effect=ValueError('wrong identity')):
            with self.assertRaises(ValueError):
                self.owner.verify_load(self.program, hook_btf_id=123)
        self.assertEqual(self.calls, [5])
        self.assertEqual(self.closed, [10])

    def test_program_query_failure_closes_program(self):
        self.fail=15
        with self.assertRaises(OSError):self.owner.load_attach(self.program,hook_btf_id=123)
        self.assertEqual(self.closed,[10])
