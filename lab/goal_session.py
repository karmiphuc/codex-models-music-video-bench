"""Run one fresh native Codex goal; callers supply isolation and authentication.

The server protocol follows codex-cli 0.163.0's generated v2 schemas. This
module never resumes a thread or supplies its own continuation/coaching text.
Selectors may arrive on stdin so they need not appear in process arguments.
"""
import argparse
import json
import math
from pathlib import Path
import queue
import signal
import subprocess
import sys
import threading
import time


TERMINAL_GOALS = {"complete", "blocked", "paused", "usageLimited", "budgetLimited"}


class ProtocolError(RuntimeError):
    pass


class GoalState:
    def __init__(self):
        self.thread_id = None
        self.goal = None
        self.active_turns = set()
        self.completed_turns = set()
        self.usage = None
        self.reroutes = []
        self.turn_errors = []
        self.final_message = ""

    def notification(self, message):
        method = message.get("method", "")
        params = message.get("params", {})
        if params.get("threadId") != self.thread_id:
            return
        if "rerout" in method.lower():
            self.reroutes.append(message)
        if method == "thread/goal/updated":
            self.goal = params["goal"]
        elif method == "thread/goal/cleared":
            raise ProtocolError("Native goal was cleared before completion")
        elif method == "turn/started":
            self.active_turns.add(params["turn"]["id"])
        elif method == "turn/completed":
            turn = params["turn"]
            self.active_turns.discard(turn["id"])
            self.completed_turns.add(turn["id"])
            if turn.get("status") != "completed" or turn.get("error"):
                self.turn_errors.append(turn)
        elif method == "thread/tokenUsage/updated":
            # 'total' is cumulative for the thread, including native continuations.
            usage = params["tokenUsage"]["total"]
            self.usage = {
                "input_tokens": usage["inputTokens"],
                "cached_input_tokens": usage["cachedInputTokens"],
                "output_tokens": usage["outputTokens"],
                "reasoning_output_tokens": usage.get("reasoningOutputTokens"),
                "total_tokens": usage.get("totalTokens"),
            }
        elif method == "item/completed":
            item = params.get("item", {})
            if item.get("type") == "agentMessage":
                self.final_message = item.get("text", "")
        elif method == "error" and not params.get("willRetry", False):
            raise ProtocolError("App-server turn error: " + json.dumps(params.get("error", params)))

    @property
    def stopped(self):
        return bool(self.goal and self.goal.get("status") in TERMINAL_GOALS and not self.active_turns)


class RpcClient:
    def __init__(self, command, events_path, state):
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=sys.stderr, text=True, bufsize=1)
        self.lines = queue.Queue()
        self.state = state
        self.sequence = 0
        self.events = Path(events_path).open("w", encoding="utf-8")

        def reader():
            try:
                for line in self.process.stdout:
                    self.events.write(line)
                    self.events.flush()
                    self.lines.put(line)
            finally:
                self.lines.put(None)

        self.reader = threading.Thread(target=reader, daemon=True)
        self.reader.start()

    def send(self, message):
        self.process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
        self.process.stdin.flush()

    def next(self, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Native goal exceeded the session wall-clock limit")
        try:
            line = self.lines.get(timeout=remaining)
        except queue.Empty:
            raise TimeoutError("Native goal exceeded the session wall-clock limit") from None
        if line is None:
            raise ProtocolError("App-server exited before the native goal stopped")
        try:
            message = json.loads(line)
        except json.JSONDecodeError as error:
            raise ProtocolError("App-server emitted malformed JSON") from error
        if "method" in message:
            if "id" in message:
                # No interactive approvals, user answers, or dynamic tools in a condition.
                self.send({"id": message["id"], "error": {
                    "code": -32601, "message": "Interactive server requests are disabled in this benchmark"}})
                raise ProtocolError("Unexpected interactive server request: " + message["method"])
            self.state.notification(message)
        return message

    def request(self, method, params, deadline):
        self.sequence += 1
        request_id = self.sequence
        self.send({"id": request_id, "method": method, "params": params})
        while True:
            message = self.next(deadline)
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise ProtocolError(method + " failed: " + json.dumps(message["error"]))
            if "result" not in message:
                raise ProtocolError(method + " returned no result")
            return message["result"]

    def close(self):
        if self.process.poll() is None:
            try:
                self.process.stdin.close()
            except OSError:
                pass
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
        self.reader.join(timeout=2)
        if not self.reader.is_alive():
            self.events.close()
        self.process.stdout.close()


def _verify_goal(goal, thread_id, objective, token_budget):
    if not goal or goal.get("threadId") != thread_id or goal.get("objective") != objective:
        raise ProtocolError("Native goal readback differs from the identical task")
    if goal.get("status") != "active" or goal.get("tokenBudget") != token_budget:
        raise ProtocolError("Native goal status or token budget differs from the request")


def run_session(work, result_path, events_path, model, effort, seconds,
                token_budget=None, server_command=None):
    """Return/write the native goal result; server_command is injectable for offline tests."""
    if not model or not effort:
        raise ValueError("An explicit model and advertised reasoning effort are required")
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("seconds must be positive and finite")
    if token_budget is not None and (isinstance(token_budget, bool) or
                                     not isinstance(token_budget, int) or token_budget <= 0):
        raise ValueError("token_budget must be a positive integer when supplied")
    work = Path(work).resolve()
    objective = (work / "TASK.txt").read_text(encoding="utf-8")
    result_path, events_path = Path(result_path), Path(events_path)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    events_path.parent.mkdir(parents=True, exist_ok=True)
    state = GoalState()
    client = None
    started = time.monotonic()
    deadline = started + seconds
    result = {"status": "failed", "requested_model": model, "requested_effort": effort,
              "model_identity_verified": False, "identity_verification_scope":
              "App-server effective configuration, not independent server execution attestation"}
    try:
        command = server_command or ["codex", "--enable", "goals", "--disable", "multi_agent",
                                      "--disable", "multi_agent_v2", "app-server", "--stdio"]
        client = RpcClient(command, events_path, state)
        client.request("initialize", {
            "clientInfo": {"name": "music_video_goal_bench", "version": "1.0.0"},
            "capabilities": {"experimentalApi": True},
        }, deadline)
        client.send({"method": "initialized", "params": {}})
        thread = client.request("thread/start", {
            "cwd": str(work), "model": model, "approvalPolicy": "never",
            "sandbox": "workspace-write", "ephemeral": False,
            "config": {"model_reasoning_effort": effort},
        }, deadline)
        state.thread_id = thread["thread"]["id"]
        result.update(thread_id=state.thread_id, effective_model=thread.get("model"),
                      effective_effort=thread.get("reasoningEffort"),
                      instruction_sources=thread.get("instructionSources", []))
        if thread.get("model") != model or thread.get("reasoningEffort") != effort:
            raise ProtocolError("Effective model/effort differs from the requested condition")
        metadata = thread["thread"]
        if metadata.get("ephemeral") is not False or metadata.get("parentThreadId") or metadata.get("forkedFromId") or metadata.get("turns"):
            raise ProtocolError("Native goals require a fresh, persistent, unforked thread")
        result["model_identity_verified"] = True
        goal_request = {"threadId": state.thread_id, "objective": objective,
                        "status": "active", "origin": "user"}
        if token_budget is not None:
            goal_request["tokenBudget"] = token_budget
        state.goal = client.request("thread/goal/set", goal_request, deadline)["goal"]
        _verify_goal(state.goal, state.thread_id, objective, token_budget)
        state.goal = client.request("thread/goal/get", {"threadId": state.thread_id}, deadline)["goal"]
        _verify_goal(state.goal, state.thread_id, objective, token_budget)
        # Exactly one TASK-only user input. Any subsequent work is native goal continuation.
        turn = client.request("turn/start", {
            "threadId": state.thread_id, "model": model, "effort": effort,
            "input": [{"type": "text", "text": objective}], "approvalPolicy": "never",
        }, deadline)["turn"]
        if turn["id"] not in state.completed_turns and turn.get("status") == "inProgress":
            state.active_turns.add(turn["id"])
        while True:
            while not state.stopped:
                client.next(deadline)
            # A barrier after turn stop captures final accounting notifications and
            # the authoritative goal state, including any final tool/turn usage.
            state.goal = client.request("thread/goal/get", {"threadId": state.thread_id}, deadline)["goal"]
            if not state.goal or state.goal.get("objective") != objective or state.goal.get("threadId") != state.thread_id:
                raise ProtocolError("Native goal changed before final readback")
            if state.stopped:
                break
        result["status"] = state.goal["status"]
        if state.reroutes or state.turn_errors or not state.completed_turns:
            result.update(status="failed", error="Native execution rerouted, failed, or completed no turns")
    except TimeoutError as error:
        result.update(status="timed_out", error=str(error))
    except KeyboardInterrupt:
        result.update(status="interrupted", error="Session interrupted")
    except (OSError, KeyError, ValueError, RuntimeError) as error:
        result.update(status="failed", error=str(error))
    finally:
        if client is not None:
            if state.thread_id and state.goal and state.goal.get("status") == "active":
                # The caller's explicit wall-clock limit authorizes stopping this run.
                try:
                    stopped = client.request("thread/goal/set", {
                        "threadId": state.thread_id, "status": "paused", "origin": "user",
                    }, time.monotonic() + 2)
                    state.goal = stopped["goal"]
                except (OSError, RuntimeError, TimeoutError, KeyError) as error:
                    result["stop_error"] = str(error)
            for turn_id in tuple(state.active_turns):
                try:
                    client.request("turn/interrupt", {"threadId": state.thread_id, "turnId": turn_id},
                                   time.monotonic() + 2)
                except (OSError, RuntimeError, TimeoutError):
                    pass
            client.close()
        result.update(goal=state.goal, completed_turns=len(state.completed_turns), usage=state.usage,
                      reroutes=state.reroutes, turn_errors=state.turn_errors,
                      final_message=state.final_message,
                      wall_seconds=round(time.monotonic() - started, 3))
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", required=True)
    parser.add_argument("--result", required=True)
    parser.add_argument("--events", required=True)
    parser.add_argument("--model")
    parser.add_argument("--effort")
    parser.add_argument("--seconds", type=float, required=True)
    parser.add_argument("--token-budget", type=int)
    args = parser.parse_args(argv)
    selectors = {} if args.model and args.effort else json.load(sys.stdin)
    model, effort = args.model or selectors.get("model"), args.effort or selectors.get("effort")
    if threading.current_thread() is threading.main_thread():
        def interrupted(_signum, _frame):
            raise KeyboardInterrupt()
        signal.signal(signal.SIGTERM, interrupted)
    result = run_session(args.work, args.result, args.events, model, effort, args.seconds, args.token_budget)
    if result.get("usage"):
        print(json.dumps({"type": "turn.completed", "usage": result["usage"]}), flush=True)
    if result["status"] != "complete":
        print(json.dumps({"type": "turn.failed", "error": {
            "message": result.get("error", "Native goal stopped with status " + result["status"])}}), flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
