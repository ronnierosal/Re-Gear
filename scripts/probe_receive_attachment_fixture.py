"""Disposable recovery-only attachment controller integration; no player service."""
import hashlib
import json
import os
from pathlib import Path
import sys

if Path(__file__).name != '__main__.py':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

from hdm.delivery.device_filter_attachment import AttachmentObservation
from hdm.delivery.device_filter_btf import parse_file_receive_btf
from hdm.delivery.device_filter_lifecycle import PairedStage
from hdm.delivery.device_receive_attachment import ReceiveAttachmentController, ReceiveAttachmentPolicy
from hdm.delivery.device_receive_program import compile_device_receive
from scripts.probe_paired_journal_fixture import run_fixture


def publish_controller(journal, binding, directory, layout, null_device, *,
                       observe_denial, stage=lambda value: None,
                       controller_factory=ReceiveAttachmentController, read_btf=None):
    # Synthetic waiting evidence belongs only to the owned dummy receiver.
    # This adapter is never a player-session authentication source.
    if read_btf is None:
        def read_btf():
            with open('/sys/kernel/btf/vmlinux', 'rb') as source:
                return source.read(64 * 1024 * 1024 + 1)
    raw = read_btf()
    if parse_file_receive_btf(raw, pointer_size=8) != layout:
        raise ValueError('running layout changed')
    devices = ((os.major(null_device), os.minor(null_device)),)
    code = compile_device_receive((binding.cgroup_inode,), devices,
        file_inode_offset=layout.file_inode_offset,
        inode_mode_offset=layout.inode_mode_offset,
        inode_rdev_offset=layout.inode_rdev_offset)
    policy = ReceiveAttachmentPolicy(binding, layout, hashlib.sha256(raw).hexdigest(),
                                    hashlib.sha256(code).hexdigest())
    observation = AttachmentObservation(binding, devices, True, True)
    stage('controller_attachment')
    result = controller_factory(journal, lambda: observation).attach(
        binding.operation, binding.unit, directory, policy=policy)
    if (result.launch_authorized or result.disconnect_clearance
            or result.ownership.stage is not PairedStage.RECEIVE_CONFIRMED
            or result.program_sha256 != policy.program_sha256):
        raise ValueError('recovery-only attachment not confirmed')
    if observe_denial() is not True:
        raise ValueError('controller denial unavailable')


def main():
    if sys.argv[1:] != ['--disposable-fixture']:
        raise SystemExit('Explicit --disposable-fixture required')
    report = run_fixture(publisher=publish_controller)
    report['attachment_controller_requested'] = True
    print(json.dumps(report, sort_keys=True))
    return 0 if report['state'] == 'fixture_passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
