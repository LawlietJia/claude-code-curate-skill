"""Record through the public CLI using isolated files, including interrupted retries."""
import datetime as dt
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'curate_check.py'


class RecordTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.ledger = self.root / 'events.jsonl'
        self.event = self.root / 'event.json'
        self.input = self.root / 'input.json'
        self.draft = dict(project=str(self.root), mode='quick', action='merge',
                          target=['memory/topic.md'], detail='保留条件，修正 "旧结论"\n第二行',
                          verification='已核对用户决定与正文差异')
        self.write_input(self.draft)

    def write_input(self, draft):
        self.input.write_text(json.dumps(draft, ensure_ascii=False), encoding='utf-8')

    def cli(self, *args, code=0):
        result = subprocess.run([sys.executable, '-B', str(SCRIPT), *map(str, args)],
                                text=True, capture_output=True, timeout=10, cwd=self.root)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        body = json.loads(result.stdout)
        self.assertEqual(body['ok'], code == 0)
        return body

    def record(self, *args, code=0, event=None):
        return self.cli('record', '--ledger', self.ledger, '--event', event or self.event,
                        *args, code=code)

    def rows(self):
        return [json.loads(line) for line in self.ledger.read_text().splitlines()]

    def test_generates_valid_event_and_retries_without_new_identity(self):
        before = dt.datetime.now(dt.timezone.utc)
        first = self.record('--input', self.input)
        saved = self.event.read_bytes()
        event = json.loads(saved)
        self.assertTrue(first['appended'])
        self.assertEqual(first['event_id'], event['event_id'])
        self.assertEqual(first['run_id'], event['run_id'])
        self.assertEqual(first['event_file'], str(self.event))
        uuid.UUID(event['run_id'])
        self.assertEqual(event['event_id'], event['run_id'] + ':1')
        self.assertEqual(event['schema_version'], 3)
        self.assertEqual(event['detail'], self.draft['detail'])
        self.assertLessEqual(before, dt.datetime.fromisoformat(event['ts']))
        self.assertLessEqual(dt.datetime.fromisoformat(event['ts']), dt.datetime.now(dt.timezone.utc))
        self.assertEqual(stat.S_IMODE(self.event.stat().st_mode), 0o600)
        for args in [(), ('--input', self.input)]:
            repeated = self.record(*args)
            self.assertFalse(repeated['appended'])
            self.assertEqual(repeated['event_id'], first['event_id'])
            self.assertEqual(self.event.read_bytes(), saved)
        self.assertEqual(len(self.rows()), 1)
        self.cli('validate', '--ledger', self.ledger)

    def test_multiple_events_share_run_and_reject_changed_retry_parameters(self):
        first = self.record('--input', self.input)
        second = self.record('--input', self.input, '--run-id', first['run_id'],
                             '--sequence', '2', event=self.root / 'second.json')
        self.assertEqual(second['event_id'], first['run_id'] + ':2')
        saved = self.event.read_bytes()
        original = self.ledger.read_bytes()
        for args in [('--run-id', 'another'), ('--sequence', '3')]:
            self.record(*args, code=1)
        self.write_input(dict(self.draft, detail='Changed result'))
        self.record('--input', self.input, code=1)
        self.assertEqual(self.event.read_bytes(), saved)
        self.assertEqual(self.ledger.read_bytes(), original)

    def test_bad_business_inputs_never_create_event_or_ledger(self):
        examples = [dict(ts='2026-10-25T16:00:00+08:00', type='action', scope='demo',
                         title='cleanup', targets=['topic.md'], changes=['x']),
                    dict(ts='2026-10-31T13:05:00+08:00', action='curate.quick',
                         project=str(self.root), task='cleanup', changes=['x'], reviewed_feedback=[]),
                    dict(ts='2026-11-01T20:23:12+0800', action='session-curate',
                         project=str(self.root), summary='cleanup', files_changed=['x']),
                    dict(self.draft, action='update'),
                    dict(schema_version=3, action='curate_quick', project=str(self.root),
                         ts='2026-11-04T15:09:18', changes=['x'], reviewed_feedback=[])]
        examples += [dict(self.draft, **change) for change in [
            dict(action='smart-review'), dict(action='retire-audit'), dict(reviewed_feedback=[]),
            dict(target='topic.md'), dict(verification=''), dict(cleaned=['x']),
            dict(schema_version=3), dict(event_id='invented'), dict(run_id='invented'),
            dict(ts='2026-11-06T00:00:00+00:00')]]
        for draft in examples:
            with self.subTest(draft=draft):
                self.write_input(draft)
                self.record('--input', self.input, code=1)
                self.assertFalse(self.event.exists())
                self.assertFalse(self.ledger.exists())
        self.write_input(dict(self.draft, action='update'))
        result = self.record('--input', self.input, code=1)
        self.assertIn('merge', result['error'])

    def test_invalid_run_parameters_do_not_create_files(self):
        for args in [('--sequence', '0'), ('--sequence', '-1'), ('--run-id', ' '),
                     ('--sequence', '2')]:
            with self.subTest(args=args):
                self.record('--input', self.input, *args, code=1)
                self.assertFalse(self.event.exists())
                self.assertFalse(self.ledger.exists())

    def test_new_event_rejects_relative_output_without_writing_files(self):
        for argument in ('cleanup', '{"action":"merge"}', 'event.json'):
            with self.subTest(argument=argument):
                result = self.record('--input', self.input, event=argument, code=1)
                self.assertIn('--event', result['error'])
                self.assertIn('absolute', result['error'])
                self.assertEqual(set(self.root.iterdir()), {self.input})

    def test_missing_event_directory_does_not_create_files(self):
        self.record('--input', self.input, event=self.root / 'absent' / 'event.json', code=1)
        self.assertEqual(set(self.root.iterdir()), {self.input})

    def test_existing_relative_event_can_still_be_retried(self):
        first = self.record('--input', self.input)
        saved = self.event.read_bytes()
        for args in [(), ('--input', self.input)]:
            retry = self.record(*args, event=self.event.name)
            self.assertFalse(retry['appended'])
            self.assertEqual(retry['event_id'], first['event_id'])
        self.assertEqual(self.event.read_bytes(), saved)
        self.assertEqual(len(self.rows()), 1)

    def test_missing_and_partial_event_are_not_regenerated(self):
        self.record(code=1)
        self.assertFalse(self.event.exists())
        self.event.write_bytes(b'{"schema_version":')
        self.record('--input', self.input, code=1)
        self.record(code=1)
        self.assertEqual(self.event.read_bytes(), b'{"schema_version":')
        self.assertFalse(self.ledger.exists())

    def test_append_failure_keeps_event_for_retry(self):
        self.ledger.write_bytes(b'{"broken":')
        self.record('--input', self.input, code=1)
        saved = self.event.read_bytes()
        self.assertEqual(self.ledger.read_bytes(), b'{"broken":')
        # Simulate a separately authorized repair in the isolated fixture.
        self.ledger.write_bytes(b'')
        result = self.record()
        self.assertTrue(result['appended'])
        self.assertEqual(self.event.read_bytes(), saved)
        self.assertEqual(self.rows(), [json.loads(saved)])

    def test_unknown_receipt_can_retry_using_only_saved_event(self):
        # The producer completes; the caller discards its acknowledgement.
        self.record('--input', self.input)
        saved_event = self.event.read_bytes()
        saved_ledger = self.ledger.read_bytes()
        self.input.unlink()
        result = self.record()
        self.assertFalse(result['appended'])
        self.assertEqual(self.event.read_bytes(), saved_event)
        self.assertEqual(self.ledger.read_bytes(), saved_ledger)

    def test_same_event_path_concurrent_calls_do_not_duplicate(self):
        command = [sys.executable, '-B', str(SCRIPT), 'record', '--ledger', str(self.ledger),
                   '--input', str(self.input), '--event', str(self.event)]
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: subprocess.run(command, capture_output=True,
                                                            text=True, timeout=10), range(4)))
        self.assertTrue(any(result.returncode == 0 for result in results))
        for result in results:
            self.assertIn(result.returncode, [0, 1], result.stderr)
        saved = self.event.read_bytes()
        self.record('--input', self.input)
        self.assertEqual(self.event.read_bytes(), saved)
        self.assertEqual(len(self.rows()), 1)

    def test_duplicate_feedback_returns_consumable_original_id(self):
        draft = dict(self.draft, action='feedback', feedback=dict(
            task_id='task-1', effect='corrected', evidence='User corrected the old conclusion.'))
        self.write_input(draft)
        first = self.record('--input', self.input)
        duplicate = self.record('--input', self.input, event=self.root / 'duplicate.json')
        self.assertFalse(duplicate['appended'])
        self.assertEqual(duplicate['event_id'], first['event_id'])
        self.write_input(dict(self.draft, reviewed_feedback=[duplicate['event_id']]))
        self.record('--input', self.input, '--run-id', duplicate['run_id'], '--sequence', '2',
                    event=self.root / 'review.json')
        pending = self.cli('feedback', '--ledger', self.ledger, '--project', self.root)
        self.assertEqual(pending['pending_count'], 0)
        self.assertEqual(len(self.rows()), 2)

    def test_invalid_feedback_reference_does_not_append(self):
        self.record('--input', self.input)
        before = self.ledger.read_bytes()
        self.write_input(dict(self.draft, reviewed_feedback=['unknown-feedback']))
        self.record('--input', self.input, event=self.root / 'bad-review.json', code=1)
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_refuses_path_aliases_links_and_nonregular_event(self):
        original = self.input.read_bytes()
        self.record('--input', self.input, event=self.input, code=1)
        self.record('--input', self.input, event=self.ledger, code=1)
        self.assertEqual(self.input.read_bytes(), original)
        outside = self.root / 'outside.json'
        outside.write_bytes(b'untouched')
        self.event.symlink_to(outside)
        self.record('--input', self.input, code=1)
        self.event.unlink()
        os.link(outside, self.event)
        self.record('--input', self.input, code=1)
        self.event.unlink()
        os.mkfifo(self.event)
        self.record('--input', self.input, code=1)
        self.assertEqual(outside.read_bytes(), b'untouched')
        self.assertFalse(self.ledger.exists())

    def test_case_alias_of_ledger_does_not_deadlock(self):
        probe = self.root / 'case-probe'
        probe.touch()
        if not (self.root / 'CASE-PROBE').exists():
            self.skipTest('Filesystem is case-sensitive')
        command = [sys.executable, '-B', str(SCRIPT), 'record',
                   '--ledger', str(self.root / 'EVENT.JSON'), '--event', str(self.event),
                   '--input', str(self.input)]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=2)
        except subprocess.TimeoutExpired:
            self.fail('Same-file ledger alias must be rejected without waiting for its own lock')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertFalse(json.loads(result.stdout)['ok'])
        saved = self.event.read_bytes()
        self.cli('record', '--ledger', self.root / 'EVENT.JSON', '--event', self.event, code=1)
        self.assertEqual(self.event.read_bytes(), saved)


if __name__ == '__main__':
    unittest.main()
