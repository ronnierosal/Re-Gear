"""Local coordination for cooperating agents. No network, credentials, or execution."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import html
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
