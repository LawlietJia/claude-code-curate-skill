"""Behavioral tests of the file checker, not tests of an LLM's judgment."""
import json
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'curate_check.py'


class CurateCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.memory = self.root / 'memory'
        self.memory.mkdir()
        (self.memory / 'MEMORY.md').write_text('- [Topic](topic.md)\n')
        (self.memory / 'topic.md').write_text('# A valid topic\n')

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args, code=0):
        proc = subprocess.run([sys.executable, str(SCRIPT), *map(str,args)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, code, proc.stdout + proc.stderr)
        return json.loads(proc.stdout)

    def event(self, **changes):
        data = dict(schema_version=3, event_id='run-1:1', run_id='run-1',
                    ts='2026-09-26T12:00:00+08:00', project=str(self.root.resolve()),
                    mode='quick', action='merge', target=['memory/topic.md'],
                    detail='Merged an equivalent duplicate without losing conditions.',
                    verification='Checked content and all incoming links; later benefit unmeasured.')
        data.update(changes)
        p = self.root / ('event-' + str(len(list(self.root.glob('event-*.json')))) + '.json')
        p.write_text(json.dumps(data))
        return p

    def test_inspects_all_markdown_and_backlinks(self):
        (self.memory / 'tools.md').write_text('[obsolete](old.md)\n')
        result = self.run_cli('inspect', '--memory', self.memory, code=1)
        self.assertEqual(len(result['files']), 3)
        bad = [i for i in result['issues'] if i['type']=='broken_link']
        self.assertEqual([(i['file'],i['target']) for i in bad], [('tools.md','old.md')])

    def test_ignores_code_comments_and_remote_links(self):
        (self.memory / 'topic.md').write_text('`[example](absent.md)`\n```md\n[x](fake.md)\n```\n<!-- [x](hidden.md) -->\n[web](https://example.com/x)\n')
        result=self.run_cli('inspect','--memory',self.memory)
        self.assertFalse([i for i in result['issues'] if i['type']=='broken_link'])

    def test_reference_angle_escaped_and_parenthesis_destinations(self):
        (self.memory/'a (b).md').write_text('# Present\n')
        (self.memory/'topic.md').write_text('[a](<a (b).md>)\n[b](a%20(b).md)\n[c][ref]\n[ref]: a%20(b).md\n[x](missing.md "title")\n')
        result=self.run_cli('inspect','--memory',self.memory,code=1)
        bad=[i['target'] for i in result['issues'] if i['type']=='broken_link']
        self.assertEqual(bad,['missing.md'])

    def test_unknown_reference_and_wiki_syntax_are_not_silent(self):
        (self.memory/'topic.md').write_text('[x][not-defined]\n[[wiki-note]]\n')
        result=self.run_cli('inspect','--memory',self.memory)
        self.assertTrue(any(i['type']=='manual_link_review' for i in result['issues']))

    def test_missing_memory_or_index_is_error_without_creating_files(self):
        absent=self.root/'absent'
        self.run_cli('inspect','--memory',absent,code=1)
        self.assertFalse(absent.exists())
        (self.memory/'MEMORY.md').unlink()
        self.run_cli('inspect','--memory',self.memory,code=1)

    def test_chinese_utf8_soft_budget_does_not_equal_runtime_truncation(self):
        (self.memory/'MEMORY.md').write_text('中'*9000+'\n')
        r=self.run_cli('inspect','--memory',self.memory)
        self.assertGreater(r['index']['utf8_bytes'],25000)
        self.assertEqual(r['index']['utf16_units'],9000)
        self.assertFalse(r['index']['would_truncate'])

    def test_index_limit_applies_without_version_and_across_versions(self):
        for version in [None, '2.1.300', '3.0.0']:
            args=[] if version is None else ['--claude-version',version]
            for lines in [200,201]:
                with self.subTest(version=version,lines=lines):
                    (self.memory/'MEMORY.md').write_text('\n'.join('line '+str(i) for i in range(lines)))
                    r=self.run_cli('inspect','--memory',self.memory,*args,code=int(lines>200))
                    self.assertEqual(r['index']['would_truncate'],lines>200)
                    self.assertEqual(r['index']['version'],version)
                    self.assertFalse(any(i['type']=='runtime_limit_unverified' for i in r['issues']))

    def test_character_budget_is_version_independent(self):
        for text,over in [('a'*25000,False),('a'*25001,True),('😀'*12501,True)]:
            with self.subTest(length=len(text),over=over):
                (self.memory/'MEMORY.md').write_text(text)
                r=self.run_cli('inspect','--memory',self.memory,code=int(over))
                self.assertEqual(r['index']['would_truncate'],over)

    def test_snapshot_detects_change_add_delete_without_writing_memory(self):
        snap=self.root/'snapshot.json'
        before=(self.memory/'topic.md').read_bytes()
        self.run_cli('inspect','--memory',self.memory,'--snapshot',snap)
        self.run_cli('guard','--snapshot',snap)
        self.assertEqual((self.memory/'topic.md').read_bytes(),before)
        (self.memory/'new.md').write_text('# New')
        r=self.run_cli('guard','--snapshot',snap,code=1)
        self.assertIn('new.md',r['changed'])
        (self.memory/'new.md').unlink()
        (self.memory/'topic.md').unlink()
        r=self.run_cli('guard','--snapshot',snap,code=1)
        self.assertIn('topic.md',r['changed'])

    def test_symlink_memory_file_is_reported_without_reading_target(self):
        outside=self.root/'private.txt';outside.write_text('DO-NOT-READ')
        (self.memory/'escape.md').symlink_to(outside)
        r=self.run_cli('inspect','--memory',self.memory,code=1)
        self.assertTrue(any(i['type']=='symlink' for i in r['issues']))
        self.assertNotIn('DO-NOT-READ',json.dumps(r))

    def test_snapshot_refuses_overwriting_existing_file(self):
        snap=self.root/'snapshot.json';snap.write_text('preserve')
        self.run_cli('inspect','--memory',self.memory,'--snapshot',snap,code=1)
        self.assertEqual(snap.read_text(),'preserve')

    def test_append_idempotent_and_legacy_unchanged(self):
        legacy=self.root/'curate-history.jsonl';legacy.write_bytes(b'{"action":"repair"}\nnot-json\n')
        original=legacy.read_bytes();ledger=self.root/'curate-events.v3.jsonl';event=self.event()
        first=self.run_cli('append','--ledger',ledger,'--event',event)
        second=self.run_cli('append','--ledger',ledger,'--event',event)
        self.assertTrue(first['appended']);self.assertFalse(second['appended'])
        self.assertEqual(len(ledger.read_text().splitlines()),1)
        self.assertEqual(legacy.read_bytes(),original)
        self.run_cli('validate','--ledger',ledger)

    def test_invalid_new_fields_rejected_without_creating_ledger(self):
        ledger=self.root/'events.jsonl'
        for changes in [dict(action='repair'),dict(schema_version=2),dict(project='relative'),dict(ts='2026-09-26'),dict(strategy='verify'),dict(target=[]),dict(verification='')]:
            self.run_cli('append','--ledger',ledger,'--event',self.event(**changes),code=1)
            self.assertFalse(ledger.exists())

    def test_conflicting_identity_fails_without_second_append(self):
        ledger=self.root/'events.jsonl'
        self.run_cli('append','--ledger',ledger,'--event',self.event())
        self.run_cli('append','--ledger',ledger,'--event',self.event(detail='Different action'),code=1)
        self.assertEqual(len(ledger.read_text().splitlines()),1)

    def test_concurrent_retry_is_one_record(self):
        ledger=self.root/'events.jsonl';event=self.event()
        def call(_):
            return subprocess.run([sys.executable,str(SCRIPT),'append','--ledger',str(ledger),'--event',str(event)],capture_output=True,text=True)
        with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(call,range(4)))
        self.assertTrue(all(p.returncode==0 for p in results),str(results))
        self.assertEqual(len(ledger.read_text().splitlines()),1)

    def test_corrupt_current_ledger_is_not_appended_to(self):
        ledger=self.root/'events.jsonl';ledger.write_bytes(b'{"truncated":')
        self.run_cli('append','--ledger',ledger,'--event',self.event(),code=1)
        self.assertEqual(ledger.read_bytes(),b'{"truncated":')

    def test_append_refuses_symlink_ledger_and_parent(self):
        outside=self.root/'outside.jsonl';outside.write_text('')
        ledger=self.root/'events.jsonl';ledger.symlink_to(outside)
        self.run_cli('append','--ledger',ledger,'--event',self.event(),code=1)
        self.assertEqual(outside.read_text(),'')
        actual=self.root/'actual';actual.mkdir();link=self.root/'link';link.symlink_to(actual,target_is_directory=True)
        self.run_cli('append','--ledger',link/'events.jsonl','--event',self.event(),code=1)
        self.assertFalse((actual/'events.jsonl').exists())

    def test_guard_refuses_changed_root_ancestor(self):
        snap=self.root/'snapshot.json'
        self.run_cli('inspect','--memory',self.memory,'--snapshot',snap)
        relocated=self.root.with_name(self.root.name+'-moved')
        self.root.rename(relocated)
        self.root.symlink_to(relocated,target_is_directory=True)
        try:
            self.run_cli('guard','--snapshot',relocated/'snapshot.json',code=1)
        finally:
            self.root.unlink();relocated.rename(self.root)

    def test_nested_list_links_get_visible_manual_review(self):
        (self.memory/'topic.md').write_text('- parent\n    - [real](gone.md)\n')
        r=self.run_cli('inspect','--memory',self.memory)
        self.assertTrue(any(i['type']=='manual_link_review' and i['line']==2 for i in r['issues']))

    def test_unclosed_link_is_not_a_broken_destination(self):
        (self.memory/'topic.md').write_text('[example](missing.md\n')
        r=self.run_cli('inspect','--memory',self.memory)
        self.assertFalse(any(i['type']=='broken_link' for i in r['issues']))
        self.assertTrue(any(i['type']=='manual_link_review' for i in r['issues']))

    def test_invalid_link_title_needs_manual_review(self):
        (self.memory/'topic.md').write_text('[example](missing.md invalid title)\n')
        r=self.run_cli('inspect','--memory',self.memory)
        self.assertFalse(any(i['type']=='broken_link' for i in r['issues']))
        self.assertTrue(any(i['type']=='manual_link_review' for i in r['issues']))


if __name__=='__main__': unittest.main()
