#!/usr/bin/env python3
"""Local, preview-first community report using the existing Re-Gear CLI.

Python standard library only. No network, sudo, system mutation, or raw logs.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import selectors
import subprocess
import sys
import time
from datetime import datetime, timezone

LIMIT = 256 * 1024
TIMEOUT = 30


def read_text(path: Path, limit: int = 8192) -> str:
    try:
        with path.open('rb') as stream:
            data = stream.read(limit + 1)
        return data.decode('utf-8') if len(data) <= limit else ''
    except (OSError, UnicodeError):
        return ''


def mapping(value):
    return value if isinstance(value, dict) else {}


def choice(value, choices):
    return value if isinstance(value, str) and value in choices else 'unknown'


def boolean(value):
    return value if type(value) is bool else None


def items(value):
    return value[:16] if isinstance(value, list) else []


def summarize(payload):
    """Rebuild output; never forward arbitrary collector keys, text or errors."""
    snapshot = mapping(mapping(payload).get('snapshot'))
    return {
        'game_state': choice(snapshot.get('game_state'), ('idle', 'running')),
        'gpus': [
            {'role': choice(mapping(g).get('role'), ('internal', 'external')),
             'present': boolean(mapping(g).get('present')),
             'selected_for_render': boolean(mapping(g).get('selected_for_render'))}
            for g in items(snapshot.get('gpus'))
        ],
        'displays': [
            {'kind': choice(mapping(d).get('kind'), ('internal', 'external')),
             'connected': boolean(mapping(d).get('connected')),
             'active': boolean(mapping(d).get('active'))}
            for d in items(snapshot.get('displays'))
        ],
        'gamescope_running': boolean(mapping(snapshot.get('gamescope')).get('running')),
        'safe_to_unplug': False,
    }


def build_info(root):
    result = {'version': 'unknown', 'revision': 'unknown'}
    try:
        value = mapping(json.loads(read_text(root / 'build_info.json')))
    except ValueError:
        return result
    if type(value.get('schema_version')) is not int or value['schema_version'] != 1:
        return result
    version, revision = value.get('version'), value.get('revision')
    if isinstance(version, str) and re.fullmatch(r'\d{1,5}\.\d{1,5}\.\d{1,5}', version):
        result['version'] = version
    if isinstance(revision, str) and re.fullmatch(r'[0-9a-f]{40}', revision):
        result['revision'] = revision
    elif revision in ('uncommitted', 'unavailable'):
        result['revision'] = revision
    return result


def os_info(release=Path('/etc/os-release'), kernel=Path('/proc/sys/kernel/osrelease')):
    values = {}
    for line in read_text(release).splitlines():
        key, sep, value = line.partition('=')
        if sep:
            values[key] = value.strip().strip('\"\'')
    version = values.get('VERSION_ID', '')
    match = re.match(r'^(\d{1,5}\.\d{1,5}\.\d{1,5})(?:[-+\s]|$)', read_text(kernel))
    return {
        'distribution': choice(values.get('ID'), ('steamos', 'holo', 'bazzite', 'fedora', 'arch')),
        'version': version if re.fullmatch(r'\d{1,8}(?:\.\d{1,8}){0,3}', version) else 'unknown',
        'kernel_core_version': match.group(1) if match else 'unknown',
        'decky_version': 'unknown',
    }


def find_plugin(explicit=None, home=None):
    root = Path(explicit) if explicit else (home or Path.home()) / 'homebrew/plugins/HandheldDockMode'
    if (root / 'backend/hdm/cli.py').is_file() and (root / 'plugin.json').is_file():
        return root.resolve()
    return None


def collect(root, timeout=TIMEOUT):
    """Bound child output and duration; never print its errors or raw payload."""
    env = {key: os.environ[key] for key in
           ('HOME', 'USER', 'LOGNAME', 'XDG_RUNTIME_DIR', 'DBUS_SESSION_BUS_ADDRESS')
           if key in os.environ}
    env.update(PATH='/usr/bin:/bin', LANG='C.UTF-8')
    command = [sys.executable, '-I', '-B', '-c',
               'import sys; sys.path.insert(0,sys.argv[1]); '
               'sys.argv=["hdm-diagnose","--compact"]; '
               'from hdm.cli import main; raise SystemExit(main())', str(root / 'backend')]
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, env=env, cwd=root)
    data = bytearray()
    deadline = time.monotonic() + timeout
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return {}, 'timed_out'
                if not selector.select(remaining):
                    return {}, 'timed_out'
                chunk = os.read(process.stdout.fileno(), min(8192, LIMIT + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
                if len(data) > LIMIT:
                    return {}, 'output_too_large'
        try:
            code = process.wait(timeout=max(0.01, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            return {}, 'timed_out'
        if code:
            return {}, 'collector_failed'
        try:
            value = json.loads(data)
        except (ValueError, UnicodeError):
            return {}, 'invalid_output'
        if not isinstance(value, dict) or not isinstance(value.get('snapshot'), dict):
            return {}, 'invalid_output'
        return value, 'collected'
    finally:
        # Only our own diagnostic child is stopped; no existing service is signaled.
        if process.poll() is None:
            process.kill()
        process.wait()
        process.stdout.close()


def save_reviewed(text, directory, answer):
    if answer.strip().lower() != 'save':
        return None
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    path = directory / f'Re-Gear-community-report-{stamp}.json'
    # Exclusive creation refuses an existing file or symlink. No directory creation.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
        stream.write(text)
    return path.name


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plugin-root', type=Path, help='optional path to your trusted installed plugin')
    args = parser.parse_args(argv)
    if sys.platform != 'linux':
        print('Run this helper on the SteamOS/Linux handheld, using Python 3.')
        return 2
    if os.geteuid() == 0:
        print('Run as your normal user, without sudo.')
        return 2
    root = find_plugin(args.plugin_root)
    payload, status = {}, 'plugin_not_found'
    if root:
        print('Collecting one read-only snapshot (up to 30 seconds)...')
        try:
            payload, status = collect(root)
        except (OSError, ValueError):
            status = 'collector_unavailable'
    report = {
        'community_report_schema': 1,
        'collector_status': status,
        'source': 'selected_plugin_tree' if root else 'unavailable',
        'build_identity': build_info(root) if root else {'version': 'unknown', 'revision': 'unknown'},
        'operating_system': os_info(),
        'observed_state': summarize(payload),
        'user_to_complete': {
            'hardware_models_and_connection': 'add model names; no serial numbers',
            'steps_expected_actual_and_repeatability': 'describe your observations',
            'picture_controls_audio_afterward': 'describe what remained working',
        },
        'limits': [
            'Point-in-time CLI observation; no in-memory Decky history.',
            'Build metadata describes the selected files, not proof the running plugin matches.',
            'Unknown or null means unavailable; kernel suffix and private identifiers are omitted.',
            'No hardware certification or physical unplug clearance.',
        ],
    }
    text = json.dumps(report, indent=2, sort_keys=True) + '\n'
    print('\nReview this report before sharing. Nothing has been uploaded.\n')
    print(text, end='')
    print('Model names and player-observed results still need your description.')
    if not sys.stdin.isatty():
        print('Non-interactive run: preview only; no report saved.')
        return 0
    try:
        answer = input('Type save to write this exact JSON in the current folder; Enter cancels: ')
        name = save_reviewed(text, Path.cwd(), answer)
    except (EOFError, KeyboardInterrupt):
        print('\nCancelled; no report saved.')
        return 0
    except OSError:
        print('Could not save the report. No existing report was overwritten.')
        return 1
    print(f'Saved {name}. Review it before attaching to discussion #91.' if name else 'No report saved.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
