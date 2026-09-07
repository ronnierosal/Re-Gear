import unittest
from backend.hdm.adapters.steamos.device_receive_symbols import parse_receive_symbols


class ReceiveSymbolTests(unittest.TestCase):
    def setUp(self):
        self.raw = (b'ffffffff82001000 d dma_buf_fops\n'
                    b'ffffffffc0012000 r amdgpu_dmabuf_ops [amdgpu]\n')

    def test_exact_symbols_and_private_representation(self):
        result=parse_receive_symbols(self.raw)
        self.assertEqual(result.dma_buf_fops,0xffffffff82001000)
        self.assertEqual(result.amdgpu_dmabuf_ops,0xffffffffc0012000)
        self.assertNotIn(str(result.dma_buf_fops),repr(result))
        self.assertNotIn('ffffffff',repr(result))

    def test_hidden_duplicate_wrong_module_and_wrong_kind_fail(self):
        for raw in (self.raw.replace(b'ffffffff82001000',b'0000000000000000'),
                    self.raw+self.raw, self.raw.replace(b'[amdgpu]',b'[other]'),
                    self.raw.replace(b' d ',b' t '), self.raw.splitlines()[0],
                    self.raw.replace(b'ffffffffc0012000',b'ffffffff82001000')):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):parse_receive_symbols(raw)

    def test_noncanonical_unaligned_extra_fields_and_invalid_address_fail(self):
        for value in (b'00007fff82001000',b'ffffffff82001001',b'zzzzzzzz82001000'):
            with self.assertRaises(ValueError):parse_receive_symbols(self.raw.replace(b'ffffffff82001000',value))
        with self.assertRaises(ValueError):parse_receive_symbols(self.raw.replace(b'dma_buf_fops',b'dma_buf_fops extra'))
        with self.assertRaises(ValueError):parse_receive_symbols(b'')

    def test_candidate_substrings_in_other_fields_do_not_become_symbols(self):
        noise=(b'xx dma_buf_fops unrelated\n'
               b'ffffffff82001000 d prefix_dma_buf_fops_suffix\n'
               b'\xff d unrelated amdgpu_dmabuf_ops dma_buf_fops\n')
        self.assertEqual(parse_receive_symbols(noise+self.raw),parse_receive_symbols(self.raw))

    def test_repeated_candidates_one_row_still_validate_whole_row(self):
        with self.assertRaises(ValueError):
            parse_receive_symbols(self.raw.replace(b'dma_buf_fops\n',b'dma_buf_fops dma_buf_fops\n'))
        noise=b'address kind irrelevant '+b'dma_buf_fops '*200+b'\n'
        self.assertEqual(parse_receive_symbols(noise+self.raw),parse_receive_symbols(self.raw))

    def test_late_duplicate_and_irrelevant_bounds_checked(self):
        noise=b'ffffffff82001000 t irrelevant\n'*1000
        with self.assertRaises(ValueError):parse_receive_symbols(self.raw+noise+self.raw.splitlines(keepends=True)[0])
        with self.assertRaises(ValueError):parse_receive_symbols(self.raw+b'x'*4096+b'\n')
        with self.assertRaises(ValueError):parse_receive_symbols(self.raw+b'\n'*999999)

    def test_whitespace_final_unterminated_and_nonascii_candidate_semantics(self):
        self.assertEqual(parse_receive_symbols(self.raw.rstrip(b'\n').replace(b' d ',b'\vd\t')),
                         parse_receive_symbols(self.raw))
        with self.assertRaises(ValueError):parse_receive_symbols(self.raw.replace(b' d ',b' \xff '))
