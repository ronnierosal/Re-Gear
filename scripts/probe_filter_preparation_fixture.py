"""Disposable combined preparation and ordered recovery; never grants launch."""
import json
from pathlib import Path
import sys

if Path(__file__).name != '__main__.py':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

from hdm.delivery.device_filter_preparation import FilterPreparation
from hdm.delivery.device_filter_recovery import FilterRecovery
from hdm.delivery.device_receive_attachment import ReceiveAttachmentResult
from hdm.delivery.device_filter_lifecycle import Phase, PairedStage
from scripts.probe_receive_attachment_fixture import publish_controller
from scripts.probe_paired_journal_fixture import run_fixture


class PreparationAdapter:
    def __init__(self, journal, observe):
        self.controller = FilterPreparation(journal, observe)

    def attach(self, operation, unit, directory, *, policy):
        result = self.controller.prepare(operation, unit, directory, policy=policy)
        if result.prepared is not True or result.launch_authorized or result.disconnect_clearance:
            raise ValueError('non-authorizing preparation required')
        return ReceiveAttachmentResult(result.revision, result.paired, policy.program_sha256)


def publish_preparation(*args, **kwargs):
    return publish_controller(*args, controller_factory=PreparationAdapter, **kwargs)


def recover_preparation(journal_factory, binding, *, current_boot_hash,
                        observe_denial, observe_restored, recovery_factory=FilterRecovery):
    journal = journal_factory()
    with journal.transaction() as tx:
        before = tx.read(binding.operation, binding.unit)
    if (before.lifecycle.binding != binding or before.lifecycle.phase is not Phase.ATTACHED
            or before.lifecycle.owned is None or before.paired is None
            or before.paired.stage is not PairedStage.RECEIVE_CONFIRMED or before.delivery_granted):
        raise ValueError('combined durable preparation absent')
    if observe_denial() is not True:
        raise ValueError('prepared denial unavailable')
    result = recovery_factory(journal).recover(binding.operation, binding.unit,
                                               current_boot_hash=current_boot_hash)
    with journal.transaction() as tx:
        after = tx.read(binding.operation, binding.unit)
    if (result.outcome != 'owned_pin_removed' or result.launch_authorized or result.disconnect_clearance
            or after.lifecycle.binding != binding or after.lifecycle.phase is not Phase.CANCELLED
            or after.lifecycle.owned != before.lifecycle.owned or after.paired is None
            or after.paired.stage is not PairedStage.COMPLETE
            or after.paired.receive != before.paired.receive or after.paired.map_id != before.paired.map_id
            or after.revision <= before.revision or after.delivery_granted):
        raise ValueError('combined recovery incomplete')
    if observe_restored() is not True:
        raise ValueError('prepared controls not restored')
    return dict(combined_preparation_verified=True, direct_pin_removed=True,
        direct_open_denial_verified=False,
        durable_cancellation_observed=True, paired_complete_observed=True,
        null_zero_restored=True, launch_authorized=False, disconnect_clearance=False)


def main():
    if sys.argv[1:] != ['--disposable-fixture']:
        raise SystemExit('Explicit --disposable-fixture required')
    report = run_fixture(publisher=publish_preparation, recoverer=recover_preparation)
    print(json.dumps(report, sort_keys=True))
    return 0 if report['state'] == 'fixture_passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
