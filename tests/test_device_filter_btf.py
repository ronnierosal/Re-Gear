import struct
import unittest

from backend.hdm.delivery.device_filter_btf import parse_file_receive_btf, parse_dma_buf_receive_btf


def fixture(*, mode_offset=16, rdev_offset=32, file_offset=64, bitfield=False,
            duplicate=False, two_args=False, mode_size=2, bad_ref=False, modifier=False, type_tag=False, dma=False, dma_error=None):
    strings = bytearray(b"\0")
    def name(value):
        offset = len(strings)
        strings.extend(value.encode() + b"\0")
        return offset
    def t(label, kind, value, words=(), vlen=0, flag=False):
        return struct.pack("<III", name(label), (kind << 24) | vlen | (int(flag) << 31), value) + struct.pack("<" + "I" * len(words), *words)
    types = [t("int", 1, 4, (0x01000020,)), t("short unsigned int", 1, mode_size, (mode_size * 8,)),
             t("unsigned int", 1, 4, (32,)),
             t("inode", 4, 64, (name("i_mode"), 2, mode_offset,
                                name("i_rdev"), 3, rdev_offset), vlen=2, flag=bitfield),
             t("", 2, 4), t("file", 4, 64 if dma else 32,
                 (name("f_inode"), 5, file_offset) + ((name("f_op"), 11, 128, name("private_data"), 12, 192) if dma else ()), vlen=3 if dma else 1),
             t("", 2, 6),
             t("", 13, 1, (name("file"), 999 if bad_ref else 10 if modifier or type_tag else 7)
               + ((name("ret"), 1) if two_args else ()), vlen=2 if two_args else 1),
             t("bpf_lsm_file_receive", 12, 8, vlen=1)]
    if dma:
        types.extend((t("file_operations", 4, 8), t("", 2, 10), t("", 2, 0),
            t("dma_buf_ops", 4, 8), t("", 2, 13),
            t("dma_buf", 4, 32, (name("ops"), 14, 0, name("priv"), 12, 64), vlen=2),
            t("drm_device", 4, 32, (name("primary"), 19, 64), vlen=1),
            t("", 2, 16),
            t("drm_minor", 4, 32, (name("index"), 3 if dma_error == "unsigned" else 1,
              (1 << 24) if dma_error == "bitfield" else 0,
              name("type"), 1, 32, name("dev"), 17, 128), vlen=3, flag=dma_error == "bitfield"),
            t("", 2, 18),
            t("drm_gem_object", 4, 32, (name("dev"), 11 if dma_error == "target" else 21 if dma_error == "cycle" else 17, 64), vlen=1)))
        if dma_error == "cycle":
            types.append(t("cycle", 8, 21))
        if dma_error == "duplicate":
            types.append(t("drm_device", 4, 32))
    if modifier:
        types.append(t("file_ptr", 8, 7))
    if type_tag:
        types.append(t("__user", 18, 7, flag=True))
    if duplicate:
        types.append(t("bpf_lsm_file_receive", 12, 8, vlen=1))
    body = b"".join(types)
    return struct.pack("<HBBIIIII", 0xeb9f, 1, 0, 24, 0, len(body), len(body), len(strings)) + body + strings


class FileReceiveBtfTests(unittest.TestCase):
    def test_dma_export_chain_layout_and_primary_type(self):
        value = parse_dma_buf_receive_btf(fixture(dma=True), pointer_size=8)
        self.assertEqual((value.file_fop_offset, value.file_private_offset), (16, 24))
        self.assertEqual((value.dma_ops_offset, value.dma_priv_offset), (0, 8))
        self.assertEqual((value.gem_dev_offset, value.drm_primary_offset), (8, 8))
        self.assertEqual((value.minor_dev_offset, value.minor_index_offset, value.minor_type_offset), (16, 0, 4))
        self.assertEqual((value.dma_btf_id, value.gem_btf_id, value.drm_btf_id, value.minor_btf_id), (15, 20, 16, 18))

    def test_dma_wrong_types_unsigned_index_cycles_and_duplicates_fail(self):
        for error in ("target", "unsigned", "cycle", "duplicate", "bitfield"):
            with self.subTest(error=error), self.assertRaises(ValueError):
                parse_dma_buf_receive_btf(fixture(dma=True, dma_error=error), pointer_size=8)
        with self.assertRaisesRegex(ValueError, "file_operations"):
            parse_dma_buf_receive_btf(fixture(), pointer_size=8)

    def test_layout_comes_from_records_not_fixed_offsets(self):
        result = parse_file_receive_btf(fixture(), pointer_size=8)
        self.assertEqual((result.hook_btf_id, result.file_btf_id, result.inode_btf_id), (9, 6, 4))
        self.assertEqual((result.file_size, result.inode_size), (32, 64))
        self.assertEqual((result.file_inode_offset, result.inode_mode_offset, result.inode_rdev_offset), (8, 2, 4))
        changed = parse_file_receive_btf(fixture(file_offset=128, mode_offset=80, rdev_offset=128), pointer_size=8)
        self.assertEqual((changed.file_inode_offset, changed.inode_mode_offset, changed.inode_rdev_offset), (16, 10, 16))

    def test_kind_flag_type_tag_is_valid_linux_btf(self):
        self.assertEqual(parse_file_receive_btf(fixture(type_tag=True), pointer_size=8).hook_btf_id, 9)

    def test_modifier_resolution_and_explicit_pointer_abi(self):
        self.assertEqual(parse_file_receive_btf(fixture(modifier=True), pointer_size=8).hook_btf_id, 9)
        for width in (4, True, None):
            with self.assertRaises(ValueError):
                parse_file_receive_btf(fixture(), pointer_size=width)

    def test_unsupported_members_references_and_prototype_rejected(self):
        for options in ({"mode_offset": 1}, {"file_offset": 1024}, {"rdev_offset": 17},
                        {"mode_offset": (1 << 24) | 16, "bitfield": True},
                        {"mode_size": 4}, {"duplicate": True}, {"two_args": True}, {"bad_ref": True}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                parse_file_receive_btf(fixture(**options), pointer_size=8)

    def test_header_ranges_truncation_and_string_offsets(self):
        original = fixture()
        samples = [b"", original[:-1], original + b"x", b"\xeb\x9f" + original[2:], original[:100]]
        for offset, value in ((4, 25), (8, 1), (12, 0xffffffff), (16, 0), (20, 0xffffffff), (24, 0xffffffff)):
            raw = bytearray(original)
            struct.pack_into("<I", raw, offset, value)
            samples.append(bytes(raw))
        raw = bytearray(original)
        raw[2] = 2
        samples.append(bytes(raw))
        for raw in samples:
            with self.subTest(length=len(raw)), self.assertRaises(ValueError):
                parse_file_receive_btf(raw, pointer_size=8)

    def test_missing_hook_and_duplicate_selected_member(self):
        raw = fixture().replace(b"bpf_lsm_file_receive", b"bpf_lsm_file_missing")
        with self.assertRaises(ValueError):
            parse_file_receive_btf(raw, pointer_size=8)
        raw = fixture().replace(b"i_rdev", b"i_mode")
        with self.assertRaises(ValueError):
            parse_file_receive_btf(raw, pointer_size=8)


if __name__ == "__main__":
    unittest.main()
