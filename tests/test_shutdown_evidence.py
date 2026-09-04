from __future__ import annotations

import copy
import json
import subprocess
import unittest
from unittest.mock import Mock, patch

from scripts import capture_shutdown_evidence as capture


def journal(message, **fields):
    return json.dumps({"MESSAGE": message, **fields}).encode() + b"\n"


class ShutdownEvidenceTests(unittest.TestCase):
    def test_fixed_previous_boot_tail_command(self):
        self.assertEqual(capture.JOURNAL_ARGV, (
            "/usr/bin/journalctl", "--boot=-1", "--lines=2000", "--output=json",
            "--output-fields=MESSAGE,__MONOTONIC_TIMESTAMP,_TRANSPORT,_COMM,_SYSTEMD_UNIT",
            "--no-pager", "--quiet",
        ))
        self.assertEqual(capture.JOURNAL_TIMEOUT_SECONDS, 10)

    def test_payload_is_self_contained_and_has_no_local_client_or_mutators(self):
        payload = capture.remote_payload()
        compile(payload, "fixed-payload", "exec")
        self.assertNotIn("remote_capture", payload)
        self.assertNotIn("build_ssh_argv", payload)
        self.assertNotIn("sudo", payload.replace("# No sudo/root fallback", ""))
        for forbidden in ("systemctl", "write_text", "write_bytes", "journalctl --flush", "mkdir", "reboot"):
            self.assertNotIn(forbidden, payload)
        namespace = {}
        exec(payload.rsplit("\nprint(", 1)[0], namespace)
        self.assertEqual(namespace["JOURNAL_ARGV"], capture.JOURNAL_ARGV)
        self.assertEqual(namespace["classify_journal"](b""), capture.empty_report("no_previous_journal"))

    def test_kernel_symptoms_require_kernel_provenance_and_never_export_text(self):
        messages = (
            "INFO: task amdgpu:123 blocked for more than 122 seconds /private/path secret-host",
            "INFO: task pciehp:456 blocked for more than 122 seconds",
            "amdgpu_device_ip_fini+0x123/0x456",
            "pciehp_disable_slot+0x123/0x456",
            "pcieport 0000:01:00.0: AER: device recovery failed",
            "xhci_hcd 0000:03:00.0: HC died; cleaning up; controller not responding",
        )
        data = b"".join(journal(message, _TRANSPORT="kernel") for message in messages)
        report = capture.classify_journal(data)
        self.assertEqual(report["symptoms"]["kernel_blocked_task"], 2)
        for category in capture.CATEGORIES[:-2]:
            self.assertGreater(report["symptoms"][category], 0)
        encoded = json.dumps(report)
        for private in ("secret-host", "/private", "0000:", "0x123", "amdgpu:123"):
            self.assertNotIn(private, encoded)
        untrusted = capture.classify_journal(b"".join(journal(message) for message in messages))
        self.assertFalse(any(untrusted["symptoms"].values()))

    def test_systemd_timeout_and_exit126_require_trusted_process(self):
        data = journal("gamescope-session.service: Main process exited, code=exited, status=126/n/a", _COMM="systemd")
        data += journal("plugin_loader.service: State 'stop-sigterm' timed out. Killing.", _COMM="systemd")
        report = capture.classify_journal(data)
        self.assertEqual(report["symptoms"]["session_exit_126"], 1)
        self.assertEqual(report["symptoms"]["systemd_stop_timeout"], 1)
        spoof = capture.classify_journal(journal("gamescope-session status=126/n/a", SYSLOG_IDENTIFIER="systemd"))
        self.assertEqual(spoof["symptoms"]["session_exit_126"], 0)

    def test_checkpoints_are_allowlisted_unit_scoped_and_bounded(self):
        data = b"".join(journal(
            f"[INFO] HDM shutdown checkpoint: stage={stage} elapsed_ms={number}",
            _SYSTEMD_UNIT="plugin_loader.service",
            __MONOTONIC_TIMESTAMP=str(1000000 + number * 1000),
        ) for number, stage in enumerate(capture.STAGES))
        data += journal("HDM shutdown checkpoint: stage=unload_complete elapsed_ms=999", _SYSTEMD_UNIT="other.service")
        data += journal("HDM shutdown checkpoint: stage=unload_complete elapsed_ms=999999999", _SYSTEMD_UNIT="plugin_loader.service")
        data += journal("HDM shutdown checkpoint: stage=secret_hostname elapsed_ms=1", _SYSTEMD_UNIT="plugin_loader.service")
        report = capture.classify_journal(data)
        for number, stage in enumerate(capture.STAGES):
            self.assertEqual(report["checkpoints"][stage], {"count": 1, "last_elapsed_ms": number})
        self.assertEqual(report["coverage"]["span_ms"], len(capture.STAGES) - 1)
        self.assertEqual(report["physical_poweroff"], "unknown")
        self.assertEqual(report["collector"]["installed_revision"], "unknown")
        self.assertEqual(capture.validate_report(json.dumps(report)), report)

    def test_empty_malformed_unknown_and_tail_bounds(self):
        self.assertEqual(capture.classify_journal(b"")["status"], "no_previous_journal")
        malformed = capture.classify_journal(b"not-json\n[]\n" + journal([1, 2, 3]))
        self.assertEqual(malformed["status"], "malformed_journal")
        self.assertEqual(malformed["coverage"]["malformed_rows"], 3)
        unknown = capture.classify_journal(journal("ordinary event with private text"))
        self.assertEqual(unknown["status"], "observed")
        self.assertFalse(any(unknown["symptoms"].values()))
        self.assertEqual(capture.classify_journal(b"x" * (capture.MAX_BYTES + 1))["status"], "size_limit")
        self.assertEqual(capture.classify_journal(journal("x") * (capture.MAX_ROWS + 1))["status"], "size_limit")
        tail = capture.classify_journal(journal("x") * capture.MAX_ROWS)
        self.assertTrue(tail["coverage"]["tail_limit_reached"])
        self.assertEqual(tail["physical_poweroff"], "unknown")

    def test_missing_permissions_failures_and_root_never_fallback(self):
        cases = (
            ((1, b"", b"No journal files were found.", ""), "no_previous_journal"),
            ((1, b"", b"no persistent journal was found", ""), "no_previous_journal"),
            ((1, b"", b"Permission denied secret-host", ""), "permission_denied"),
            ((1, b"", b"No journal files were opened due to insufficient permissions", ""), "permission_denied"),
            ((0, journal("partial"), b"not seeing messages from other users", ""), "permission_denied"),
            ((1, b"", b"unknown private error", ""), "journal_unavailable"),
            ((-9, b"private", b"", "timed_out"), "timed_out"),
            ((-9, b"private", b"", "size_limit"), "size_limit"),
        )
        with patch.object(capture.os, "geteuid", return_value=1000, create=True):
            for result, status in cases:
                with self.subTest(status=status), patch.object(capture, "read_journal", return_value=result):
                    self.assertEqual(capture.collect_previous_boot(), capture.empty_report(status))
        with patch.object(capture.os, "geteuid", return_value=0, create=True), patch.object(capture, "read_journal") as reader:
            self.assertEqual(capture.collect_previous_boot()["status"], "permission_denied")
            reader.assert_not_called()

    def test_strict_local_schema_rejects_private_fields_values_and_fake_provenance(self):
        base = capture.empty_report("observed")
        variants = []
        for key, value in (("hostname", "private"), ("status", "private"), ("physical_poweroff", "complete"), ("schema_version", True)):
            report = copy.deepcopy(base)
            report[key] = value
            variants.append(report)
        report = copy.deepcopy(base)
        report["collector"]["execution_privilege"] = "root_read_only"
        variants.append(report)
        for section, key, value in (("symptoms", "aer_error", True), ("symptoms", "aer_error", 99999), ("coverage", "span_ms", "private")):
            report = copy.deepcopy(base)
            report[section][key] = value
            variants.append(report)
        report = copy.deepcopy(base)
        report["checkpoints"]["unload_started"]["path"] = "/private"
        variants.append(report)
        for report in variants:
            with self.subTest(report=report), self.assertRaises(ValueError):
                capture.validate_report(json.dumps(report))
        for data in ("bad-json", "x" * (capture.MAX_REPORT_BYTES + 1)):
            with self.assertRaises(ValueError):
                capture.validate_report(data)

    def test_ssh_streams_fixed_payload_with_existing_validation_and_hash(self):
        result = subprocess.CompletedProcess([], 0, json.dumps(capture.empty_report("no_previous_journal")), "")
        with patch.object(capture.subprocess, "run", return_value=result) as run:
            report = capture.collect_remote(host="example.test")
        args, kwargs = run.call_args
        self.assertEqual(args[0][-3:], ["deck@example.test", "python3", "-"])
        self.assertNotIn("sudo", args[0])
        self.assertEqual(kwargs["input"], capture.remote_payload())
        self.assertEqual(kwargs["timeout"], 25)
        self.assertEqual(len(report["collector"]["payload_sha256"]), 64)
        self.assertNotIn("example.test", json.dumps(report))
        for arguments in ({"host": "-bad"}, {"host": "ok", "user": "root"}, {"host": "ok", "port": 0}):
            with patch.object(capture.subprocess, "run") as run, self.assertRaises(ValueError):
                capture.collect_remote(**arguments)
            run.assert_not_called()

    def test_ssh_error_text_never_leaves_classifier(self):
        result = subprocess.CompletedProcess([], 255, "", "Permission denied private-user@private-host")
        with patch.object(capture.subprocess, "run", return_value=result):
            with self.assertRaisesRegex(RuntimeError, "^ssh.authentication_failed$"):
                capture.collect_remote(host="example.test")

    def test_missing_journalctl_is_categorical(self):
        with patch.object(capture.subprocess, "Popen", side_effect=FileNotFoundError("private/path")):
            self.assertEqual(capture.read_journal(), (1, b"", b"", "journal_unavailable"))

    def test_reader_timeout_kills_only_its_owned_reader_and_closes_pipes(self):
        process = Mock()
        process.returncode = -9
        process.poll.return_value = None
        selector = Mock()
        selector.get_map.return_value = {1: 1}
        context = Mock()
        context.__enter__ = Mock(return_value=selector)
        context.__exit__ = Mock(return_value=False)
        with (patch.object(capture.subprocess, "Popen", return_value=process) as popen,
              patch.object(capture.selectors, "DefaultSelector", return_value=context),
              patch.object(capture.time, "monotonic", side_effect=[0, 11])):
            self.assertEqual(capture.read_journal(), (-9, b"", b"", "timed_out"))
        self.assertEqual(popen.call_args.args, (capture.JOURNAL_ARGV,))
        self.assertIs(popen.call_args.kwargs["shell"], False)
        self.assertEqual(popen.call_args.kwargs["env"], {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"})
        process.kill.assert_called_once_with()
        process.stdout.close.assert_called_once_with()
        process.stderr.close.assert_called_once_with()

    def test_reader_caps_combined_raw_bytes_before_returning(self):
        process = Mock()
        process.returncode = -9
        process.poll.return_value = None
        selector = Mock()
        selector.get_map.return_value = {1: 1}
        key = Mock(data="stdout", fileobj=process.stdout)
        selector.select.return_value = [(key, 1)]
        context = Mock()
        context.__enter__ = Mock(return_value=selector)
        context.__exit__ = Mock(return_value=False)
        with (patch.object(capture.subprocess, "Popen", return_value=process),
              patch.object(capture.selectors, "DefaultSelector", return_value=context),
              patch.object(capture.os, "read", return_value=b"private bytes"),
              patch.object(capture, "MAX_BYTES", 4)):
            self.assertEqual(capture.read_journal(), (-9, b"", b"", "size_limit"))
        process.kill.assert_called_once_with()

    def test_reader_success_never_signals_other_processes(self):
        process = Mock()
        process.returncode = 0
        process.poll.return_value = 0
        selector = Mock()
        selector.get_map.side_effect = [{1: 1}, {1: 1}, {}]
        key = Mock(data="stdout", fileobj=process.stdout)
        selector.select.return_value = [(key, 1)]
        context = Mock()
        context.__enter__ = Mock(return_value=selector)
        context.__exit__ = Mock(return_value=False)
        data = journal("ordinary event")
        with (patch.object(capture.subprocess, "Popen", return_value=process),
              patch.object(capture.selectors, "DefaultSelector", return_value=context),
              patch.object(capture.os, "read", side_effect=[data, b""])):
            self.assertEqual(capture.read_journal(), (0, data, b"", ""))
        process.kill.assert_not_called()

    def test_reader_cleanup_reap_is_bounded_even_after_kill(self):
        process = Mock()
        process.returncode = None
        process.poll.return_value = None
        process.wait.side_effect = subprocess.TimeoutExpired(capture.JOURNAL_ARGV, 1)
        selector = Mock()
        selector.get_map.return_value = {1: 1}
        context = Mock()
        context.__enter__ = Mock(return_value=selector)
        context.__exit__ = Mock(return_value=False)
        with (patch.object(capture.subprocess, "Popen", return_value=process),
              patch.object(capture.selectors, "DefaultSelector", return_value=context),
              patch.object(capture.time, "monotonic", side_effect=[0, 11])):
            self.assertEqual(capture.read_journal(), (1, b"", b"", "timed_out"))
        process.wait.assert_called_once_with(timeout=1)
        process.stdout.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
