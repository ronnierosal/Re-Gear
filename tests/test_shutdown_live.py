import contextlib
import io
import json
import unittest
from unittest.mock import Mock, patch

from scripts import capture_shutdown_live as live
from scripts import capture_shutdown_evidence as evidence


class LiveShutdownTests(unittest.TestCase):
    def test_fixed_bounded_payload_has_no_device_mutation(self):
        for seconds in (29, 301, True, "180"):
            with self.assertRaises(ValueError):
                live.live_payload(seconds)
        payload = live.live_payload(30)
        compile(payload, "live-payload", "exec")
        for forbidden in ("systemctl", "sudo", "write_text", "write_bytes", "os.kill", "killpg"):
            self.assertNotIn(forbidden, payload.replace("# No sudo/root fallback", ""))

    def test_live_reader_redacts_messages_and_closes_only_owned_reader(self):
        namespace = {}
        exec(evidence.remote_payload("current", "shutdown").rsplit("\nprint(", 1)[0], namespace)
        namespace["LIVE_SECONDS"] = 30
        process = Mock()
        process.poll.return_value = None
        selector = Mock()
        selector.get_map.return_value = {1: 1}
        selector.select.return_value = [(Mock(fileobj=process.stdout, data="stdout"), 1)]
        context = Mock()
        context.__enter__ = Mock(return_value=selector)
        context.__exit__ = Mock(return_value=False)
        row = json.dumps({"MESSAGE": "amdgpu_device_fini secret-host /private/path",
                          "_TRANSPORT": "kernel"}).encode() + b"\n"
        output = io.StringIO()
        with (patch.object(namespace["subprocess"], "Popen", return_value=process) as popen,
              patch.object(namespace["selectors"], "DefaultSelector", return_value=context),
              patch.object(namespace["os"], "read", return_value=row),
              patch.object(namespace["time"], "monotonic", side_effect=[0, 1, 1, 31]),
              contextlib.redirect_stdout(output)):
            exec(live.LIVE_BODY, namespace)
        self.assertIn("--follow", popen.call_args.args[0])
        self.assertIn("--lines=0", popen.call_args.args[0])
        self.assertNotIn("secret-host", output.getvalue())
        self.assertNotIn("/private/path", output.getvalue())
        reports = [evidence.validate_report(line, "current", "shutdown")
                   for line in output.getvalue().splitlines()]
        self.assertEqual(reports[-1]["symptoms"]["amdgpu_shutdown_stack"], 1)
        self.assertEqual(reports[-1]["physical_poweroff"], "unknown")
        process.kill.assert_called_once_with()
        process.stdout.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
