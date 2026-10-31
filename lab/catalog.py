"""Read the installed Codex catalog without starting a generation."""
import json
import queue
import subprocess
import tempfile
import threading
import time


def discover(executable="codex", timeout=90):
    # Protocol verified against `codex app-server generate-json-schema` (0.163.0).
    with tempfile.TemporaryFile(mode="w+") as errors:
        process = subprocess.Popen(
            [executable, "app-server", "--stdio"], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=errors, text=True, bufsize=1,
        )
        lines = queue.Queue()

        def reader():
            for line in process.stdout:
                lines.put(line)
            lines.put(None)

        threading.Thread(target=reader, daemon=True).start()
        deadline = time.monotonic() + timeout
        sequence = 0

        def send(message):
            process.stdin.write(json.dumps(message) + "\n")
            process.stdin.flush()

        def request(method, params):
            nonlocal sequence
            sequence += 1
            send({"id": sequence, "method": method, "params": params})
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError("Codex catalog timed out; check `codex login status`.")
                try:
                    line = lines.get(timeout=remaining)
                except queue.Empty:
                    raise RuntimeError("Codex catalog timed out; check `codex login status`.") from None
                if line is None:
                    raise RuntimeError("Codex app-server exited before returning the catalog.")
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if message.get("id") != sequence:
                    continue
                if "error" in message:
                    raise RuntimeError(f"Catalog request failed: {message['error']}")
                return message["result"]

        try:
            request("initialize", {"clientInfo": {
                "name": "music_video_lab", "version": "1.0.0"}})
            send({"method": "initialized", "params": {}})
            models, cursor, seen = [], None, set()
            while True:
                params = {"includeHidden": True, "limit": 100}
                if cursor:
                    params["cursor"] = cursor
                response = request("model/list", params)
                models.extend(response["data"])
                cursor = response.get("nextCursor")
                if not cursor:
                    break
                if cursor in seen:
                    raise RuntimeError("Catalog returned a repeated pagination cursor.")
                seen.add(cursor)
            if not models:
                raise RuntimeError("Codex returned an empty catalog; no models were guessed.")
            return models
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            process.stdin.close()
            process.stdout.close()


def matrix(models, mode="all", selected=None, repeats=1):
    if mode not in {"all", "default"} or repeats < 1:
        raise ValueError("Use mode all/default and at least one repeat.")
    known = {m["model"] for m in models}
    if selected and set(selected) - known:
        raise ValueError(f"Models not in catalog: {sorted(set(selected) - known)}")
    rows, seen = [], set()
    for model in models:
        name = model["model"]
        if name in seen or (selected and name not in selected):
            continue
        seen.add(name)
        efforts = [e["reasoningEffort"] for e in model.get("supportedReasoningEfforts", [])]
        default = model.get("defaultReasoningEffort")
        if mode == "default":
            efforts = [default] if default else [None]
        elif not efforts:
            efforts = [default] if default else [None]
        for effort in dict.fromkeys(efforts):
            for repeat in range(1, repeats + 1):
                rows.append({"model": name, "effort": effort, "repeat": repeat,
                             "hidden": model.get("hidden", False)})
    return rows
