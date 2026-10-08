"""Local coordination for cooperating agents. No network, credentials, or execution."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import html
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
import uuid

# Installed copies live beside the shared database. Repository sources require
# an explicit database so a worktree cannot silently create a competing hub.
DEFAULT_DB = (Path(__file__).resolve().parent / 'data' / 'hub.sqlite3'
              if Path(__file__).resolve().parent.name == 'agent-hub' else None)
STATES = ('todo', 'in_progress', 'blocked', 'review', 'done', 'cancelled')

MAINTAINER = 'codex-01a080fd'
MAINTENANCE_TASK = 'agent-hub-unavailable-owner-closeout-498'
MAINTENANCE_ISSUE = 'https://github.com/ronnierosal/Re-Gear/issues/498'
# These remain deliberately unset in the implementation candidate. A later,
# separately reviewed change must compile the exact invocation approvals before
# either command can mutate a hub.
CLOSEOUT_EXECUTION_AUTHORIZATION = None
RANGE_EXECUTION_AUTHORIZATION = None
MAINTENANCE_ASSIGNMENT_DIGEST = '4b3643ddaced86da253f4b7050672ce5010709c7a208cf85598756de72a060f7'
RANGE_NEW_BRANCH = 'agent/codex-local/497-tdp-expressible-range-admission'
APPROVED_TASKS = {'tdp-readiness-evidence-setup': {'id': 'tdp-readiness-evidence-setup',
                                  'stream': 'auto-tdp',
                                  'title': 'P0: Make manual and Auto TDP readiness evidence actionable',
                                  'owner': 'claude-3e188980-234d-4e35-9a46-1b048630ba63',
                                  'state': 'review',
                                  'branch': 'claude/tdp-readiness-evidence-setup',
                                  'paths': '["backend/regear/delivery/auto_tdp_status.py", '
                                           '"scripts/probe_auto_tdp_context.py", '
                                           '"tests/test_auto_tdp_status.py"]',
                                  'dependencies': '[]',
                                  'evidence': 'Commit f394344 on base ccbf275. PR '
                                              'https://github.com/ronnierosal/Re-Gear/pull/277, draft. Gate: '
                                              'architecture passed, 2894 tests OK with 109 skips, compileall '
                                              'clean. Mutation check: replacing the expressible-range '
                                              'computation with the naive sustained-only maximum fails 5 of '
                                              'the 7 new tests. Existing probe test asserting exactly two '
                                              'provider observe calls still passes, so no extra device reads '
                                              'were added. Probe still runs standalone and degrades to null '
                                              'evidence without a provider. Merge state: not merged.',
                                  'note': 'Audit first, then one demonstrated gap fixed.\n'
                                          'Demonstrated gap: readiness reports only the sustained register '
                                          'range. A request maps onto the boost registers as max(watts, '
                                          'register.minimum), so a boost ceiling below the sustained ceiling '
                                          'narrows the usable range invisibly. TdpRuntime._status exposes '
                                          'sustained min/max, validAutoTdpRange validates against those, '
                                          'can_start goes true, and the session then refuses per-tick as '
                                          'auto_tdp.readback_invalid. Correct but late and generic.\n'
                                          'Result: the existing read-only probe now reports each register '
                                          'range separately and the actually expressible sustained range, '
                                          'with categorical codes for fully expressible, narrowed by boost '
                                          'ceiling, and no expressible range. Evidence is reported even when '
                                          'the host context is unusable, since such a device can still '
                                          'explain why it will not start. Pinned against '
                                          'TdpReading.target_values across the whole sustained range for '
                                          'four register shapes, so reported bounds cannot drift from real '
                                          'acceptance.\n'
                                          'Behavior change: probe output gains registers and expressible '
                                          'keys. No admission, no writes, no extra provider reads, no raw '
                                          'provider identifier.\n'
                                          'Remaining gaps, deliberately not in this slice: competing writer, '
                                          'journal recovery state, render/game/placement eligibility, '
                                          'thermal configuration and full-collector benchmark evidence. Most '
                                          'already have categorical codes in the readiness chain; auditing '
                                          'which are genuinely missing before adding, per '
                                          'fix-only-demonstrated-gaps. Surfacing the boost limit in '
                                          'can_start itself needs TdpRuntime._status or main.py; main.py is '
                                          'a shared hotspot listed by three unowned eGPU tasks, so I did not '
                                          'expand into it unilaterally. Recommend it as a follow-up task '
                                          'with an agreed owner.\n'
                                          'Known limitations: no device evidence. The narrowed register '
                                          'shape is synthesised from provider semantics and has never been '
                                          'observed on hardware.\n'
                                          'Documentation impact: none\n'
                                          'Next: review.',
                                  'issue': '',
                                  'pr': 'https://github.com/ronnierosal/Re-Gear/pull/277',
                                  'rev': 3,
                                  'updated': '2026-09-10T23:09:11+00:00'},
 'tdp-lifecycle-gap-verification': {'id': 'tdp-lifecycle-gap-verification',
                                    'stream': 'auto-tdp',
                                    'title': 'P0: Close demonstrated manual and Auto TDP lifecycle gaps',
                                    'owner': 'claude-58d0fbe8-bd82-4bd1-ad84-6dd1d31e03b7',
                                    'state': 'review',
                                    'branch': 'claude/tdp-lifecycle-gap-verification',
                                    'paths': '["backend/regear/delivery/auto_tdp_factory.py", '
                                             '"tests/test_auto_tdp_factory.py", '
                                             '"tests/test_auto_tdp_replays.py", '
                                             '"tests/test_auto_tdp_session.py", "tests/test_tdp_control.py"]',
                                    'dependencies': '[]',
                                    'evidence': 'Revised head 697ffa8f67d597c2011f7cc7f0184b1796e9a48e on '
                                                'base d5937c6 (origin/main moved past ab87e2e0 to 3c9d6db '
                                                'and then d5937c6 during this cycle; branch carries a merge '
                                                'of current main, not a rewrite - no force push was used). '
                                                'PR https://github.com/ronnierosal/Re-Gear/pull/319 OPEN, '
                                                'MERGEABLE/CLEAN, not merged. Gate on the revised head: '
                                                'check_architecture passed; compileall clean; unittest '
                                                'discover -s tests 3059 OK 109 skipped; '
                                                'check_golden_behaviors 29/29 across 7 contracts. Final-head '
                                                'CI: foundation pass, privileged-user-delivery pass. '
                                                'MUTATION (source only, tests unchanged, both reverted): '
                                                'reverting the default to time.monotonic fails 4 of 13; '
                                                'making _session_clock suspend-blind fails 2 of 13, with the '
                                                "end-to-end test failing 'tdp.readback_verified' != "
                                                "'auto_tdp.sample_unavailable' - the pre-suspend streak "
                                                'completing quorum and writing after an eight-hour sleep, '
                                                'which is the defect itself. No hardware, install or release '
                                                'action; no device evidence.',
                                    'note': 'REVIEW FIX RETURNED. Primary review '
                                            '8de50e2f09834022a2f1a3d0b782d8f6 accepted the clock diagnosis '
                                            'and minimal seam and asked for one end-to-end regression on the '
                                            "factory's DEFAULT clock. Added as "
                                            'test_the_default_clock_composition_rejects_a_pre_suspend_streak: '
                                            'composes the factory with clock omitted, models an awake '
                                            'monotonic clock and a suspend-inclusive elapsed clock behind '
                                            "the module's time, and reads frame and sensor timestamps from "
                                            'whichever clock the composition selected, so the arms differ '
                                            'only by the sleep and not by a mismatched fake epoch. Awake arm '
                                            'still reaches its first verified write on the ordinary cadence; '
                                            'sleep arm rejects the old evidence and settles fresh. Existing '
                                            'injected-clock behaviour arms and the clock/fallback unit tests '
                                            'are retained.\n'
                                            'Monotonic fallback limitation recorded explicitly in the '
                                            '_session_clock docstring: where CLOCK_BOOTTIME is unavailable '
                                            'the suspend is invisible again. No blocking policy added - '
                                            'refusing to run on an unobservable condition would be '
                                            'speculation, not a guard.\n'
                                            'HISTORY NOTE: I had rebased onto the advanced main, which made '
                                            'the push non-fast-forward. Force pushes need human approval '
                                            'under AGENTS.md, and the rewrite was avoidable, so I reset back '
                                            'to the pushed commit, merged current origin/main and '
                                            'cherry-picked the review fix. The branch history was never '
                                            'rewritten and no approval was needed.\n'
                                            'No whole-matrix rediscovery was repeated. Scope unchanged: no '
                                            'main.py, suspend-observer, dock/eGPU or UI edit.\n'
                                            'Documentation impact: none\n'
                                            'Next: awaiting primary combined integration review. Then, per '
                                            'the same message, claim '
                                            'tdp-post-session-steam-resolution-feasibility under this ID in '
                                            'a separate isolated worktree, without waiting for #277 '
                                            'ownership recovery or #319 merge, consolidating the voice '
                                            'requirements (mode-aware Steam resolution, supported managed '
                                            'framegen, base vs generated FPS, permanent popup suppression) '
                                            'into that task note on claim; the per-game settings guide is '
                                            'the subsequent task.',
                                    'issue': '',
                                    'pr': 'https://github.com/ronnierosal/Re-Gear/pull/319',
                                    'rev': 6,
                                    'updated': '2026-09-13T16:51:59+00:00'},
 'tdp-readiness-evidence-recovery-277': {'id': 'tdp-readiness-evidence-recovery-277',
                                         'stream': 'primary-auto-tdp',
                                         'title': 'Recover, refresh, and integrate PR277 provider-range '
                                                  'diagnostics',
                                         'owner': 'codex-auto-tdp-01a097b0-ac26-7e92-915c-b5c68d2a1b13',
                                         'state': 'done',
                                         'branch': 'codex/integration-auto-tdp-277',
                                         'paths': '[]',
                                         'dependencies': '[]',
                                         'evidence': 'PR277 merged by delegated closeout driver as squash '
                                                     'commit 1ff4de5f43d8bab2defa20739c2d69f855087d88 from '
                                                     'exact accepted head '
                                                     'cc802b76fc0d5beaf5e19ce0c9ba766c4f251cae/base '
                                                     'c75ff5ae6050d2f068d3e58ecd19f24bfefc3ea1. Final-head '
                                                     'checks all passed; local exact-head gates: '
                                                     'architecture/compile pass, backend 3668 OK/298 '
                                                     'skipped, golden49/49 across8, frontend764 pass/1 '
                                                     'existing skip, '
                                                     'typecheck/build/plugin-package/diff/preflight pass; '
                                                     'independent review no blockers with 11 focused tests. '
                                                     'Post-merge CI run35553433335 SUCCESS and '
                                                     'privileged-user-delivery run35553433343 SUCCESS at '
                                                     'merge commit. Effective merged diff remains '
                                                     'scripts/probe_auto_tdp_context.py and '
                                                     'tests/test_auto_tdp_status.py diagnostic-only. No '
                                                     'runtime admission, install, release, device, or '
                                                     'hardware claim.',
                                         'note': 'Recovery complete under Ronnie authorization message '
                                                 '9f715e9539a04004ab38912f3c389287. Original ended-owner '
                                                 'task tdp-readiness-evidence-setup is superseded for '
                                                 'integration by this recovery record while its historical '
                                                 'evidence remains preserved. Runtime expressible-range '
                                                 'admission remains a separate follow-up. Documentation '
                                                 'impact: none.',
                                         'issue': '',
                                         'pr': 'https://github.com/ronnierosal/Re-Gear/pull/277',
                                         'rev': 4,
                                         'updated': '2026-09-21T02:14:51+00:00'},
 'auto-tdp-suspend-integration-319': {'id': 'auto-tdp-suspend-integration-319',
                                      'stream': 'primary-auto-tdp',
                                      'title': 'Independently accept and integrate Auto TDP suspend clock '
                                               'fix PR319',
                                      'owner': 'codex-auto-tdp-01a097b0-ac26-7e92-915c-b5c68d2a1b13',
                                      'state': 'done',
                                      'branch': 'codex/integration-auto-tdp-suspend-319',
                                      'paths': '[]',
                                      'dependencies': '[]',
                                      'evidence': 'PR319 merged ffd6c7a736ef5263e94eadaec1a3cabb5fc76d04. '
                                                  'Accepted final head77d6b96/base15cdffe and combined '
                                                  'cb26e43 all have '
                                                  'tree2225df8065404d741533cf0a9b5b782da768a673; merged tree '
                                                  'independently matched. Backend3068 OK/101 skips; '
                                                  'frontend637 pass/1 existing skip; golden29/29; '
                                                  'build,typecheck,architecture,compileall,package,diff/preflight '
                                                  'pass. Final-head foundation + privileged CI pass. '
                                                  'Independent reviewer /root/review319 accepted exact '
                                                  'refreshed head. PR evidence '
                                                  'https://github.com/ronnierosal/Re-Gear/pull/319#issuecomment-5655053391.',
                                      'note': 'Integration acceptance complete; Claude retains task record '
                                              'and was sent exact merge evidence for closeout. No '
                                              'implementation rewriting or source-tree changes during final '
                                              'branch refresh; all source trees matched. Rollback: new '
                                              'reviewed revert of two-file change (restores known suspend '
                                              'blindness); no deployed artifact changed. BOOTTIME fallback '
                                              'remains suspend-blind when unavailable. Post-merge CI tracked '
                                              'separately; no hardware/install/release. Next: owner closes '
                                              'lifecycle record and continues authorized performance '
                                              'feasibility; #277 recovery still separate.\n'
                                              'Documentation impact: none',
                                      'issue': '',
                                      'pr': 'https://github.com/ronnierosal/Re-Gear/pull/319',
                                      'rev': 3,
                                      'updated': '2026-09-13T18:02:11+00:00'},
 'tdp-runtime-expressible-range-admission': {'id': 'tdp-runtime-expressible-range-admission',
                                             'stream': 'auto-tdp',
                                             'title': 'P0: Reject unrepresentable Auto TDP ranges before '
                                                      'starting a worker',
                                             'owner': None,
                                             'state': 'todo',
                                             'branch': 'claude/tdp-runtime-expressible-range-admission',
                                             'paths': '["backend/regear/delivery/tdp_runtime.py", '
                                                      '"tests/test_tdp_auto_lifecycle.py", '
                                                      '"tests/test_tdp_runtime.py"]',
                                             'dependencies': '["tdp-readiness-evidence-setup"]',
                                             'evidence': '',
                                             'note': 'Distinct follow-up to diagnostic-only PR277, not a '
                                                     'replacement. Current da60e212 start_auto admits via '
                                                     'sustained bounds; a narrower boost ceiling is rejected '
                                                     'only at session tick. Scope: smallest runtime '
                                                     'admission fix with successful representable startup '
                                                     'preserved. First reproduce through real start_auto '
                                                     'using existing fixtures: sustained max30/boost '
                                                     'max25/request max30 should not start worker; valid '
                                                     'max25 should start with unchanged settling. Test empty '
                                                     'expressible intersection, differing boost minima, '
                                                     'changed bounds between readiness/start, current limit '
                                                     'inclusion, Stop and manual takeover. Do not add '
                                                     'retries, delays, confirmation or a second writer. Keep '
                                                     'existing final dispatch validation and pending journal '
                                                     'protections. Proposed assignee Claude Auto TDP lead '
                                                     'after readiness closure. Public minimum/maximum '
                                                     'payload semantics are shared with UI: any change to '
                                                     'that schema/meaning waits for UI primary agreement; '
                                                     'prefer an internal admission fix if sufficient. No '
                                                     'main.py/UI/eGPU edits without agreed overlap. Primary '
                                                     'Auto TDP is intended final driver; shared contracts '
                                                     'require same-candidate UI acceptance before '
                                                     'integration. Focused tests during iteration; full '
                                                     'backend/architecture/compile/golden/preflight/final-head '
                                                     'CI at integration. Return exact head/base, '
                                                     'failure-before/pass-after, preserved successful path '
                                                     'and documentation impact. No install/device/release. '
                                                     'Unclaimed; design/reproducer may be prepared, '
                                                     'implementation waits for dependency and interface '
                                                     'decision.\n'
                                                     'Documentation impact: none',
                                             'issue': '',
                                             'pr': '',
                                             'rev': 1,
                                             'updated': '2026-09-13T14:44:37+00:00'}}
APPROVED_DIGESTS = {
    'tdp-readiness-evidence-setup': 'c4c1f37b712d211c13e3fb79ff7b18d7f93e70acef8d1a30740e6e2577dce5cd',
    'tdp-lifecycle-gap-verification': 'de93c3a0e209a87a09e159e1d368289aea2199522951f19bde30a5d2172aeeb5',
    'tdp-readiness-evidence-recovery-277': '4b0f201cf28590731d762642fad8fbd38fa5a065d29589ab17f556e94a59116d',
    'auto-tdp-suspend-integration-319': 'fbeba200f43e861e61a1a20d20506e861f09be12aed4eb933559eec81188e3dc',
    'tdp-runtime-expressible-range-admission': '161e34c5bbea86d7b59176aa9542cdf02a2ffaed177d3aba3f790a0e6944ad5f',
}
CLOSEOUT_EVIDENCE = {
    'tdp-readiness-evidence-setup': 'Approved maintainer closeout: PR277 exact head cc802b76fc0d5beaf5e19ce0c9ba766c4f251cae / base c75ff5ae6050d2f068d3e58ecd19f24bfefc3ea1 / merge 1ff4de5f43d8bab2defa20739c2d69f855087d88 passed recorded software, independent-review, and post-merge checks. Runtime expressible-range admission remains separate and incomplete. No install, device, or hardware claim.',
    'tdp-lifecycle-gap-verification': 'Approved maintainer closeout: PR319 exact head 77d6b96e1c33d5a00075d76ee57eeca4757df0bb / base 15cdffeb3c314c7209c26975673794ebaef86103 / merge ffd6c7a736ef5263e94eadaec1a3cabb5fc76d04 passed recorded software, independent-review, and post-merge checks. CLOCK_BOOTTIME fallback remains suspend-blind where unavailable; real SteamOS suspend remains unproven. No hardware-validation claim.',
}


class Conflict(ValueError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}', value):
        raise ValueError('Use a 1-100 character ID with letters, digits, dots, hyphens or underscores')
    return value


def text(value, label='text', maximum=12000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f'{label} must be nonempty text, at most {maximum} characters')
    return value.strip()


def scope_paths(values):
    if not isinstance(values, list) or len(values) > 100:
        raise ValueError('paths must be a list of at most 100 repository-relative paths')
    result = []
    for value in values:
        value = text(value, 'path', 500).replace('\\', '/').rstrip('/')
        if value.startswith('/') or ':' in value or any(x in ('', '.', '..') for x in value.split('/')) or '*' in value:
            raise ValueError('Claim exact repository-relative paths or directories, without wildcards or traversal')
        result.append(value.casefold())
    return sorted(set(result))


def overlaps(left, right):
    return any(a == b or a.startswith(b + '/') or b.startswith(a + '/') for a in left for b in right)


class Hub:
    def __init__(self, path=DEFAULT_DB):
        if path is None:
            raise ValueError('Use --db with the shared workspace agent-hub/data/hub.sqlite3')
        self.path = Path(path)

    @contextmanager
    def connection(self, write=False):
        if not self.path.is_file():
            raise ValueError('Hub is not initialized; run init first')
        db = sqlite3.connect(str(self.path), timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def init(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(str(self.path), timeout=10)
        try:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                PRAGMA foreign_keys=ON;
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, agent TEXT NOT NULL, label TEXT NOT NULL,
                    worktree TEXT NOT NULL, created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS streams (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL,
                    owner TEXT REFERENCES sessions(id), rev INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, stream TEXT NOT NULL REFERENCES streams(id),
                    title TEXT NOT NULL, owner TEXT REFERENCES sessions(id),
                    state TEXT NOT NULL, branch TEXT NOT NULL, paths TEXT NOT NULL,
                    dependencies TEXT NOT NULL, evidence TEXT NOT NULL, note TEXT NOT NULL,
                    issue TEXT NOT NULL, pr TEXT NOT NULL, rev INTEGER NOT NULL DEFAULT 1,
                    updated TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY, sender TEXT NOT NULL REFERENCES sessions(id),
                    recipient TEXT REFERENCES sessions(id), stream TEXT NOT NULL REFERENCES streams(id),
                    subject TEXT NOT NULL, body TEXT NOT NULL,
                    reply_to TEXT REFERENCES messages(id), created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS receipts (
                    message TEXT NOT NULL REFERENCES messages(id),
                    session TEXT NOT NULL REFERENCES sessions(id),
                    state TEXT NOT NULL, updated TEXT NOT NULL,
                    PRIMARY KEY(message, session));
                CREATE TABLE IF NOT EXISTS transfers (
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL, target TEXT NOT NULL,
                    sender TEXT NOT NULL REFERENCES sessions(id),
                    recipient TEXT NOT NULL REFERENCES sessions(id),
                    expected_rev INTEGER NOT NULL, state TEXT NOT NULL, note TEXT NOT NULL,
                    created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, actor TEXT NOT NULL,
                    action TEXT NOT NULL, target TEXT NOT NULL, detail TEXT NOT NULL,
                    created TEXT NOT NULL);
            ''')
            db.executemany('INSERT OR IGNORE INTO streams(id,title) VALUES (?,?)', [
                ('egpu', 'eGPU connection and release'), ('auto-tdp', 'Auto TDP'),
                ('quick-access', 'Quick Access'), ('documentation', 'Documentation'),
                ('coordination', 'Agent coordination')])
            db.commit()
        finally:
            db.close()
        return {'database': str(self.path), 'initialized': True}

    @staticmethod
    def row(db, table, key):
        # Table names are internal constants, never user input.
        result = db.execute(f'SELECT * FROM {table} WHERE id=?', (key,)).fetchone()
        if result is None:
            raise ValueError(f'Unknown {table} ID: {key}')
        return dict(result)

    @staticmethod
    def revision(row, expected):
        if type(expected) is not int or row['rev'] != expected:
            raise Conflict(f'Stale revision: expected {expected}, current {row["rev"]}; reread before retrying')

    @staticmethod
    def event(db, actor, action, target, detail):
        db.execute('INSERT INTO events(actor,action,target,detail,created) VALUES (?,?,?,?,?)',
                   (actor, action, target, json.dumps(detail, ensure_ascii=False), now()))

    @staticmethod
    def _digest(row):
        payload = json.dumps(dict(row), sort_keys=True, separators=(',', ':'),
                             ensure_ascii=False).encode('utf-8')
        return hashlib.sha256(payload).hexdigest()

    def _maintenance_actor(self, db, actor):
        if actor != MAINTAINER:
            raise Conflict('This compiled maintenance operation is restricted to its designated maintainer')
        self.row(db, 'sessions', actor)
        task = self.row(db, 'tasks', MAINTENANCE_TASK)
        if self._digest(task) != MAINTENANCE_ASSIGNMENT_DIGEST:
            raise Conflict('The canonical maintenance assignment no longer matches its approved binding')

    @staticmethod
    def _execution_authorization(reference, operation):
        if not reference:
            raise Conflict(f'{operation} is disabled until its separate invocation approval is compiled')
        return reference

    @staticmethod
    def _approved_row(db, key):
        try:
            row = Hub.row(db, 'tasks', key)
        except ValueError as exc:
            raise Conflict(f'Approved preimage mismatch for {key}') from exc
        if row != APPROVED_TASKS[key] or Hub._digest(row) != APPROVED_DIGESTS[key]:
            raise Conflict(f'Approved preimage mismatch for {key}')
        return row

    def close_approved_auto_tdp_records(self, actor):
        """Atomically close the two frozen, accepted software records."""
        identifier(actor)
        targets = ('tdp-readiness-evidence-setup', 'tdp-lifecycle-gap-verification')
        supporting = ('tdp-readiness-evidence-recovery-277', 'auto-tdp-suspend-integration-319')
        with self.connection(True) as db:
            self._maintenance_actor(db, actor)
            authorization = self._execution_authorization(
                CLOSEOUT_EXECUTION_AUTHORIZATION, 'close_approved_auto_tdp_records')
            before = {key: self._approved_row(db, key) for key in targets}
            for key in supporting:
                row = self._approved_row(db, key)
                if row['state'] != 'done':
                    raise Conflict(f'Accepted integration record is incomplete: {key}')
            stamp = now()
            after_digests = {}
            for key in targets:
                evidence = before[key]['evidence'] + '\n' + CLOSEOUT_EVIDENCE[key]
                db.execute("UPDATE tasks SET state='done', evidence=?, rev=rev+1, updated=? WHERE id=?",
                           (evidence, stamp, key))
                after_digests[key] = self._digest(self.row(db, 'tasks', key))
            detail = {'authorization': authorization,
                      'before': {key: APPROVED_DIGESTS[key] for key in targets},
                      'after': after_digests}
            self.event(db, actor, 'close_approved_auto_tdp_records', ','.join(targets), detail)
            return {'tasks': [self.row(db, 'tasks', key) for key in targets], 'audit': detail}

    def amend_approved_auto_tdp_range_branch(self, actor):
        """Apply the frozen branch-only amendment for issue 497."""
        identifier(actor)
        key = 'tdp-runtime-expressible-range-admission'
        with self.connection(True) as db:
            self._maintenance_actor(db, actor)
            authorization = self._execution_authorization(
                RANGE_EXECUTION_AUTHORIZATION, 'amend_approved_auto_tdp_range_branch')
            before = self._approved_row(db, key)
            stamp = now()
            db.execute('UPDATE tasks SET branch=?, rev=rev+1, updated=? WHERE id=?',
                       (RANGE_NEW_BRANCH, stamp, key))
            result = self.row(db, 'tasks', key)
            detail = {'authorization': authorization,
                      'before': APPROVED_DIGESTS[key], 'after': self._digest(result)}
            self.event(db, actor, 'amend_approved_auto_tdp_range_branch', key, detail)
            return {'task': result, 'audit': detail}

    def register(self, session, agent, label, worktree):
        identifier(session)
        if agent not in ('codex', 'claude', 'human', 'other'):
            raise ValueError('agent must be codex, claude, human or other')
        values = (session, agent, text(label, 'label', 200), text(worktree, 'worktree', 1000))
        with self.connection(True) as db:
            existing = db.execute('SELECT * FROM sessions WHERE id=?', (session,)).fetchone()
            if existing:
                if tuple(existing[k] for k in ('id', 'agent', 'label', 'worktree')) != values:
                    raise Conflict('Session ID already registered with different metadata; use your own session ID')
            else:
                db.execute('INSERT INTO sessions VALUES (?,?,?,?,?)', (*values, now()))
                self.event(db, session, 'register', session, {'agent': agent})
            return self.row(db, 'sessions', session)

    def apply(self, actor, request):
        identifier(actor)
        if not isinstance(request, dict):
            raise ValueError('Request must be a JSON object')
        op = request.get('op')
        fields = {
            'create_stream': {'id', 'title'},
            'claim_stream': {'stream', 'rev'},
            'create_task': {'id', 'stream', 'title', 'branch', 'paths', 'dependencies', 'issue', 'pr', 'note'},
            'claim_task': {'id', 'rev'},
            'update_task': {'id', 'rev', 'state', 'note', 'evidence', 'issue', 'pr', 'paths'},
            'send': {'stream', 'to', 'subject', 'body', 'reply_to'},
            'receipt': {'id', 'state'},
            'offer_transfer': {'kind', 'id', 'rev', 'to', 'note'},
            'accept_transfer': {'id'},
            'cancel_transfer': {'id'},
        }
        if op not in fields or set(request) - fields[op] - {'op'}:
            raise ValueError('Unknown operation or unexpected request fields')
        with self.connection(True) as db:
            self.row(db, 'sessions', actor)
            result = self._apply(db, actor, op, request)
            self.event(db, actor, op, result.get('id', result.get('message', '')), request)
            return result

    def _ready(self, db, task):
        for dep in json.loads(task['dependencies']):
            if self.row(db, 'tasks', dep)['state'] != 'done':
                raise Conflict(f'Dependency {dep} is not done')
        for other in db.execute("SELECT * FROM tasks WHERE owner IS NOT NULL AND state NOT IN ('done','cancelled') AND id != ?", (task['id'],)):
            if overlaps(json.loads(task['paths']), json.loads(other['paths'])):
                raise Conflict(f'File scope overlaps task {other["id"]} owned by {other["owner"]}; sequence or split the work')

    def _apply(self, db, actor, op, r):
        if op == 'create_stream':
            key = identifier(r['id'])
            db.execute('INSERT INTO streams(id,title,owner) VALUES (?,?,?)',
                       (key, text(r['title'], 'title', 200), actor))
            return self.row(db, 'streams', key)
        if op == 'claim_stream':
            row = self.row(db, 'streams', r['stream'])
            self.revision(row, r['rev'])
            if row['owner'] is not None:
                raise Conflict('Workstream already owned; use an accepted transfer')
            db.execute('UPDATE streams SET owner=?, rev=rev+1 WHERE id=?', (actor, row['id']))
            return self.row(db, 'streams', row['id'])
        if op == 'create_task':
            stream = self.row(db, 'streams', r['stream'])
            key = identifier(r['id'])
            deps = r.get('dependencies', [])
            if not isinstance(deps, list) or len(deps) > 100:
                raise ValueError('dependencies must be a list of existing task IDs')
            for dep in deps:
                self.row(db, 'tasks', identifier(dep))
            # Existing-only, immutable dependencies cannot form a cycle.
            branch = text(r['branch'], 'branch', 250)
            if branch in ('main', 'master'):
                raise ValueError('Use a dedicated task branch, not shared main')
            db.execute('''INSERT INTO tasks(id,stream,title,state,branch,paths,dependencies,evidence,note,issue,pr,updated)
                          VALUES (?,?,?,'todo',?,?,?,'','','',?,?)''',
                       (key, stream['id'], text(r['title'], 'title', 300), branch,
                        json.dumps(scope_paths(r.get('paths', []))), json.dumps(sorted(set(deps))),
                        r.get('pr', ''), now()))
            for field in ('issue', 'pr', 'note'):
                if field in r:
                    db.execute(f'UPDATE tasks SET {field}=? WHERE id=?', (text(r[field], field), key))
            return self.row(db, 'tasks', key)
        if op == 'claim_task':
            row = self.row(db, 'tasks', r['id'])
            self.revision(row, r['rev'])
            if row['owner'] is not None or row['state'] != 'todo':
                raise Conflict('Task already claimed or not pending')
            self._ready(db, row)
            db.execute("UPDATE tasks SET owner=?, state='in_progress', rev=rev+1, updated=? WHERE id=?", (actor, now(), row['id']))
            return self.row(db, 'tasks', row['id'])
        if op == 'update_task':
            row = self.row(db, 'tasks', r['id'])
            self.revision(row, r['rev'])
            if row['owner'] != actor:
                raise Conflict('Only the task owner can update it')
            state = r.get('state', row['state'])
            allowed = {'todo': (), 'in_progress': ('in_progress', 'blocked', 'review', 'done', 'cancelled'),
                       'blocked': ('blocked', 'in_progress', 'cancelled'),
                       'review': ('review', 'in_progress', 'blocked', 'done', 'cancelled'),
                       'done': (), 'cancelled': ()}
            if state not in allowed[row['state']]:
                raise Conflict('Invalid task transition; finish active work with evidence')
            if 'paths' in r:
                if state != 'in_progress':
                    raise Conflict('Scope changes require in_progress and renewed verification')
                text(r.get('note'), 'scope change reason')
                row['paths'] = json.dumps(scope_paths(r['paths']))
            evidence = r.get('evidence', row['evidence'])
            note = r.get('note', row['note'])
            if state in ('review', 'done'):
                evidence = text(evidence, 'verification evidence')
            elif state == 'in_progress':
                evidence = ''  # Returning to work invalidates previous completion evidence.
            if state in ('blocked', 'cancelled'):
                note = text(note, 'blocker reason')
            if state in ('in_progress', 'review', 'done'):
                self._ready(db, row)
            for field, value in [('note', note), ('evidence', evidence), ('issue', r.get('issue', row['issue'])), ('pr', r.get('pr', row['pr']))]:
                if not isinstance(value, str) or len(value) > 12000:
                    raise ValueError(f'Invalid {field}')
            db.execute('UPDATE tasks SET state=?,note=?,evidence=?,issue=?,pr=?,paths=?,rev=rev+1,updated=? WHERE id=?',
                       (state, note, evidence, r.get('issue', row['issue']), r.get('pr', row['pr']), row['paths'], now(), row['id']))
            return self.row(db, 'tasks', row['id'])
        if op == 'send':
            self.row(db, 'streams', r['stream'])
            recipient = r.get('to')
            if recipient:
                self.row(db, 'sessions', recipient)
            reply_to = r.get('reply_to')
            if reply_to:
                parent = self.row(db, 'messages', reply_to)
                self._can_receive(db, actor, parent)
                if recipient != parent['sender'] or r['stream'] != parent['stream']:
                    raise ValueError('A reply must target the original sender in the same workstream')
            key = uuid.uuid4().hex
            db.execute('INSERT INTO messages VALUES (?,?,?,?,?,?,?,?)',
                       (key, actor, recipient, r['stream'], text(r['subject'], 'subject', 300), text(r['body'], 'body'), reply_to, now()))
            if reply_to:
                self._receipt(db, actor, reply_to, 'replied')
            return self.row(db, 'messages', key)
        if op == 'receipt':
            if r['state'] not in ('read', 'acknowledged'):
                raise ValueError('Receipt state is read or acknowledged; send a reply to mark replied')
            message = self.row(db, 'messages', r['id'])
            self._can_receive(db, actor, message)
            self._receipt(db, actor, message['id'], r['state'])
            return {'message': message['id'], 'session': actor, 'state': r['state']}
        if op == 'offer_transfer':
            table = {'stream': 'streams', 'task': 'tasks'}.get(r['kind'])
            if table is None:
                raise ValueError('Transfer kind is stream or task')
            row = self.row(db, table, r['id'])
            self.revision(row, r['rev'])
            if row['owner'] != actor or r['to'] == actor:
                raise Conflict('Only the current owner may offer ownership to another session')
            if table == 'tasks' and row['state'] in ('done', 'cancelled'):
                raise Conflict('Completed tasks cannot be transferred')
            self.row(db, 'sessions', r['to'])
            if db.execute("SELECT 1 FROM transfers WHERE kind=? AND target=? AND state='pending'", (r['kind'], row['id'])).fetchone():
                raise Conflict('A transfer is already pending; cancel it first')
            key = uuid.uuid4().hex
            db.execute('INSERT INTO transfers VALUES (?,?,?,?,?,?,?,?,?)',
                       (key, r['kind'], row['id'], actor, r['to'], row['rev'], 'pending', text(r['note'], 'handoff note'), now()))
            return self.row(db, 'transfers', key)
        if op in ('accept_transfer', 'cancel_transfer'):
            transfer = self.row(db, 'transfers', r['id'])
            expected_actor = transfer['recipient'] if op == 'accept_transfer' else transfer['sender']
            if transfer['state'] != 'pending' or expected_actor != actor:
                raise Conflict('Transfer is not pending for this session')
            if op == 'accept_transfer':
                table = {'stream': 'streams', 'task': 'tasks'}[transfer['kind']]
                row = self.row(db, table, transfer['target'])
                self.revision(row, transfer['expected_rev'])
                if row['owner'] != transfer['sender']:
                    raise Conflict('Owner changed since this offer')
                db.execute(f'UPDATE {table} SET owner=?,rev=rev+1 WHERE id=?', (actor, row['id']))
            state = 'accepted' if op == 'accept_transfer' else 'cancelled'
            db.execute('UPDATE transfers SET state=? WHERE id=?', (state, transfer['id']))
            return self.row(db, 'transfers', transfer['id'])
        raise ValueError('Unsupported operation')

    def _can_receive(self, db, actor, message):
        if message['sender'] == actor:
            raise Conflict('Sender cannot acknowledge their own message')
        if message['recipient']:
            if message['recipient'] != actor:
                raise Conflict('Message belongs to another recipient')
        elif self.row(db, 'streams', message['stream'])['owner'] != actor:
            raise Conflict('Only the current workstream lead can acknowledge its shared inbox')

    @staticmethod
    def _receipt(db, actor, message, state):
        prior = db.execute('SELECT state FROM receipts WHERE message=? AND session=?', (message, actor)).fetchone()
        ranks = {'read': 1, 'acknowledged': 2, 'replied': 3}
        if prior and ranks[state] < ranks[prior['state']]:
            raise Conflict('Receipt state cannot move backwards')
        db.execute('INSERT INTO receipts VALUES (?,?,?,?) ON CONFLICT(message,session) DO UPDATE SET state=excluded.state,updated=excluded.updated',
                   (message, actor, state, now()))

    def status(self):
        with self.connection() as db:
            return {table: [dict(row) for row in db.execute(f'SELECT * FROM {table} ORDER BY rowid')]
                    for table in ('streams', 'sessions', 'tasks', 'messages', 'receipts', 'transfers')}

    def inbox(self, actor):
        with self.connection() as db:
            self.row(db, 'sessions', actor)
            messages = [dict(row) for row in db.execute('''
                SELECT m.*, COALESCE(r.state,'unread') AS receipt FROM messages m
                LEFT JOIN receipts r ON r.message=m.id AND r.session=?
                JOIN streams s ON s.id=m.stream
                WHERE m.sender != ? AND (m.recipient=? OR (m.recipient IS NULL AND s.owner=?))
                ORDER BY m.created, m.rowid''', (actor, actor, actor, actor))]
            transfers = [dict(row) for row in db.execute("SELECT * FROM transfers WHERE recipient=? AND state='pending'", (actor,))]
            return {'messages': messages, 'pending_transfers': transfers, 'note': 'Reading this output does not create a read receipt.'}

    def history(self):
        with self.connection() as db:
            return [dict(row) for row in db.execute('SELECT * FROM events ORDER BY seq DESC LIMIT 100')]

    def snapshot(self):
        """Portable, read-only text for humans and voice handoffs, not a claim store."""
        data = self.status()
        lines = ['Re-Gear coordination snapshot: ' + now(),
                 'Refresh from the shared hub before acting; this is not a live claim store.']
        for task in data['tasks']:
            lines.extend([
                '', f"{task['id']} | {task['state']} | owner: {task['owner'] or 'available'} | rev {task['rev']}",
                task['title'], f"Stream: {task['stream']} | branch: {task['branch']}",
                'Scope paths: ' + task['paths'], 'Dependencies: ' + task['dependencies'],
                'Scope / acceptance / blocker / next: ' + (task['note'] or 'Not recorded'),
                'Evidence: ' + (task['evidence'] or 'Not recorded'),
                f"Issue / PR: {task['issue']} {task['pr']}"])
        lines.append('\nMessages and transfers: use status and your inbox; reading never acknowledges them.')
        return '\n'.join(lines) + '\n'

    def docs_queue(self):
        """Derive pending documentation reviews from existing tasks, without writes."""
        tasks = self.status()['tasks']
        pending = []
        for task in tasks:
            if task['state'] != 'done' or task['stream'] == 'documentation':
                continue
            impacts = re.findall(r'^Documentation impact:[ \t]*(.*)$', task['note'], re.MULTILINE | re.IGNORECASE)
            impact = impacts[0].strip().casefold() if len(impacts) == 1 else 'unassessed'
            if impact not in ('none', 'readme', 'wiki', 'discussion', 'multiple'):
                impact = 'unassessed'
            if impact == 'none':
                continue
            reviews = [review for review in tasks
                       if review['stream'] == 'documentation'
                       and task['id'] in json.loads(review['dependencies'])
                       and ('Documentation review: ' + task['id']) in review['note'].splitlines()]
            if any(review['state'] == 'done' for review in reviews):
                continue
            pending.append({'task': task, 'documentation_impact': impact,
                            'reviews': reviews})
        return {'pending': pending,
                'note': 'Read-only review queue. Missing/invalid impact needs triage. Verify merged code and evidence before publishing.'}

    def export_html(self, destination):
        data = self.status()
        esc = lambda value: html.escape(str(value), quote=True)
        sections = []
        for stream in data['streams']:
            tasks = [t for t in data['tasks'] if t['stream'] == stream['id']]
            cards = ''.join('<article><b>' + esc(t['title']) + '</b><p>' + esc(t['state']) + ' · ' + esc(t['owner'] or 'unassigned') +
                            '</p><small>' + esc(t['id']) + ' · revision ' + str(t['rev']) + '</small><p>' + esc(t['note']) +
                            '</p><p>Branch: ' + esc(t['branch']) + '</p><p>Paths: ' + esc(', '.join(json.loads(t['paths'])) or 'No file claim') +
                            '</p><p>Dependencies: ' + esc(', '.join(json.loads(t['dependencies'])) or 'None') +
                            '</p><p>Issue / PR: ' + esc(t['issue']) + ' ' + esc(t['pr']) +
                            '</p><p>Evidence: ' + esc(t['evidence'] or 'not recorded') + '</p></article>' for t in tasks)
            messages = ''
            for m in data['messages']:
                if m['stream'] != stream['id']:
                    continue
                receipts = ', '.join(r['session'] + ': ' + r['state'] for r in data['receipts'] if r['message'] == m['id']) or 'No receipt recorded'
                messages += '<details><summary>' + esc(m['subject']) + '</summary><p>From ' + esc(m['sender']) + ' to ' + esc(m['recipient'] or 'workstream lead') + '</p><pre>' + esc(m['body']) + '</pre><p>' + esc(receipts) + '</p></details>'
            sections.append('<section><h2>' + esc(stream['title']) + '</h2><p>Lead: ' + esc(stream['owner'] or 'unassigned') + '</p>' + (cards or '<p>No tasks yet.</p>') + '<h3>Inbox</h3>' + (messages or '<p>No messages.</p>') + '</section>')
        transfers = ''.join('<article><b>' + esc(t['kind'] + ': ' + t['target']) + '</b><p>' + esc(t['sender']) + ' → ' + esc(t['recipient']) +
                            ' · ' + esc(t['state']) + '</p><p>' + esc(t['note']) + '</p></article>' for t in data['transfers'])
        sections.append('<section><h2>Ownership handoffs</h2>' + (transfers or '<p>No transfers yet.</p>') + '</section>')
        content = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'"><title>Re-Gear agent hub</title>
<style>body{font:16px system-ui;background:#101724;color:#edf3ff;max-width:1100px;margin:32px auto;padding:0 24px}h1{color:#8bd5ff}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:20px}section{background:#1b2637;padding:20px;border-radius:12px}article,details{background:#26354a;padding:12px;margin:10px 0;border-radius:8px}small{color:#b9cadf}pre{white-space:pre-wrap;overflow-wrap:anywhere}p{overflow-wrap:anywhere}</style>
<h1>Re-Gear agent hub</h1><p>Local coordination · no shared credentials</p><p>Read-only snapshot: ''' + esc(now()) + '''. Regenerate to refresh. Viewing this page does not mark messages read.</p><main>''' + ''.join(sections) + '</main></html>'
        destination = Path(destination)
        if destination.resolve() == self.path.resolve():
            raise ValueError('Cannot overwrite the database')
        # A dashboard is a disposable view. Never overwrite another kind of file.
        if destination.suffix.lower() != '.html':
            raise ValueError('Dashboard destination must end in .html')
        destination.write_text(content, encoding='utf-8')
        return {'dashboard': str(destination)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=DEFAULT_DB)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('init')
    sub.add_parser('status')
    sub.add_parser('history')
    sub.add_parser('snapshot')
    sub.add_parser('docs-queue')
    closeout = sub.add_parser('close-approved-auto-tdp-records')
    closeout.add_argument('--session', required=True)
    amend = sub.add_parser('amend-approved-auto-tdp-range-branch')
    amend.add_argument('--session', required=True)
    register = sub.add_parser('register')
    register.add_argument('--session', required=True)
    register.add_argument('--agent', required=True)
    register.add_argument('--label', required=True)
    register.add_argument('--worktree', required=True)
    inbox = sub.add_parser('inbox')
    inbox.add_argument('--session', required=True)
    apply = sub.add_parser('apply')
    apply.add_argument('--session', required=True)
    apply.add_argument('--request', type=Path, help='JSON file; omit to read JSON from stdin')
    export = sub.add_parser('export')
    export.add_argument('--output', type=Path, default=Path(__file__).resolve().parent / 'dashboard.html')
    args = parser.parse_args(argv)
    try:
        hub = Hub(args.db)
        if args.command == 'init': result = hub.init()
        elif args.command == 'status': result = hub.status()
        elif args.command == 'history': result = hub.history()
        elif args.command == 'docs-queue': result = hub.docs_queue()
        elif args.command == 'close-approved-auto-tdp-records': result = hub.close_approved_auto_tdp_records(args.session)
        elif args.command == 'amend-approved-auto-tdp-range-branch': result = hub.amend_approved_auto_tdp_range_branch(args.session)
        elif args.command == 'snapshot':
            print(hub.snapshot(), end='')
            return 0
        elif args.command == 'register': result = hub.register(args.session, args.agent, args.label, args.worktree)
        elif args.command == 'inbox': result = hub.inbox(args.session)
        elif args.command == 'export': result = hub.export_html(args.output)
        else:
            payload = args.request.read_text(encoding='utf-8-sig') if args.request else sys.stdin.read()
            result = hub.apply(args.session, json.loads(payload))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, KeyError, TypeError, OSError, sqlite3.Error) as exc:
        print(json.dumps({'error': str(exc), 'type': type(exc).__name__}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
