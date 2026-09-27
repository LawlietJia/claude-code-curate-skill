import json
import unittest
import test_curate_check as old

class LearningTests(unittest.TestCase):
    setUp=old.CurateCheckTests.setUp
    tearDown=old.CurateCheckTests.tearDown
    run_cli=old.CurateCheckTests.run_cli
    event=old.CurateCheckTests.event

    def feedback_event(self, **changes):
        data=dict(action='feedback',pattern_key='tool.render-auth',target=['memory/topic.md#auth'],
                  feedback=dict(task_id='task-42',effect='helped',evidence='Task-42 command output confirmed the auth retry worked.'))
        data.update(changes)
        return self.event(**data)

    def append_event(self,path,code=0):
        return self.run_cli('append','--ledger',self.root/'curate-events.v3.jsonl','--event',path,code=code)

    def test_scoped_history_includes_unknown_legacy_and_separate_current(self):
        legacy=self.root/'curate-history.jsonl'
        legacy.write_text(json.dumps(dict(pattern_key='tool:render:auth',detail='auth legacy'))+'\ninvalid\n'+json.dumps(dict(project='/unrelated/project',pattern_key='tool:render:auth',detail='auth elsewhere'))+'\n')
        before=legacy.read_bytes()
        self.append_event(self.event(pattern_key='tool.render-auth',detail='auth current'))
        r=self.run_cli('history','--assets',self.root,'--project',self.root,'--query','auth')
        self.assertEqual(r['total'],2)
        self.assertEqual({x['scope'] for x in r['matches']},{'project','unknown'})
        self.assertEqual(len(r['warnings']),1)
        self.assertEqual(legacy.read_bytes(),before)

    def test_history_pagination_does_not_claim_full_coverage(self):
        (self.root/'curate-history.jsonl').write_text('\n'.join(json.dumps(dict(pattern_key='tool:auth',detail='auth '+str(i))) for i in range(3))+'\n')
        r=self.run_cli('history','--assets',self.root,'--project',self.root,'--query','auth','--limit','1')
        self.assertEqual(r['total'],3);self.assertTrue(r['truncated']);self.assertEqual(r['next_offset'],1)

    def test_legacy_invalid_project_is_unknown_not_silently_excluded(self):
        (self.root/'curate-history.jsonl').write_text(''.join(json.dumps(dict(project=scope,pattern_key='tool:auth',detail='auth'))+'\n' for scope in ['', ' ', 'video-studio', 7]))
        r=self.run_cli('history','--assets',self.root,'--project',self.root,'--query','auth')
        self.assertEqual(r['total'],4)
        self.assertTrue(all(row['scope']=='unknown' for row in r['matches']))
        self.assertEqual(len(r['warnings']),4)

    def test_new_key_control_and_exact_legacy_reuse(self):
        self.append_event(self.event(pattern_key='tool:novel:key'),code=1)
        (self.root/'curate-history.jsonl').write_text(json.dumps(dict(pattern_key='tool:render:auth'))+'\n')
        self.append_event(self.event(pattern_key='tool:render:auth'))
        self.append_event(self.event(event_id='next',pattern_key='tool.render-auth'))

    def test_feedback_retry_different_event_id_does_not_grow_ledger(self):
        self.append_event(self.feedback_event())
        r=self.append_event(self.feedback_event(event_id='different',run_id='different-run'))
        self.assertFalse(r['appended'])
        self.assertEqual(len((self.root/'curate-events.v3.jsonl').read_text().splitlines()),1)
        r=self.run_cli('feedback','--ledger',self.root/'curate-events.v3.jsonl','--project',self.root)
        self.assertEqual(r['pending_count'],1);self.assertEqual(r['summary'][0]['task_count'],1)

    def test_consumption_round_trip_leaves_no_pending(self):
        self.append_event(self.feedback_event())
        self.append_event(self.event(event_id='review-1',action='verify',target=['memory/topic.md#auth'],reviewed_feedback=['run-1:1']))
        r=self.run_cli('feedback','--ledger',self.root/'curate-events.v3.jsonl','--project',self.root)
        self.assertEqual(r['pending'],[]);self.assertEqual(r['pending_count'],0)
        self.assertEqual(r['summary'][0]['helped_tasks'],1)

    def test_invalid_acknowledgement_does_not_append(self):
        self.append_event(self.feedback_event());ledger=self.root/'curate-events.v3.jsonl';before=ledger.read_bytes()
        for changes in [dict(reviewed_feedback=['missing']),dict(reviewed_feedback=['run-1:1'],project='/other-project'),dict(reviewed_feedback=['run-1:1'],target=['unrelated.md'])]:
            self.append_event(self.event(event_id='bad-review',action='verify',**changes),code=1)
            self.assertEqual(ledger.read_bytes(),before)

    def test_reading_or_missing_evidence_is_not_feedback(self):
        for feedback in [dict(task_id='task',effect='read',evidence='Read file'),dict(task_id='task',effect='helped',evidence=''),dict(task_id='',effect='failed',evidence='error')]:
            self.append_event(self.feedback_event(feedback=feedback),code=1)
        self.assertFalse((self.root/'curate-events.v3.jsonl').exists())

    def test_conflicting_same_task_signals_are_not_success_votes(self):
        self.append_event(self.feedback_event())
        self.append_event(self.feedback_event(event_id='f2',feedback=dict(task_id='task-42',effect='exception',evidence='Same task showed auth retries only work with refreshed credentials.')))
        r=self.run_cli('feedback','--ledger',self.root/'curate-events.v3.jsonl','--project',self.root)
        self.assertEqual(r['summary'][0]['task_count'],1)
        self.assertEqual(r['summary'][0]['helped_tasks'],0)
        self.assertEqual(r['summary'][0]['review_tasks'],1)
        self.assertEqual(r['pending_count'],2)

    def test_other_project_feedback_excluded_and_empty_start_allowed(self):
        r=self.run_cli('feedback','--ledger',self.root/'curate-events.v3.jsonl','--project',self.root)
        self.assertEqual(r['pending_count'],0)
        self.append_event(self.feedback_event(project='/other-project'))
        r=self.run_cli('feedback','--ledger',self.root/'curate-events.v3.jsonl','--project',self.root)
        self.assertEqual(r['summary'],[])

    def test_feedback_pagination_and_new_actions(self):
        for n in range(2):
            self.append_event(self.feedback_event(event_id='fb-'+str(n),feedback=dict(task_id='task-'+str(n),effect='helped',evidence='Task execution verified auth.')))
        r=self.run_cli('feedback','--ledger',self.root/'curate-events.v3.jsonl','--project',self.root,'--limit','1')
        self.assertTrue(r['truncated']);self.assertEqual(r['pending_count'],2)
        for n,action in enumerate(['handoff','verify']):
            self.append_event(self.event(event_id='action-'+str(n),action=action))

    def test_retired_plugin_action_readable_but_not_newly_writable(self):
        event=json.loads(self.event(action='smart-review').read_text())
        ledger=self.root/'curate-events.v3.jsonl'
        ledger.write_text(json.dumps(event)+'\n');before=ledger.read_bytes()
        self.run_cli('validate','--ledger',ledger)
        self.append_event(self.event(event_id='new-plugin-event',action='smart-review'),code=1)
        self.assertEqual(ledger.read_bytes(),before)

if __name__=='__main__':unittest.main()
