"""Linux filesystem namespaces for condition-independent model sessions.

Authentication is mounted by path without reading or logging credential values.
No user history, sibling run, experiment manifest, or parent conversation is
available inside the namespace. A model may still know its own identity.
"""
import os
import json
from pathlib import Path
import shutil
import subprocess


def bubblewrap():
    executable = shutil.which("bwrap")
    bundled = Path("/opt/codex/codex-resources/bwrap")
    if executable:
        return executable
    if bundled.is_file():
        return str(bundled)
    raise RuntimeError("Goal isolation requires bubblewrap on Linux; no weaker fallback is used.")


def goal_command(work, home, seconds, token_budget=500000, auth_file=None, prepare=True):
    work, home = Path(work).resolve(), Path(home).resolve()
    if os.name != "posix":
        raise RuntimeError("This goal-isolation backend requires Linux bubblewrap.")
    if prepare:
        home.mkdir(parents=True, exist_ok=True)
        (home / ".codex").mkdir(exist_ok=True)
    # Uniform configuration: no inherited user instructions, MCPs, memories or skills.
    if prepare:
        (home / ".codex/config.toml").write_text(
            '[features]\ngoals = true\nmulti_agent = false\nmulti_agent_v2 = false\n'
            'external_agent_memory_import = false\n')
    original_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    authentication = Path(auth_file) if auth_file else original_home / "auth.json"
    args = [bubblewrap(), "--die-with-parent", "--new-session", "--unshare-pid",
            "--ro-bind", "/", "/", "--tmpfs", "/workspace", "--tmpfs", "/tmp",
            "--tmpfs", "/home", "--dir", "/home/agent", "--bind", str(home), "/home/agent",
            "--dir", "/workspace/run", "--bind", str(work), "/workspace/run",
            "--dir", "/tmp/runner", "--ro-bind", str(Path(__file__).with_name("goal_session.py")), "/tmp/runner/session.py",
            "--proc", "/proc", "--dev", "/dev",
            "--setenv", "HOME", "/home/agent", "--setenv", "CODEX_HOME", "/home/agent/.codex",
            "--setenv", "TMPDIR", "/tmp", "--setenv", "PWD", "/workspace/run"]
    if authentication.is_file():
        # Preserve the authenticated CLI's normal path; do not inspect its contents.
        args.extend(["--ro-bind", str(authentication.resolve()), "/home/agent/.codex/auth.json"])
    # Retain proxy/CA/auth headers and runtime guards, but remove parent session
    # selectors, remote shell routing, and unrelated account credentials.
    remove = {"CODEX_THREAD_ID", "CODEX_SESSION_ID", "CODEX_TURN_ID", "GH_TOKEN", "GITHUB_TOKEN"}
    remove.add("CODEX_EXEC_SERVER_REMOTE_BASE_URL")
    for name in sorted(remove):
        args.extend(["--unsetenv", name])
    args.extend(["--chdir", "/workspace/run", "--", shutil.which("python3") or "python3",
                 "/tmp/runner/session.py", "--work", "/workspace/run",
                 "--result", "/home/agent/goal-result.json",
                 "--events", "/home/agent/goal-events.jsonl", "--seconds", str(seconds),
                 "--token-budget", str(token_budget)])
    return args


def verify_namespace(work, home, auth_file=None):
    """Run a real no-model check that host workspace/home/temp cannot be read."""
    command = goal_command(work, home, 30, auth_file=auth_file)
    end = command.index("--")
    code = (
        "from pathlib import Path; import json,os; "
        "assert set(p.name for p in Path('/workspace').iterdir()) == {'run'}; "
        "assert set(p.name for p in Path('/tmp').iterdir()) == {'runner'}; "
        "assert not Path('/workspace/run/../manifest.json').exists(); "
        "assert not Path('/workspace/run/../runs').exists(); "
        "assert not Path('/home/agent/.codex/AGENTS.md').exists(); "
        "assert not Path('/home/agent/.codex/memories_1.sqlite').exists(); "
        "print(json.dumps({'filesystem_isolated':True,'cwd':os.getcwd()}))"
    )
    result = subprocess.run(command[:end+1] + [shutil.which("python3") or "python3", "-c", code],
                            check=True, capture_output=True, text=True, timeout=30)
    return result.stdout


def verify_native_goal(work, home, model, effort):
    """Check real native APIs with a paused goal, never starting a model turn."""
    command = goal_command(work, home, 30)
    end = command.index("--")
    sentinel = Path(work).resolve().parent / "sibling-sentinel.txt"
    sentinel.write_text("Must not be visible inside a worker namespace.")
    code = """import json,runpy,time,sys,os,shlex
module=runpy.run_path('/tmp/runner/session.py',run_name='readiness')
selectors=json.load(sys.stdin)
assert not any(k in os.environ for k in ['CODEX_THREAD_ID','CODEX_SESSION_ID','CODEX_TURN_ID','GH_TOKEN','GITHUB_TOKEN'])
state=module['GoalState']()
client=module['RpcClient'](['codex','--enable','goals','app-server','--stdio'],'/home/agent/readiness-events.jsonl',state)
deadline=time.monotonic()+25
try:
 client.request('initialize',{'clientInfo':{'name':'goal_readiness','version':'1'},'capabilities':{'experimentalApi':True}},deadline)
 client.send({'method':'initialized','params':{}})
 thread=client.request('thread/start',{'cwd':'/workspace/run','model':selectors['model'],'approvalPolicy':'never','sandbox':'workspace-write','ephemeral':False,'config':{'model_reasoning_effort':selectors['effort']}},deadline)
 state.thread_id=thread['thread']['id']
 assert thread['model']==selectors['model'] and thread['reasoningEffort']==selectors['effort']
 assert thread['thread']['ephemeral'] is False and not thread['thread']['turns']
 goal=client.request('thread/goal/set',{'threadId':state.thread_id,'objective':'Readiness check only; remain paused. No generation is requested.','status':'paused','origin':'user','tokenBudget':1},deadline)['goal']
 assert goal['status']=='paused'
 check_code = "import os,json; from pathlib import Path; assert os.getcwd()=='/workspace/run'; assert sorted(p.name for p in Path('/workspace').iterdir())==['run']; assert not Path("+repr(selectors['sentinel'])+").exists(); assert 'CODEX_EXEC_SERVER_REMOTE_BASE_URL' not in os.environ; assert not any(k in os.environ for k in ['GH_TOKEN','GITHUB_TOKEN']); print(json.dumps({'cwd':os.getcwd(),'native_thread_id':os.getenv('CODEX_THREAD_ID')}))"
 client.request('thread/shellCommand',{'threadId':state.thread_id,'command':'python3 -c '+shlex.quote(check_code),'timeoutMs':5000},deadline)
 while True:
  event=client.next(deadline)
  item=event.get('params',{}).get('item',{})
  if event.get('method')=='item/completed' and item.get('type')=='commandExecution':
   assert item['exitCode']==0, item.get('aggregatedOutput')
   result=json.loads(item['aggregatedOutput'])
   assert result['native_thread_id']==state.thread_id
   break
 print(json.dumps({'effective_model':thread['model'],'effective_effort':thread['reasoningEffort'],'persistent_thread':True,'goal_status':'paused','native_shell_isolated':True,'model_turns_requested':0}),flush=True)
finally:
 client.close()
"""
    result = subprocess.run(command[:end+1] + [shutil.which("python3") or "python3", "-c", code],
                            input=json.dumps({"model": model, "effort": effort, "sentinel": str(sentinel)}),
                            check=True, capture_output=True, text=True, timeout=35)
    return json.loads(result.stdout)
