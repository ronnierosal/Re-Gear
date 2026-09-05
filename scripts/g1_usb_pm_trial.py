"""Supervised developer trial, not a Re-Gear feature or a safe-unplug tool.

Default is read-only. --apply must start detached as root in a local terminal.
Changes only the dynamically bound G1 xHCI power/control, then restores it.
The observation has a deadline; a blocked kernel write cannot be cancelled or
promised to roll back by that deadline. A watchdog reports this, without racing
another write/reset against it. Keep G1 attached until full system power-off.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import tempfile
import threading
import time

from capture_g1_pcie_health import counters, identity, read

PCI = Path('/sys/bus/pci/devices')
BOOT = Path('/proc/sys/kernel/random/boot_id')


def discover(registry=PCI):
    nodes = list(registry.iterdir())
    if len(nodes) > 512:
        raise ValueError('inventory_limit')
    internal = [n for n in nodes if identity(n) == ('0x1002', '0x15bf')]
    gpus = [n for n in nodes if identity(n) == ('0x1002', '0x7480')]
    if len(internal) != 1:
        raise ValueError('host_gpu_unverified')
    if not gpus:
        return None
    if len(gpus) != 1:
        raise ValueError('ambiguous_g1')
    gpu = gpus[0].resolve(strict=True)
    bridges = [n for n in gpu.parents if identity(n) == ('0x8086', '0x15ef')]
    if not bridges:
        raise ValueError('g1_transport_unverified')
    branch = bridges[-1]
    usb = [n.resolve(strict=True) for n in nodes
           if identity(n) == ('0x8086', '0x15f0')
           and n.resolve(strict=True).is_relative_to(branch)]
    if len(usb) != 1:
        raise ValueError('g1_usb_unverified')
    usb = usb[0]
    if identity(usb.parent) != ('0x8086', '0x15ef'):
        raise ValueError('usb_bridge_unverified')
    if read(usb / 'class') != '0x0c0330':
        raise ValueError('usb_class_unverified')
    if not (usb / 'driver').exists() or (usb / 'driver').resolve().name != 'xhci_hcd':
        raise ValueError('usb_driver_unready')
    if not (gpu / 'driver').exists() or (gpu / 'driver').resolve().name != 'amdgpu':
        raise ValueError('gpu_driver_unready')
    return gpu, usb, branch


def clean(target):
    gpu, usb, branch = target
    for node in {gpu, usb, usb.parent, branch}:
        for name in ('aer_dev_nonfatal', 'aer_dev_fatal'):
            values = counters(node / name)
            if values is None or any(values.values()):
                raise ValueError('aer_missing_or_nonzero')
    if list(usb.rglob('block')):
        raise ValueError('usb_storage_present')


def fingerprint(target, boot=BOOT):
    return (read(boot), tuple((str(n), n.stat().st_ino, identity(n)) for n in target))


def emit(event, **values):
    print(json.dumps({'event': event, 'unix_time': time.time(), **values}), flush=True)


def change_and_restore(target, *, hold_seconds, stop, emit_event=emit,
                       validate=clean, identify=fingerprint,
                       open_control=None, wait=None):
    """Serialized writes through one original fd; injectable fixture boundary."""
    usb = target[1]
    validate(target)
    original = read(usb / 'power/control')
    if original != 'auto':
        raise ValueError('baseline_must_be_auto')
    bound = identify(target)
    if bound[0] is None:
        raise ValueError('boot_unverified')
    opener = open_control or (lambda p: open(p, 'r+', encoding='ascii'))
    waiter = wait or stop.wait
    attempted = False
    restored = False
    with opener(usb / 'power/control') as control:
        try:
            validate(target)
            if stop.is_set():
                raise ValueError('cancelled_before_write')
            if identify(target) != bound or read(usb / 'power/control') != original:
                raise ValueError('target_changed_before_write')
            emit_event('apply_started', original=original, controller=str(usb))
            attempted = True
            control.seek(0)
            control.write('on\n')
            control.flush()
            if read(usb / 'power/control') != 'on':
                raise ValueError('apply_readback_failed')
            if read(usb / 'power/runtime_status') != 'active':
                raise ValueError('controller_not_active')
            emit_event('holding', seconds=hold_seconds)
            deadline = time.monotonic() + hold_seconds
            while not stop.is_set() and time.monotonic() < deadline:
                if identify(target) != bound:
                    raise ValueError('target_changed_during_hold')
                validate(target)
                if read(usb / 'power/control') != 'on':
                    raise ValueError('control_changed_during_hold')
                waiter(min(0.25, max(0, deadline - time.monotonic())))
        finally:
            if attempted:
                if identify(target) != bound:
                    emit_event('restore_unverified', reason='target_changed')
                else:
                    current = read(usb / 'power/control')
                    if current == original:
                        restored = True
                    elif current == 'on':
                        emit_event('restore_started')
                        control.seek(0)
                        control.write(original + '\n')
                        control.flush()
                        restored = read(usb / 'power/control') == original
                    emit_event('restored' if restored else 'restore_unverified')
                if not restored:
                    raise RuntimeError('restore_unverified_keep_connected')
    return restored


def watch_deadline(finished, stop, seconds, record):
    if not finished.wait(seconds):
        stop.set()
        record('deadline_exceeded', state='unknown_keep_connected_no_reset')


def validate_durations(wait_seconds, hold_seconds):
    if type(wait_seconds) is not int or not 1 <= wait_seconds <= 600:
        raise ValueError('wait must be 1..600 seconds')
    if type(hold_seconds) is not int or not 1 <= hold_seconds <= 300:
        raise ValueError('hold must be 1..300 seconds')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--wait-seconds', type=int, default=600)
    parser.add_argument('--hold-seconds', type=int, default=180)
    args = parser.parse_args()
    try:
        validate_durations(args.wait_seconds, args.hold_seconds)
    except ValueError as error:
        parser.error(str(error))
    if not args.apply:
        target = discover()
        if target:
            clean(target)
        emit('read_only', target_present=target is not None)
        return
    if os.geteuid() != 0 or not os.isatty(0):
        parser.error('apply requires root in a local interactive terminal')
    # A flock lives as long as this process, including during a blocked syscall.
    import fcntl
    lock_fd = os.open('/run/regear-g1-usb-pm.lock',
                      os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if discover() is not None:
            raise ValueError('start_with_g1_detached')
        # Also reject a partially enumerated transport at startup.
        if any(identity(n) in {('0x8086', '0x15ef'), ('0x8086', '0x15f0')}
               for n in PCI.iterdir()):
            raise ValueError('start_with_transport_detached')
        report = Path(tempfile.mkdtemp(prefix='regear-g1-usb-pm-', dir='/run')) / 'events.jsonl'
        stop = threading.Event()
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, lambda *_: stop.set())

        def record(event, **values):
            row = {'event': event, 'unix_time': time.time(), **values}
            with report.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(row) + '\n')
                stream.flush()
                os.fsync(stream.fileno())
            try:
                emit(event, **values)
            except (BrokenPipeError, OSError):
                stop.set()

        record('armed_detached', report=str(report), wait_seconds=args.wait_seconds)
        deadline = time.monotonic() + args.wait_seconds
        target = None
        while not stop.is_set() and time.monotonic() < deadline:
            # Incomplete driver/transport enumeration is retryable only before
            # any mutation. Ambiguity/host mismatch always aborts.
            try:
                target = discover()
            except ValueError as exc:
                if str(exc) not in {'g1_transport_unverified', 'g1_usb_unverified',
                                    'usb_driver_unready', 'gpu_driver_unready'}:
                    raise
            if target:
                break
            stop.wait(0.1)
        if target is None or stop.is_set():
            record('ended_without_write')
            return
        finished = threading.Event()

        threading.Thread(target=watch_deadline,
                         args=(finished, stop, args.hold_seconds + 10, record),
                         daemon=True).start()
        try:
            change_and_restore(target, hold_seconds=args.hold_seconds,
                               stop=stop, emit_event=record)
        finally:
            finished.set()
    finally:
        os.close(lock_fd)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError) as error:
        emit('stopped', reason=str(error), safe_to_unplug=False)
        raise SystemExit(1)
