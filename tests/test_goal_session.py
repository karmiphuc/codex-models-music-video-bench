"""Native goal protocol fixtures only: never start Codex or any model."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

from lab.goal_session import run_session


FAKE_SERVER = r'''
import json, pathlib, sys
mode, record_path = sys.argv[1:]
thread_id = 'fresh-thread'
goal = None
def send(value):
    print(json.dumps(value), flush=True)
def notify(method, params):
    send({'method':method, 'params':{'threadId':thread_id, **params}})
def reply(request, result):
    send({'id':request['id'], 'result':result})
for line in sys.stdin:
    request = json.loads(line)
    with open(record_path, 'a') as record:
        record.write(json.dumps(request)+'\n')
    method, params = request['method'], request.get('params',{})
    if method == 'initialize':
        reply(request, {'userAgent':'offline-test'})
    elif method == 'initialized':
        continue
    elif method == 'thread/start':
        reply(request, {'model':'wrong' if mode == 'wrong-model' else params['model'],
          'reasoningEffort':'wrong' if mode == 'wrong-effort' else params['config']['model_reasoning_effort'],
          'thread':{'id':thread_id,'ephemeral':False,'turns':[], 'parentThreadId':None,'forkedFromId':None}})
    elif method == 'thread/goal/set':
        if goal is None:
            goal = {'threadId':thread_id,'objective':params['objective'], 'status':'active',
                    'tokenBudget':params.get('tokenBudget'),'tokensUsed':0,'timeUsedSeconds':0}
        else:
            goal['status'] = params['status']
        reply(request, {'goal':goal})
    elif method == 'thread/goal/get':
        returned = dict(goal)
        if mode == 'wrong-goal':
            returned['objective'] = 'different task'
        reply(request, {'goal':returned})
    elif method == 'turn/start':
        reply(request, {'turn':{'id':'t1','status':'inProgress'}})
        notify('turn/started', {'turn':{'id':'t1','status':'inProgress'}})
        notify('thread/tokenUsage/updated', {'turnId':'t1', 'tokenUsage':{'total':{
            'inputTokens':10,'cachedInputTokens':2,'outputTokens':5,'totalTokens':15}}})
        notify('turn/completed', {'turn':{'id':'t1','status':'completed','error':None}})
        if mode == 'never-complete':
            continue
        # The server supplies its own second turn, without a second turn/start request.
        notify('turn/started', {'turn':{'id':'t2','status':'inProgress'}})
        notify('thread/tokenUsage/updated', {'turnId':'t2', 'tokenUsage':{'total':{
            'inputTokens':25,'cachedInputTokens':7,'outputTokens':12,'totalTokens':37}}})
        goal.update(status='complete', tokensUsed=37)
        notify('thread/goal/updated', {'turnId':'t2','goal':goal})
        notify('item/completed', {'turnId':'t2','item':{'type':'agentMessage','text':'Offline fixture done.'}})
        notify('turn/completed', {'turn':{'id':'t2','status':'failed' if mode == 'failed-turn' else 'completed','error':None}})
    elif method == 'turn/interrupt':
        reply(request, {})
    else:
        send({'id':request['id'],'error':{'code':-32601,'message':'unsupported fixture method'}})
'''


class GoalSessionTests(unittest.TestCase):
    def run_fixture(self, mode="complete", budget=500000, seconds=5):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        work = root / "work"
        work.mkdir()
        (work / "TASK.txt").write_text("Identical offline protocol fixture.\n", encoding="utf-8")
        server = root / "fake_server.py"
        server.write_text(FAKE_SERVER)
        record = root / "requests.jsonl"
        result = run_session(work, root / "result.json", root / "events.jsonl", "fixture-model", "high",
                             seconds, budget, [sys.executable, str(server), mode, str(record)])
        requests = [json.loads(line) for line in record.read_text().splitlines()]
        self.assertEqual(result, json.loads((root / "result.json").read_text()))
        return result, requests, root

    def test_fresh_native_goal_waits_for_automatic_continuation_and_uses_cumulative_usage(self):
        result, requests, root = self.run_fixture()
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["completed_turns"], 2)
        self.assertEqual(result["usage"]["input_tokens"], 25)
        self.assertEqual(result["usage"]["cached_input_tokens"], 7)
        self.assertEqual(result["goal"]["tokensUsed"], 37)
        self.assertEqual(result["final_message"], "Offline fixture done.")
        self.assertTrue(result["model_identity_verified"])
        methods = [request["method"] for request in requests]
        self.assertEqual(methods, ["initialize", "initialized", "thread/start", "thread/goal/set",
                                   "thread/goal/get", "turn/start", "thread/goal/get"])
        self.assertFalse(requests[2]["params"]["ephemeral"])
        goal = requests[3]["params"]
        self.assertEqual(goal["origin"], "user")
        self.assertEqual(goal["status"], "active")
        self.assertEqual(goal["tokenBudget"], 500000)
        self.assertEqual(requests[5]["params"]["input"], [{"type":"text", "text":goal["objective"]}])
        self.assertIn('"thread/goal/updated"', (root / "events.jsonl").read_text())

    def test_selectors_are_verified_before_goal_activation(self):
        for mode in ["wrong-model", "wrong-effort"]:
            with self.subTest(mode=mode):
                result, requests, _ = self.run_fixture(mode)
                self.assertEqual(result["status"], "failed")
                self.assertFalse(result["model_identity_verified"])
                self.assertNotIn("thread/goal/set", [request["method"] for request in requests])

    def test_changed_goal_readback_blocks_the_first_turn(self):
        result, requests, _ = self.run_fixture("wrong-goal")
        self.assertEqual(result["status"], "failed")
        self.assertNotIn("turn/start", [request["method"] for request in requests])
        self.assertEqual(requests[-1]["params"]["status"], "paused")

    def test_first_completed_turn_does_not_finish_an_active_goal(self):
        result, requests, _ = self.run_fixture("never-complete", seconds=0.4)
        self.assertEqual(result["status"], "timed_out")
        self.assertEqual(result["completed_turns"], 1)
        self.assertEqual(result["goal"]["status"], "paused")
        self.assertEqual(sum(request["method"] == "turn/start" for request in requests), 1)

    def test_no_implicit_token_budget(self):
        result, requests, _ = self.run_fixture(budget=None)
        self.assertEqual(result["status"], "complete")
        self.assertNotIn("tokenBudget", requests[3]["params"])

    def test_failed_turn_invalidates_completed_goal(self):
        result, _, _ = self.run_fixture("failed-turn")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["goal"]["status"], "complete")
        self.assertTrue(result["turn_errors"])


if __name__ == "__main__":
    unittest.main()
