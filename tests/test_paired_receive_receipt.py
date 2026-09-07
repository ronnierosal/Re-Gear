from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from scripts.paired_receive_receipt import ReceiptBinding, PairedReceiptDirectory, decode_pair
from hdm.delivery.cgroup_retention_map import MapIdentity
from hdm.delivery.device_receive_kernel import ReceiveIdentity


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.binding=ReceiptBinding('a'*64,'regear-paired-receive-fixture-'+'b'*32,1,2)
        self.map=dict(schema=1,stage='map',binding=asdict(self.binding),token='c'*64,map_id=3)
        self.receive=dict(schema=1,stage='receive',binding=asdict(self.binding),token='d'*64,
            map_token='c'*64,map_id=3,identity=asdict(ReceiveIdentity(4,5,6,7)))

    def raw(self,value):return json.dumps(value).encode()

    def test_pair_and_missing_receive_are_observations(self):
        result=decode_pair(self.raw(self.map),self.raw(self.receive),self.binding)
        self.assertEqual(result.binding,self.binding)
        self.assertEqual(result.map_identity,MapIdentity(3))
        self.assertEqual(result.receive_identity,ReceiveIdentity(4,5,6,7))
        self.assertIsNone(decode_pair(self.raw(self.map),None,self.binding).receive_identity)

    def test_duplicate_extra_boolean_and_mismatched_binding(self):
        for raw in (b'{"schema":1,"schema":1}',b'x'*2049,b'\xff',b'{"schema":NaN}',
                    self.raw(dict(self.map,extra=0)),self.raw(dict(self.map,schema=True)),
                    self.raw(dict(self.map,map_id=True))):
            with self.assertRaises((ValueError,UnicodeError)):decode_pair(raw,None,self.binding)
        with self.assertRaises(ValueError):decode_pair(self.raw(self.map),None,replace(self.binding,cgroup_inode=99))

    def test_pair_binding_tokens_and_identity_rejected(self):
        for field,value in (('map_id',9),('map_token','e'*64),('token','c'*64),('identity',{'link_id':4})):
            with self.assertRaises(ValueError):
                decode_pair(self.raw(self.map),self.raw(dict(self.receive,**{field:value})),self.binding)

    @unittest.skipUnless(sys.platform=='linux','Linux trusted directory fixture')
    def test_real_immutable_files_reopen_and_unsafe_objects(self):
        with tempfile.TemporaryDirectory() as path:
            os.chmod(path,0o700)
            directory=os.open(path,os.O_RDONLY|os.O_DIRECTORY)
            try:
                with PairedReceiptDirectory(path,self.binding,trusted_directory_fd=directory,owner_uid=os.geteuid()) as receipt:
                    receipt.write_map('c'*64,MapIdentity(3))
                    with self.assertRaises(FileExistsError):receipt.write_map('c'*64,MapIdentity(3))
                    receipt.write_receive('d'*64,ReceiveIdentity(4,5,6,7))
                with PairedReceiptDirectory(path,self.binding,trusted_directory_fd=directory,owner_uid=os.geteuid()) as receipt:
                    self.assertEqual(receipt.read().receive_identity,ReceiveIdentity(4,5,6,7))
                    with self.assertRaises(ValueError):receipt.read(replace(self.binding,boot_hash='e'*64))
                    os.chmod(Path(path)/'map.json',0o644)
                    with self.assertRaises(ValueError):receipt.read()
                    os.unlink(Path(path)/'map.json')
                    os.symlink('receive.json',Path(path)/'map.json')
                    with self.assertRaises(OSError):receipt.read()
            finally:os.close(directory)

    @unittest.skipUnless(sys.platform=='linux','Linux trusted directory fixture')
    def test_failed_write_retains_unreadable_evidence(self):
        with tempfile.TemporaryDirectory() as path:
            os.chmod(path,0o700)
            directory=os.open(path,os.O_RDONLY|os.O_DIRECTORY)
            try:
                with PairedReceiptDirectory(path,self.binding,trusted_directory_fd=directory,owner_uid=os.geteuid()) as receipt:
                    with patch('os.write',return_value=0),self.assertRaises(OSError):receipt.write_map('c'*64,MapIdentity(3))
                    self.assertTrue((Path(path)/'map.json').exists())
                    with self.assertRaises(ValueError):receipt.read()
            finally:os.close(directory)


if __name__=='__main__':unittest.main()
