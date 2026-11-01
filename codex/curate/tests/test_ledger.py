"""Bounded local tests; never use the real user ledger or native memory."""
import copy
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(os.environ.get('CURATE_TEST_ROOT') or Path(__file__).resolve().parents[1]).resolve()
SCRIPT = ROOT / 'scripts/curate_ledger.py'
spec = importlib.util.spec_from_file_location('curate_ledger', SCRIPT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='curate-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.ledger = self.root / 'state/events.jsonl'
        self.scope = {'kind': 'project', 'root': str(self.root / 'project')}

    def event(self, name='a', kind='issue'):
        e = dict(version=1, id=name, at='2026-10-30T10:00:00+08:00', scope=self.scope.copy(),
                 type=kind, targets=['docs/research.md#范围'], evidence='source: reviewed source paragraph 2')
        if kind == 'issue':
            e.update(issue_id=name, previous=None, goal='保留境外例外', advice='按来源修订',
                     remaining='仍缺境外说明', status='open', blocker='', recheck='', submissions=[])
        elif kind == 'feedback':
            e.update(task_id='real-task-1', effect='failed')
        else:
            e.update(detail='核对正文并修复入口', verification='读回并检查链接', reviewed_feedback=[])
        return e

    def update(self, old, name, **changes):
        new = copy.deepcopy(old)
        new.update(id=name, previous=old['id'], **changes)
        return new

    def pending(self):
        return m.select(m.read(self.ledger), self.scope, pending=True)

    def cli(self, *args, env=None):
        return subprocess.run([sys.executable, '-B', str(SCRIPT), *args],
                              capture_output=True, text=True, env=env)

    def test_readonly_absent_creates_nothing(self):
        for command in ('validate', 'pending', 'history'):
            args = [command, '--ledger', str(self.ledger)]
            if command != 'validate':
                args += ['--scope-kind', 'project', '--root', self.scope['root']]
            result = self.cli(*args)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.ledger.parent.exists())

    def test_same_id_retry_and_conflict(self):
        e = self.event()
        self.assertTrue(m.append(self.ledger, e)['appended'])
        before = self.ledger.read_bytes()
        self.assertFalse(m.append(self.ledger, e)['appended'])
        e['evidence'] = 'different evidence'
        with self.assertRaises(m.Invalid):
            m.append(self.ledger, e)
        self.assertEqual(before, self.ledger.read_bytes())

    def test_three_rounds_preserve_partial_and_new_issue(self):
        a, b = self.event('a'), self.event('b')
        m.append(self.ledger, a); m.append(self.ledger, b)
        m.append(self.ledger, self.update(a, 'a2', status='resolved', remaining='', evidence='document verified'))
        b2 = self.update(b, 'b2', remaining='只剩来源日期', evidence='正文条件已完成')
        m.append(self.ledger, b2); m.append(self.ledger, self.event('c'))
        self.assertEqual({e['issue_id'] for e in self.pending()}, {'b', 'c'})
        self.assertEqual(self.pending()[0]['remaining'], '只剩来源日期')

    def test_waiting_noop_does_not_grow(self):
        e = self.event()
        e.update(blocker='等待原生采纳', recheck='相关治理或有新证据时')
        m.append(self.ledger, e)
        for number in range(3):
            retry = self.update(e, f'noop-{number}', at='2026-10-31T10:00:00+08:00')
            self.assertFalse(m.append(self.ledger, retry)['appended'])
        self.assertEqual(len(m.read(self.ledger)), 1)
        self.assertEqual(len(self.pending()), 1)

    def test_replacement_is_not_resolution_and_stale_update_rejected(self):
        e = self.event(); m.append(self.ledger, e)
        new = self.update(e, 'b', advice='保留原结论，补适用条件', evidence='新增来源')
        m.append(self.ledger, new)
        self.assertEqual(self.pending()[0]['id'], 'b')
        with self.assertRaises(m.Invalid):
            m.append(self.ledger, self.update(e, 'stale', advice='旧方案'))

    def test_closed_and_reopened_target(self):
        for status in ('resolved', 'withdrawn', 'invalid'):
            with self.subTest(status=status):
                e = self.event(status); m.append(self.ledger, e)
                closed = self.update(e, status+'-close', status=status, remaining='', evidence='已核实的结束依据')
                m.append(self.ledger, closed)
                self.assertNotIn(e['issue_id'], {x['issue_id'] for x in self.pending()})
                reopened = self.update(closed, status+'-new', status='open', remaining='出现新反例', evidence='新任务结果')
                m.append(self.ledger, reopened)
                self.assertIn(e['issue_id'], {x['issue_id'] for x in self.pending()})

    def test_scopes_do_not_leak_or_reassign(self):
        e = self.event(); m.append(self.ledger, e)
        other = self.event('other'); other['scope']['root'] += '-other'
        m.append(self.ledger, other)
        user = self.event('user'); user['scope']['kind'] = 'user'
        m.append(self.ledger, user)
        self.assertEqual([x['id'] for x in self.pending()], ['a'])
        update = self.update(e, 'wrong-scope', scope=other['scope'])
        with self.assertRaises(m.Invalid):
            m.append(self.ledger, update)

    def test_feedback_dedup_and_new_counterexample(self):
        f = self.event('f', 'feedback'); m.append(self.ledger, f)
        retry = dict(f, id='retry', at='2026-10-31T10:00:00+08:00')
        self.assertEqual(m.append(self.ledger, retry), {'appended': False, 'id': 'f'})
        m.append(self.ledger, dict(f, id='counterexample', effect='exception', evidence='new evidence'))
        self.assertEqual(len(self.pending()), 2)
        self.assertEqual(len({x['task_id'] for x in self.pending()}), 1)

    def test_feedback_review_does_not_close_issue(self):
        m.append(self.ledger, self.event())
        f = self.event('f', 'feedback'); m.append(self.ledger, f)
        a = self.event('action', 'action'); a['reviewed_feedback'] = ['f']
        m.append(self.ledger, a)
        self.assertEqual([x['id'] for x in self.pending()], ['a'])

    def test_review_requires_existing_same_scope_target(self):
        m.append(self.ledger, self.event('f', 'feedback'))
        for change in ({'reviewed_feedback': ['missing']}, {'targets': ['another.md']},
                       {'scope': {'kind': 'user', 'root': self.scope['root']}}):
            a = self.event('act', 'action'); a['reviewed_feedback'] = ['f']; a.update(change)
            with self.subTest(change=change), self.assertRaises(m.Invalid):
                m.append(self.ledger, a)
        self.assertEqual(len(m.read(self.ledger)), 1)

    def test_submission_recovery_records_existing_file_only(self):
        note = self.root / 'existing-note.md'; note.write_text('fixture correction')
        submission = {'path': str(note), 'sha256': hashlib.sha256(note.read_bytes()).hexdigest()}
        e = self.event(); e['submissions'] = [submission]
        m.append(self.ledger, e)
        self.assertEqual(note.read_text(), 'fixture correction')
        self.assertEqual(self.pending()[0]['status'], 'open')
        bad = self.update(e, 'drop', submissions=[], evidence='changed approach')
        with self.assertRaises(m.Invalid):
            m.append(self.ledger, bad)

    def test_corruption_and_incomplete_tail_preserved(self):
        for raw in ('{broken}\n', json.dumps(self.event()), '\n'):
            self.ledger.parent.mkdir(exist_ok=True)
            self.ledger.write_text(raw)
            before = self.ledger.read_bytes()
            with self.subTest(raw=raw), self.assertRaises((m.Invalid, ValueError)):
                m.append(self.ledger, self.event('next'))
            self.assertEqual(self.ledger.read_bytes(), before)

    def test_invalid_fields_do_not_create_ledger(self):
        for changes in ({'status': 'pass'}, {'status': 'resolved'}, {'version': True},
                        {'at': '2026-10-30T10:00:00'}, {'unrecognized': True},
                        {'blocker': 'wait'}, {'evidence': ''}):
            e = self.event(); e.update(changes)
            with self.subTest(changes=changes), self.assertRaises((m.Invalid, ValueError)):
                m.append(self.ledger, e)
            self.assertFalse(self.ledger.exists())
        with self.assertRaises(m.Invalid):
            m.parse('{"id":"one","id":"two"}')

    def test_symlink_and_hardlink_refused_without_target_changes(self):
        target = self.root / 'target'; target.write_text('protected')
        self.ledger.parent.mkdir()
        self.ledger.symlink_to(target)
        with self.assertRaises(m.Invalid): m.append(self.ledger, self.event())
        self.ledger.unlink()
        os.link(target, self.ledger)
        with self.assertRaises(m.Invalid): m.append(self.ledger, self.event())
        self.assertEqual(target.read_text(), 'protected')

    def test_parent_symlink_and_memory_destination_refused(self):
        real = self.root / 'real'; real.mkdir()
        link = self.root / 'link'; link.symlink_to(real, target_is_directory=True)
        with self.assertRaises(m.Invalid): m.append(link / 'events.jsonl', self.event())
        with patch.object(m, 'home', return_value=self.root):
            with self.assertRaises(m.Invalid): m.append(self.root / 'memories/events.jsonl', self.event())
        self.assertFalse((self.root / 'memories').exists())

    def test_lock_contention_fails_promptly_without_writing(self):
        self.ledger.parent.mkdir()
        payload = self.root / 'event.json'; payload.write_text(json.dumps(self.event()))
        fd = os.open(self.ledger.parent, os.O_RDONLY)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            result = self.cli('append', '--ledger', str(self.ledger), '--event', str(payload))
            self.assertEqual(result.returncode, 1)
            self.assertFalse(self.ledger.exists())
        finally:
            os.close(fd)

    def test_concurrent_same_event_is_idempotent(self):
        payload = self.root / 'event.json'; payload.write_text(json.dumps(self.event()))
        command = [sys.executable, '-B', str(SCRIPT), 'append', '--ledger', str(self.ledger), '--event', str(payload)]
        jobs = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(3)]
        for job in jobs:
            stdout, stderr = job.communicate(timeout=10)
            self.assertIn(job.returncode, (0, 1), stderr)
            if job.returncode:
                self.assertIn('temporarily unavailable', stderr.lower())
        self.assertFalse(m.append(self.ledger, self.event())['appended'])
        self.assertEqual(len(m.read(self.ledger)), 1)

    def test_pagination_and_readonly_existing(self):
        for number in range(23): m.append(self.ledger, self.event(str(number)))
        before = self.ledger.read_bytes()
        events = self.pending()
        first, second = m.page(events), m.page(events, offset=20)
        self.assertEqual((first['total'], first['next_offset'], len(second['items'])), (23, 20, 3))
        self.assertIsNone(second['next_offset'])
        self.assertEqual(self.ledger.read_bytes(), before)
        with self.assertRaises(m.Invalid): m.page(events, limit=0)

    def test_custom_codex_home_readonly(self):
        env = dict(os.environ, CODEX_HOME=str(self.root / 'profile'))
        result = self.cli('validate', env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['ledger'], str(self.root / 'profile/curate/events.jsonl'))
        self.assertFalse((self.root / 'profile').exists())


if __name__ == '__main__':
    print(f'Testing actual skill: {ROOT}', flush=True)
    unittest.main(verbosity=2)
