import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from scripts import probe_dma_receive_verifier as probe


class DmaVerifierProbeTests(unittest.TestCase):
    def setUp(self):
        for name, value in (("system", "Linux"), ("machine", "x86_64")):
            context = patch.object(probe.platform, name, return_value=value)
            context.start()
            self.addCleanup(context.stop)
        self.owner = Mock()
        self.owner.verifier_log = "PRIVATE kernel pointer"
        self.layout = SimpleNamespace(receive=SimpleNamespace(hook_btf_id=123))
        self.arguments = dict(read_btf=Mock(return_value=b"btf"),
            read_symbols=Mock(return_value=probe.ReceiveSymbols(0xffff800000001000, 0xffff800000002000)),
            parse_layout=Mock(return_value=self.layout), compile_program=Mock(return_value=b"PRIVATE BYTECODE"),
            owner_factory=Mock(return_value=self.owner), effective_uid=lambda: 0)

    def test_load_only_synthetic_inputs_and_cleanup(self):
        report = probe.capture(**self.arguments)
        self.assertTrue(report["verifier_accepted"])
        self.assertFalse(report["enforcement_verified"])
        self.assertFalse(report["disconnect_clearance"])
        self.assertTrue(report["synthetic_target_inputs"])
        args = self.arguments["compile_program"].call_args
        self.assertEqual(args.args, ((1,), ((1, 3),)))
        self.assertEqual(args.kwargs["allowed_internal_primary_minor"], 0)
        self.owner.verify_load.assert_called_once_with(b"PRIVATE BYTECODE", hook_btf_id=123)
        self.assertEqual([call[0] for call in self.owner.method_calls], ["verify_load", "close"])
        self.assertNotIn("PRIVATE", json.dumps(report))

    def test_invalid_prerequisites_never_load(self):
        for dependency, phase in (("read_btf", "layout"), ("read_symbols", "symbols"), ("compile_program", "compile")):
            previous = self.arguments[dependency]
            self.arguments[dependency] = Mock(side_effect=ValueError("SECRET /private/path"))
            result = probe.capture(**self.arguments)
            self.assertEqual(result["code"], phase + "_unavailable")
            self.assertNotIn("SECRET", json.dumps(result))
            self.arguments[dependency] = previous
        self.arguments["owner_factory"].assert_not_called()

    def test_no_root_or_platform_means_no_prerequisite_reads(self):
        result = probe.capture(**dict(self.arguments, effective_uid=lambda: 1000))
        self.assertEqual(result["code"], "root_required")
        with patch.object(probe.platform, "machine", return_value="aarch64"):
            result = probe.capture(**self.arguments)
        self.assertEqual(result["code"], "unsupported_platform")
        self.arguments["read_btf"].assert_not_called()
        self.arguments["owner_factory"].assert_not_called()

    def test_verifier_failure_is_sanitized_and_closed(self):
        self.owner.verify_load.side_effect = OSError("SECRET verifier address")
        report = probe.capture(**self.arguments)
        self.assertEqual(report["code"], "verifier_unavailable")
        self.assertFalse(report["verifier_accepted"])
        self.owner.close.assert_called_once()
        self.assertNotIn("SECRET", json.dumps(report))

    def test_cleanup_failure_cannot_pass(self):
        self.owner.close.side_effect = OSError("SECRET close")
        result = probe.capture(**self.arguments)
        self.assertEqual(result["code"], "cleanup_unconfirmed")
        self.assertFalse(result["verifier_accepted"])


if __name__ == "__main__":
    unittest.main()
