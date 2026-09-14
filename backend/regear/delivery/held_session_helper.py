"""User-only internal held-stop helper. Parent must arm recovery before hold."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    __package__ = 'regear.delivery'

from ..application.held_session_release import HELD_UNITS, STOP_UNITS
from ..adapters.steamos.commands import HeldSessionCommandRunner
from .runtime_mask_lease import MaskLeaseIntent, MaskLeaseJournal, RuntimeMaskLease
from .held_session_recovery import recover


def _snapshot(lease):
    """Copy regular Python sources into a new private recovery package."""
    source = os.open(Path(__file__).resolve().parents[1], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    code = package = None
    budget = [0, 0]
    def copy(src, dst, depth=0):
        names = os.listdir(src)
        if depth > 16 or len(names) > 2048:
            raise ValueError('source tree oversized')
        for name in names:
            if name == '__pycache__':
                continue
            value = os.stat(name, dir_fd=src, follow_symlinks=False)
            if stat.S_ISDIR(value.st_mode):
                os.mkdir(name, 0o700, dir_fd=dst)
                child_src = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=src)
                child_dst = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dst)
                try:
                    copy(child_src, child_dst, depth + 1)
                finally:
                    os.close(child_src)
                    os.close(child_dst)
            elif name.endswith('.py'):
                if not stat.S_ISREG(value.st_mode):
                    raise ValueError('source not regular')
                budget[0] += 1
                if budget[0] > 2048:
                    raise ValueError('source inventory oversized')
                source_file = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=src)
                target = None
                try:
                    if not stat.S_ISREG(os.fstat(source_file).st_mode):
                        raise ValueError('source changed')
                    target = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400, dir_fd=dst)
                    while True:
                        data = os.read(source_file, 65536)
                        if not data:
                            break
                        budget[1] += len(data)
                        if budget[1] > 32 * 1024 * 1024 or os.write(target, data) != len(data):
                            raise ValueError('source copy incomplete')
                    os.fsync(target)
                finally:
                    os.close(source_file)
                    if target is not None:
                        os.close(target)
        os.fsync(dst)
    try:
        os.mkdir('code', 0o700, dir_fd=lease)
        code = os.open('code', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=lease)
        os.mkdir('regear', 0o700, dir_fd=code)
        package = os.open('regear', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=code)
        copy(source, package)
        os.fsync(code)
        os.fsync(lease)
    finally:
        for fd in (package, code, source):
            if fd is not None:
                os.close(fd)


def _open_child(parent, name, uid, *, private=False, create=False):
    if create:
        os.mkdir(name, 0o700, dir_fd=parent)
        os.fsync(parent)
    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    try:
        value = os.fstat(fd)
        if (not stat.S_ISDIR(value.st_mode) or value.st_uid != uid
                or value.st_mode & 0o022 or (private and stat.S_IMODE(value.st_mode) != 0o700)):
            raise ValueError('unsafe directory')
        return fd
    except BaseException:
        os.close(fd)
        raise


def _root(path):
    """Walk every supplied absolute parent without following directory links."""
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('absolute path required')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            value = os.fstat(child)
            if value.st_uid not in (0, os.geteuid()) or value.st_mode & 0o022:
                os.close(child)
                raise ValueError('unsafe runtime ancestor')
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _boot(path):
    with Path(path).open('rb') as stream:
        value = stream.read(129)
    if not re.fullmatch(rb'[a-f0-9-]{36}\n?', value):
        raise ValueError('boot identity unavailable')
    return hashlib.sha256(value.strip()).hexdigest()


def _bounded_names(fd, limit):
    names = []
    with os.scandir(fd) as entries:
        for entry in entries:
            names.append(entry.name)
            if len(names) > limit:
                raise ValueError('inventory oversized')
    return set(names)


def _audit(user, uid, boot_path, commands):
    """Observe settled leases only; even lock files must already exist."""
    import fcntl
    leases = systemd = units = None
    try:
        try:
            leases = _open_child(user, 'regear-held', uid, private=True)
        except FileNotFoundError:
            return True
        names = _bounded_names(leases, 64)
        if any(not re.fullmatch('[a-f0-9]{32}', name) for name in names):
            return False
        if not names:
            return True
        systemd = _open_child(user, 'systemd', uid)
        units = _open_child(systemd, 'user', uid)
        boot = _boot(boot_path)
        for token in sorted(names):
            lease = _open_child(leases, token, uid, private=True)
            journal = masks = None
            lock = None
            try:
                journal = MaskLeaseJournal(lease, owner_uid=uid)
                masks = RuntimeMaskLease(units, lease, owner_uid=uid)
                # Existing-only open is intentional: audit must not repair or
                # create a missing lock as journal.locked() normally can.
                lock = os.open('mask-journal.lock', os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=lease)
                journal._secure(lock)
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                journal._locked = True
                intent = journal.load_intent()
                if intent.token != token or intent.boot_identity != boot or not journal.is_finished(intent):
                    return False
                records = journal.load_masks(intent)
                allowed = {'intent.json', 'mask-journal.lock', 'recovering.json',
                           'finished.json', 'recovery-executor.lock', 'code'}
                for record in records:
                    anchor = token + '-' + record.unit
                    allowed.update((record.unit + '.mask.json', anchor))
                    if (not masks._matches(lease, anchor, record)
                            or masks._matches(units, record.unit, record)):
                        return False
                entries = _bounded_names(lease, 32)
                if not entries <= allowed:
                    return False  # Includes every unresolved retired/quarantine entry.
                if 'code' in entries:
                    code = _open_child(lease, 'code', uid, private=True)
                    os.close(code)
                if 'recovery-executor.lock' in entries:
                    check = os.open('recovery-executor.lock', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=lease)
                    try:
                        journal._secure(check)
                    finally:
                        os.close(check)
            finally:
                if journal is not None:
                    journal._locked = False
                if lock is not None:
                    os.close(lock)
                if masks is not None:
                    masks.close()
                if journal is not None:
                    journal.close()
                os.close(lease)
        return (all(commands.run('load', unit) == 'loaded' for unit in HELD_UNITS)
                and _bounded_names(leases, 64) == names)
    finally:
        for fd in (units, systemd, leases):
            if fd is not None:
                os.close(fd)


def dispatch(action, token, pins=None, *, uid=None, runtime_root=Path('/run/user'),
             boot_path=Path('/proc/sys/kernel/random/boot_id'), commands=None):
    """Return bounded codes. No input can choose a unit, command, or device."""
    descriptors = []
    journal = masks = None
    effective = getattr(os, 'geteuid', lambda: -1)()
    uid = effective if uid is None else uid
    result = {'code': 'held_helper.unavailable', 'safe_to_unplug': False}
    try:
        if type(uid) is not int or uid <= 0 or effective != uid:
            raise ValueError('user required')
        if action not in ('prepare', 'hold', 'restore', 'status', 'audit') or type(token) is not str or not re.fullmatch('[a-f0-9]{32}', token):
            raise ValueError('invalid operation')
        root = _root(runtime_root)
        descriptors.append(root)
        user = _open_child(root, str(uid), uid, private=True)
        descriptors.append(user)
        if action == 'audit':
            if token != '0' * 32 or pins is not None:
                raise ValueError('audit input invalid')
            settled = _audit(user, uid, boot_path, commands or HeldSessionCommandRunner(uid))
            return {**result, 'code': 'held_helper.settled' if settled else 'held_helper.unsettled',
                    'settled': settled}
        if action == 'prepare':
            try:
                os.mkdir('systemd', 0o700, dir_fd=user)
                os.fsync(user)
            except FileExistsError:
                pass
        systemd = _open_child(user, 'systemd', uid)
        descriptors.append(systemd)
        if action == 'prepare':
            try:
                os.mkdir('user', 0o700, dir_fd=systemd)
                os.fsync(systemd)
            except FileExistsError:
                pass
        units = _open_child(systemd, 'user', uid)
        descriptors.append(units)
        try:
            os.mkdir('regear-held', 0o700, dir_fd=user) if action == 'prepare' else None
            if action == 'prepare':
                os.fsync(user)
        except FileExistsError:
            pass
        leases = _open_child(user, 'regear-held', uid, private=True)
        descriptors.append(leases)
        lease = _open_child(leases, token, uid, private=True, create=action == 'prepare')
        descriptors.append(lease)
        current = {'units_device': os.fstat(units).st_dev, 'units_inode': os.fstat(units).st_ino,
                   'lease_device': os.fstat(lease).st_dev, 'lease_inode': os.fstat(lease).st_ino,
                   'boot_identity': _boot(boot_path)}
        if action != 'prepare' and (type(pins) is not dict or pins != current
                or any(type(pins[key]) is not int for key in current if key != 'boot_identity')):
            return {**result, 'code': 'held_helper.identity_changed'}
        commands = commands or HeldSessionCommandRunner(uid)
        journal = MaskLeaseJournal(lease, owner_uid=uid)
        if action == 'prepare':
            prior = []
            for unit in HELD_UNITS:
                if commands.run('load', unit) != 'loaded':
                    raise ValueError('unsupported unit')
                state = commands.run('state', unit)
                if state not in ('active', 'inactive'):
                    raise ValueError('unit state unavailable')
                if state == 'active':
                    prior.append(unit)
            if 'gamescope-session.service' in prior and 'gamescope-session.target' not in prior:
                raise ValueError('session target restoration unavailable')
            intent = MaskLeaseIntent(token, current['boot_identity'], tuple(prior))
            with journal.locked():
                journal.create_intent(intent)
            _snapshot(lease)
            return {**result, 'code': 'held_helper.prepared', 'pins': current}
        with journal.locked():
            intent = journal.load_intent()
            if intent.token != token or intent.boot_identity != current['boot_identity']:
                raise ValueError('intent mismatch')
        if action == 'restore':
            recovery = recover(units_fd=units, lease_fd=lease, uid=uid, token=token,
                               boot_identity=current['boot_identity'], commands=commands)
            return {**result, 'code': recovery.code, 'restored': recovery.restored}
        masks = RuntimeMaskLease(units, lease, owner_uid=uid)
        def published():
            records = journal.load_masks(intent)
            return (len(records) == len(HELD_UNITS) and {record.unit for record in records} == set(HELD_UNITS)
                    and all(masks._matches(units, record.unit, record) for record in records))
        if action == 'status':
            with journal.locked():
                active = journal.ownership_active(intent)
                finished = journal.is_finished(intent)
            held = active and all(commands.run('load', unit) == 'masked'
                and commands.run('state', unit) == 'inactive' for unit in HELD_UNITS)
            with journal.locked():
                active = active and journal.ownership_active(intent)
                finished = journal.is_finished(intent)
                held = held and active and published()
            return {**result, 'code': 'held_helper.status', 'held': held,
                    'ownership_active': active, 'finished': finished}
        try:
            for unit in HELD_UNITS:
                with journal.locked():
                    if not journal.ownership_active(intent):
                        raise ValueError('ownership revoked')
                    masks.create(unit, token, lambda identity: journal.record_mask(intent, identity))
            if commands.run('reload') is not True:
                raise ValueError('reload failed')
            if not all(commands.run('load', unit) == 'masked' for unit in HELD_UNITS):
                raise ValueError('mask ineffective')
            for unit in STOP_UNITS:
                with journal.locked():
                    if (not journal.ownership_active(intent) or not published()
                            or commands.run('stop', unit) is not True):
                        raise ValueError('stop refused')
            verified = all(commands.run('load', unit) == 'masked' and commands.run('state', unit) == 'inactive'
                           for unit in HELD_UNITS)
            with journal.locked():
                if not journal.ownership_active(intent) or not published() or not verified:
                    raise ValueError('held state unavailable')
            return {**result, 'code': 'held_helper.held'}
        except Exception:
            recovery = recover(units_fd=units, lease_fd=lease, uid=uid, token=token,
                               boot_identity=current['boot_identity'], commands=commands)
            return {**result, 'code': 'held_helper.hold_failed', 'restored': recovery.restored}
    except Exception:
        return result
    finally:
        if masks is not None:
            masks.close()
        if journal is not None:
            journal.close()
        for fd in reversed(descriptors):
            os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'hold', 'restore', 'status', 'audit'))
    parser.add_argument('token')
    parser.add_argument('--pins', default='null')
    args = parser.parse_args()
    try:
        if len(args.pins) > 1024:
            raise ValueError('pins oversized')
        pins = json.loads(args.pins)
    except ValueError:
        print('{"code":"held_helper.invalid_pins","safe_to_unplug":false}')
        return 1
    result = dispatch(args.action, args.token, pins)
    print(json.dumps(result, separators=(',', ':')))
    return 0 if result['code'] in ('held_helper.prepared', 'held_helper.held', 'held_helper.status',
        'held_recovery.restored', 'held_recovery.already_restored', 'held_helper.settled') else 1


if __name__ == '__main__':
    raise SystemExit(main())
