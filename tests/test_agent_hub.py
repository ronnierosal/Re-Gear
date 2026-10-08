"""Include the standalone hub regression suite in the repository's normal gate."""
import importlib.util
import copy
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest

HUB_DIR = Path(__file__).resolve().parents[1] / 'scripts' / 'agent_hub'
sys.path.insert(0, str(HUB_DIR))
import hub
sys.path.remove(str(HUB_DIR))


class CompiledMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / 'hub.sqlite3'
        self.store = hub.Hub(self.db)
        self.store.init()
        with self.store.connection(True) as db:
            sessions = {(row['owner'] or hub.MAINTAINER) for row in hub.APPROVED_TASKS.values()}
            sessions.add(hub.MAINTAINER)
            for session in sessions:
                db.execute('INSERT INTO sessions VALUES (?,?,?,?,?)',
                           (session, 'codex' if session.startswith('codex') else 'claude', session, 'fixture', hub.now()))
            for stream in {row['stream'] for row in hub.APPROVED_TASKS.values()}:
                db.execute('INSERT OR IGNORE INTO streams(id,title) VALUES (?,?)', (stream, stream))
            for row in hub.APPROVED_TASKS.values():
                self._insert(db, row)
            self._insert(db, hub.APPROVED_MAINTENANCE_ASSIGNMENT)

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def _insert(db, row):
        columns = tuple(row)
        db.execute(f"INSERT INTO tasks({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                   tuple(row[column] for column in columns))

    def rows_and_events(self):
        with self.store.connection() as db:
            rows = [dict(r) for r in db.execute('SELECT * FROM tasks ORDER BY id')]
            events = [dict(r) for r in db.execute('SELECT * FROM events ORDER BY seq')]
        return rows, events

    def test_closeout_exact_fixture_is_atomic_and_preserves_history(self):
        before = {key: copy.deepcopy(hub.APPROVED_TASKS[key]) for key in (
            'tdp-readiness-evidence-setup', 'tdp-lifecycle-gap-verification')}
        result = self.store.close_approved_auto_tdp_records(hub.MAINTAINER)
        self.assertEqual([(r['state'], r['rev']) for r in result['tasks']], [('done', 4), ('done', 7)])
        for row in result['tasks']:
            old = before[row['id']]
            for field in old:
                if field not in ('state', 'rev', 'updated', 'evidence'):
                    self.assertEqual(row[field], old[field])
            self.assertTrue(row['evidence'].startswith(old['evidence']))
            self.assertIn(hub.CLOSEOUT_EVIDENCE[row['id']], row['evidence'])
        self.assertEqual(self.rows_and_events()[1][-1]['action'], 'close_approved_auto_tdp_records')

    def test_closeout_rejects_every_mutated_field_without_any_mutation(self):
        key = 'tdp-lifecycle-gap-verification'
        for field in hub.APPROVED_TASKS[key]:
            with self.subTest(field=field):
                with self.store.connection(True) as db:
                    original = hub.APPROVED_TASKS[key][field]
                    changed = original + 'x' if isinstance(original, str) else original + 1
                    if field == 'stream':
                        db.execute('INSERT INTO streams(id,title) VALUES (?,?)', (changed, changed))
                    if field == 'owner':
                        db.execute('INSERT INTO sessions VALUES (?,?,?,?,?)', (changed, 'other', changed, 'fixture', hub.now()))
                    db.execute(f'UPDATE tasks SET {field}=? WHERE id=?', (changed, key))
                snapshot = self.rows_and_events()
                with self.assertRaises(hub.Conflict):
                    self.store.close_approved_auto_tdp_records(hub.MAINTAINER)
                self.assertEqual(self.rows_and_events(), snapshot)
                with self.store.connection(True) as db:
                    where_key = changed if field == 'id' else key
                    db.execute(f'UPDATE tasks SET {field}=? WHERE id=?', (original, where_key))

    def test_closeout_rejects_wrong_actor_support_record_and_replay(self):
        snapshot = self.rows_and_events()
        with self.assertRaises(hub.Conflict):
            self.store.close_approved_auto_tdp_records('claude-3e188980-234d-4e35-9a46-1b048630ba63')
        self.assertEqual(self.rows_and_events(), snapshot)
        with self.store.connection(True) as db:
            db.execute("UPDATE tasks SET evidence=evidence||'x' WHERE id='tdp-readiness-evidence-recovery-277'")
        changed = self.rows_and_events()
        with self.assertRaises(hub.Conflict):
            self.store.close_approved_auto_tdp_records(hub.MAINTAINER)
        self.assertEqual(self.rows_and_events(), changed)

    def test_operations_use_the_exact_compiled_conditional_consent(self):
        self.assertEqual(hub.CLOSEOUT_EXECUTION_AUTHORIZATION, hub.OPERATION_CONSENT)
        self.assertEqual(hub.RANGE_EXECUTION_AUTHORIZATION, hub.OPERATION_CONSENT)
        self.assertEqual(hub.OPERATION_CONSENT,
                         'https://github.com/ronnierosal/Re-Gear/issues/498#issuecomment-6069197182')
        self.assertEqual(hub.Hub._digest(hub.APPROVED_MAINTENANCE_ASSIGNMENT),
                         hub.MAINTENANCE_ASSIGNMENT_DIGEST)

    def test_closeout_concurrency_has_one_success_and_one_clean_failure(self):
        outcomes = []
        def run():
            try:
                self.store.close_approved_auto_tdp_records(hub.MAINTAINER)
                outcomes.append('ok')
            except hub.Conflict:
                outcomes.append('conflict')
        threads = [threading.Thread(target=run) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertCountEqual(outcomes, ['ok', 'conflict'])
        self.assertEqual(sum(e['action'] == 'close_approved_auto_tdp_records' for e in self.rows_and_events()[1]), 1)

    def test_range_amendment_changes_only_branch_revision_and_timestamp(self):
        old = copy.deepcopy(hub.APPROVED_TASKS['tdp-runtime-expressible-range-admission'])
        result = self.store.amend_approved_auto_tdp_range_branch(hub.MAINTAINER)['task']
        self.assertEqual(result['branch'], hub.RANGE_NEW_BRANCH)
        self.assertEqual(result['rev'], 2)
        for field in old:
            if field not in ('branch', 'rev', 'updated'):
                self.assertEqual(result[field], old[field])
        snapshot = self.rows_and_events()
        with self.assertRaises(hub.Conflict):
            self.store.amend_approved_auto_tdp_range_branch(hub.MAINTAINER)
        self.assertEqual(self.rows_and_events(), snapshot)

    def test_range_amendment_rejects_every_mutated_field_and_wrong_assignment(self):
        key = 'tdp-runtime-expressible-range-admission'
        for field in hub.APPROVED_TASKS[key]:
            with self.subTest(field=field):
                original = hub.APPROVED_TASKS[key][field]
                changed = original + 'x' if isinstance(original, str) else (1 if original is None else original + 1)
                with self.store.connection(True) as db:
                    if field == 'stream':
                        db.execute('INSERT INTO streams(id,title) VALUES (?,?)', (changed, changed))
                    if field == 'owner':
                        db.execute('INSERT INTO sessions VALUES (?,?,?,?,?)', (changed, 'other', changed, 'fixture', hub.now()))
                    db.execute(f'UPDATE tasks SET {field}=? WHERE id=?', (changed, key))
                snapshot = self.rows_and_events()
                with self.assertRaises(hub.Conflict):
                    self.store.amend_approved_auto_tdp_range_branch(hub.MAINTAINER)
                self.assertEqual(self.rows_and_events(), snapshot)
                with self.store.connection(True) as db:
                    where_key = changed if field == 'id' else key
                    db.execute(f'UPDATE tasks SET {field}=? WHERE id=?', (original, where_key))
        with self.store.connection(True) as db:
            db.execute("UPDATE tasks SET state='cancelled', rev=99, paths='[\"unrelated/path\"]' WHERE id=?",
                       (hub.MAINTENANCE_TASK,))
        snapshot = self.rows_and_events()
        for operation in (self.store.amend_approved_auto_tdp_range_branch,
                          self.store.close_approved_auto_tdp_records):
            with self.assertRaises(hub.Conflict):
                operation(hub.MAINTAINER)
            self.assertEqual(self.rows_and_events(), snapshot)

    def test_range_concurrency_and_operation_isolation(self):
        outcomes = []
        def run():
            try:
                self.store.amend_approved_auto_tdp_range_branch(hub.MAINTAINER)
                outcomes.append('ok')
            except hub.Conflict:
                outcomes.append('conflict')
        threads = [threading.Thread(target=run) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertCountEqual(outcomes, ['ok', 'conflict'])
        readiness = next(r for r in self.rows_and_events()[0] if r['id'] == 'tdp-readiness-evidence-setup')
        self.assertEqual(readiness, hub.APPROVED_TASKS[readiness['id']])

    def test_cli_round_trip_has_no_generic_target_or_authorization_arguments(self):
        script = HUB_DIR / 'hub.py'
        result = subprocess.run([sys.executable, str(script), '--db', str(self.db),
                                 'amend-approved-auto-tdp-range-branch', '--session', hub.MAINTAINER],
                                text=True, capture_output=True, check=True)
        self.assertEqual(json.loads(result.stdout)['task']['branch'], hub.RANGE_NEW_BRANCH)
        help_text = subprocess.run([sys.executable, str(script), '--db', str(self.db),
                                    'close-approved-auto-tdp-records', '--help'],
                                   text=True, capture_output=True, check=True).stdout
        for forbidden in ('--task', '--owner', '--state', '--authorization', '--force', '--delete', '--takeover'):
            self.assertNotIn(forbidden, help_text)


def load_tests(loader, tests, pattern):
    sys.path.insert(0, str(HUB_DIR))
    try:
        spec = importlib.util.spec_from_file_location('regear_hub_tests', HUB_DIR / 'test_hub.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        suite = loader.loadTestsFromModule(module)
        suite.addTests(loader.loadTestsFromTestCase(CompiledMaintenanceTests))
        return suite
    finally:
        sys.path.remove(str(HUB_DIR))
