from dataclasses import FrozenInstanceError
import hashlib
import unittest
from unittest.mock import patch
from backend.hdm.delivery import device_receive_layout_cache as cache
from backend.hdm.delivery.device_filter_btf import parse_dma_buf_receive_btf
from tests.test_device_filter_btf import fixture


class DmaLayoutCacheTests(unittest.TestCase):
    def setUp(self):self.cache=cache.DmaReceiveLayoutCache();self.raw=fixture(dma=True)

    def test_identical_fresh_bytes_reuse_frozen_result(self):
        with patch.object(cache,'parse_dma_buf_receive_btf',wraps=parse_dma_buf_receive_btf) as parser:
            first=self.cache.parse(self.raw,pointer_size=8)
            second=self.cache.parse(bytes(bytearray(self.raw)),pointer_size=8)
            self.assertIs(first,second)
            parser.assert_called_once()
            self.assertEqual(first.btf_sha256,hashlib.sha256(self.raw).hexdigest())
            with self.assertRaises(FrozenInstanceError):first.pointer_size=4
        self.assertEqual(set(vars(first)),{'btf_sha256','pointer_size','layout'})

    def test_changed_content_replaces_only_entry(self):
        other=fixture(dma=True,mode_offset=32)
        with patch.object(cache,'parse_dma_buf_receive_btf',wraps=parse_dma_buf_receive_btf) as parser:
            first=self.cache.parse(self.raw,pointer_size=8)
            second=self.cache.parse(other,pointer_size=8)
            self.assertNotEqual(first.btf_sha256,second.btf_sha256)
            self.assertEqual(second.layout.receive.inode_mode_offset,4)
            self.cache.parse(self.raw,pointer_size=8)
            self.assertEqual(parser.call_count,3)

    def test_changed_or_boolean_abi_never_hits_previous_entry(self):
        self.cache.parse(self.raw,pointer_size=8)
        for abi in (4,True,None,8.0):
            with self.assertRaises(ValueError):self.cache.parse(self.raw,pointer_size=abi)

    def test_malformed_data_never_admitted(self):
        with patch.object(cache,'parse_dma_buf_receive_btf',wraps=parse_dma_buf_receive_btf) as parser:
            for _ in range(2):
                with self.assertRaises(ValueError):self.cache.parse(b'bad',pointer_size=8)
            self.assertEqual(parser.call_count,2)
        self.assertIsNone(self.cache._entry)

    def test_bounded_exact_bytes_before_parser(self):
        with patch.object(cache,'MAX_BTF_BYTES',16),patch.object(cache,'parse_dma_buf_receive_btf') as parser:
            for raw in (b'',bytearray(b'foo'),'foo',b'x'*17):
                with self.assertRaises(ValueError):self.cache.parse(raw,pointer_size=8)
            parser.assert_not_called()

    def test_no_shared_global_cache(self):
        with patch.object(cache,'parse_dma_buf_receive_btf',wraps=parse_dma_buf_receive_btf) as parser:
            self.cache.parse(self.raw,pointer_size=8)
            cache.DmaReceiveLayoutCache().parse(self.raw,pointer_size=8)
            self.assertEqual(parser.call_count,2)


if __name__=='__main__':unittest.main()
