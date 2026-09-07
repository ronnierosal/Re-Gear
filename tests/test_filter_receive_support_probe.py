import gzip
import struct
import unittest
from unittest.mock import patch

from scripts.probe_filter_receive_support import (
    CONFIG_LIMIT, OPTIONS, parse_config, parse_lsm, parse_btf_header, run_probe,
)


CONFIG = "\n".join(option + "=y" for option in OPTIONS).encode()
HEADER = struct.pack("<HBBIIIII", 0xeb9f, 1, 0, 24, 0, 64, 64, 32)


class ReceiveSupportProbeTests(unittest.TestCase):
    def run_fixture(self, values=None, *, release="6.16-test"):
        values = values if values is not None else {
            "/proc/config.gz": gzip.compress(CONFIG),
            "/sys/kernel/security/lsm": b"capability,landlock,bpf\n",
        }
        self.paths = []
        def reader(path, limit):
            self.paths.append(path)
            value = values.get(path, PermissionError("unavailable"))
            if isinstance(value, Exception):
                raise value
            return value
        with patch("scripts.probe_filter_receive_support.sys.platform", "linux"):
            return run_probe(reader=reader, btf_reader=lambda path: HEADER, release=release)

    def test_available_prerequisites_never_claim_hook_or_attribution(self):
        report = self.run_fixture()
        self.assertEqual(report["preflight"], "prerequisites_observed")
        self.assertFalse(report["kernel_hook_fixture_verified"])
        self.assertFalse(report["disconnect_clearance"])
        self.assertEqual(report["dma_buf_attribution"], "unresolved")

    def test_denied_or_missing_reads_remain_unknown(self):
        report = self.run_fixture({})
        self.assertEqual(report["preflight"], "unknown")
        self.assertEqual(report["active_bpf_lsm"], "unknown")

    def test_boot_fallback_is_validated_and_disabled_is_explicit(self):
        report = self.run_fixture({"/boot/config-6.16-test": CONFIG.replace(
            b"CONFIG_BPF_LSM=y", b"# CONFIG_BPF_LSM is not set")})
        self.assertEqual(report["config_source"], "boot")
        self.assertEqual(report["preflight"], "prerequisite_unavailable")
        self.run_fixture({}, release="../../etc/passwd")
        self.assertFalse(any(path.startswith("/boot/") for path in self.paths))

    def test_inactive_lsm_is_explicit_without_guessing_config(self):
        report = self.run_fixture({"/sys/kernel/security/lsm": b"capability,landlock"})
        self.assertEqual(report["preflight"], "prerequisite_unavailable")

    def test_config_missing_options_duplicate_and_expansion_bounded(self):
        self.assertEqual(parse_config(b"CONFIG_BPF_LSM=y")["CONFIG_DEBUG_INFO_BTF"], "unknown")
        for raw in (CONFIG + b"\nCONFIG_BPF_LSM=n", gzip.compress(b"x" * (CONFIG_LIMIT + 1))):
            with self.assertRaises(ValueError):
                parse_config(raw, compressed=raw.startswith(b"\x1f\x8b"))

    def test_malformed_config_falls_back_without_claim(self):
        report = self.run_fixture({"/proc/config.gz": b"not gzip"})
        self.assertEqual(report["config_source"], "unavailable")

    def test_lsm_requires_exact_names(self):
        self.assertEqual(parse_lsm(b"notbpf,selinux"), "inactive")
        for raw in (b"", b"bpf,bpf", b"bpf\x00"):
            with self.assertRaises(ValueError):
                parse_lsm(raw)

    def test_btf_header_endianness_and_invalid_fields(self):
        self.assertEqual(parse_btf_header(HEADER), "header_present")
        self.assertEqual(parse_btf_header(struct.pack(">HBBIIIII", 0xeb9f, 1, 0, 24, 0, 64, 64, 32)), "header_present")
        for raw in (b"", HEADER[:23], bytes(24), HEADER[:2] + b"\x02" + HEADER[3:]):
            with self.assertRaises(ValueError):
                parse_btf_header(raw)

    def test_unreadable_btf_cannot_complete_preflight(self):
        def reader(path, limit):
            return gzip.compress(CONFIG) if path == "/proc/config.gz" else b"bpf"
        with patch("scripts.probe_filter_receive_support.sys.platform", "linux"):
            result = run_probe(reader=reader, btf_reader=lambda path: b"", release="6.16-test")
        self.assertEqual(result["btf"], "unknown")
        self.assertEqual(result["preflight"], "unknown")
