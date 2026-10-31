#!/usr/bin/env python3
"""Run `python lab.py --help` from any directory."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import shutil
import signal
import subprocess
import sys
import time

from lab.catalog import discover, matrix, preset_matrix
from lab.isolation import goal_command, verify_namespace, verify_native_goal
from lab.artifacts import validate_artifacts
from lab.media import contact_sheet, demo_audio, prepare_audio, validate_video

ROOT = Path(__file__).resolve().parent


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")


def read(path):
    return json.loads(Path(path).read_text())


def stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tree_hashes(path):
    return {str(p.relative_to(path)): file_hash(p) for p in sorted(path.rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts and ".git" not in p.parts}


def version(command):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=15)
        return (result.stdout or result.stderr).splitlines()[0] if result.returncode == 0 else "unavailable"
    except (OSError, subprocess.TimeoutExpired, IndexError):
        return "unavailable"


def environment():
    return {"python": sys.version, "platform": sys.platform,
            "codex": version(["codex", "--version"]),
            "ffmpeg": version(["ffmpeg", "-version"]),
            "blender": version(["blender", "--version"]),
            "packages": {name: importlib.metadata.version(name) for name in ["numpy", "Pillow"]}}


def doctor(_):
    result = environment()
    result["tools"] = {name: shutil.which(name) for name in ["codex", "ffmpeg", "ffprobe", "git", "blender"]}
    result["prepared_songs"] = [p.name for p in prepared_songs()]
    print(json.dumps(result, indent=2))


def cmd_discover(args):
    models = discover()
    path = ROOT / "catalog.json"
    write(path, {"discovered_at": stamp(), "codex_version": version(["codex", "--version"]),
                 "source": "Codex app-server model/list; includes hidden entries; availability checked only on execution",
                 "models": models})
    rows = matrix([m for m in models if not m.get("hidden")])
    with (ROOT / "MODEL_MATRIX.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["model", "effort", "repeat", "hidden"])
        writer.writeheader()
        writer.writerows(rows)
    for model in models:
        efforts = [e["reasoningEffort"] for e in model.get("supportedReasoningEfforts", [])]
        print(f"{model['model']}: {', '.join(efforts) or 'default'}" + (" [hidden]" if model.get("hidden") else ""))
    print(f"Saved {len(models)} entries to {path}")


def cmd_preflight(args):
    catalog = read(ROOT / "catalog.json")
    preset = read(ROOT / "presets" / (song_id(args.preset) + ".json"))
    rows = preset_matrix(catalog["models"], preset["conditions"])
    root = ROOT / "scratch" / ("preflight-" + stamp())
    results = []
    for number, row in enumerate(rows, 1):
        work, home = root / str(number) / "work", root / str(number) / "home"
        work.mkdir(parents=True)
        isolated = json.loads(verify_namespace(work, home))
        native = verify_native_goal(work, home, row["model"], row["effort"])
        results.append({**row, **isolated, **native})
        print(f"Ready: {row['model']} / {row['effort']}; isolated persistent goal; no model turn requested", flush=True)
    write(root / "readiness.json", {"preset": args.preset, "checks": results, "generation_sessions_started": 0})
    print(f"Readiness evidence: {root / 'readiness.json'}")


def song_id(value):
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", value) or value == "demo":
        raise ValueError("Song ID must use 1–80 lowercase letters, numbers, hyphens or underscores; 'demo' is reserved.")
    return value


def prepared_songs():
    return sorted(p for p in (ROOT / "prepared").glob("*")
                  if p.name != "demo" and (p / "audio.wav").is_file() and (p / "audio-map.json").is_file())


def select_song(name=None):
    if name:
        target = ROOT / "prepared" / song_id(name)
        if (target / "audio.wav").is_file() and (target / "audio-map.json").is_file():
            return target
        raise ValueError(f"Song '{name}' is not prepared. Run `prepare --audio /path/to/song.mp3 --song {name}` first.")
    choices = prepared_songs()
    if len(choices) == 1:
        return choices[0]
    if not choices:
        raise ValueError("No song prepared. Add any track later with `prepare --audio /path/to/song.mp3`, or use `plan --demo` for diagnostics.")
    raise ValueError("Choose a prepared track with --song: " + ", ".join(p.name for p in choices))


def cmd_prepare(args):
    title = args.title or Path(args.audio).stem
    name = args.song or re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:80] or "song"
    target = ROOT / "prepared" / song_id(name)
    summary = prepare_audio(args.audio, target, args.start, args.duration, args.bpm, args.cues,
                            title=title, artist=args.artist)
    write(target / "provenance.json", {
        "source_name": Path(args.audio).name, "source_sha256": file_hash(args.audio),
        "prepared_at": stamp(), "song_id": name, "track": title, "artist": args.artist,
        "source_start_seconds": args.start, "duration_seconds": summary["duration_seconds"],
        "license_record": args.license_note or "Not recorded; retain the source license/attribution separately.",
    })
    print(f"Prepared '{title}' at {target}. Review audio-map.json, then plan with --song {name}.")


def seed_project(destination, prepared, spec):
    shutil.copytree(ROOT / "template", destination, ignore=shutil.ignore_patterns("__pycache__"))
    (destination / "lab").mkdir()
    for filename in ["__init__.py", "media.py"]:
        shutil.copy2(ROOT / "lab" / filename, destination / "lab" / filename)
    for filename in ["audio.wav", "audio-map.json", "provenance.json"]:
        if (prepared / filename).exists():
            shutil.copy2(prepared / filename, destination / filename)
    shutil.copy2(ROOT / "prompts/music-video.txt", destination / "TASK.txt")
    shutil.copy2(ROOT / "requirements.txt", destination / "requirements.txt")
    write(destination / "spec.json", spec)


def demo_fixture():
    target = ROOT / "prepared/demo"
    if not target.exists():
        source = ROOT / "scratch/demo-source.wav"
        demo_audio(source)
        prepare_audio(source, target, 0, 12, bpm=100, demo=True)
        write(target / "provenance.json", {"is_demo": True, "description": "Original procedural test audio; not a user-selected song."})
    return target


def cmd_plan(args):
    if not (ROOT / "catalog.json").exists():
        raise ValueError("No catalog.json. Run `python lab.py discover` first; no model names will be guessed.")
    catalog = read(ROOT / "catalog.json")
    prepared = demo_fixture() if args.demo else select_song(args.song)
    settings = read(ROOT / "experiment.json")
    audio_map = read(prepared / "audio-map.json")
    settings["duration_seconds"] = audio_map["duration_seconds"]
    settings["track"] = audio_map["track"]
    settings["artist"] = audio_map.get("artist")
    execution = {"mode": "exec", "isolation": "workspace-write"}
    preset_name = getattr(args, "preset", None)
    if preset_name:
        if args.models:
            raise ValueError("Choose either an exact preset or --models, not both.")
        preset = read(ROOT / "presets" / (song_id(preset_name) + ".json"))
        rows = preset_matrix(catalog["models"], preset["conditions"], args.repeats)
        execution = {k: preset[k] for k in ["mode", "isolation", "goal_token_budget"]}
        settings["execution_mode"] = preset["mode"]
    else:
        candidates = catalog["models"] if args.include_hidden or args.models else [m for m in catalog["models"] if not m.get("hidden")]
        rows = matrix(candidates, args.efforts, args.models, args.repeats)
    if not rows:
        raise ValueError("No matching models.")
    experiment = ROOT / "experiments" / (prepared.name + "-" + stamp())
    experiment.mkdir(parents=True)
    seed_project(experiment / "seed", prepared, settings)
    for i, row in enumerate(rows, 1):
        row["id"] = f"run-{i:03d}"
    write(experiment / "manifest.json", {
        "created_at": stamp(), "song_id": prepared.name, "is_demo": args.demo,
        "efforts_mode": "preset" if preset_name else args.efforts, "preset": preset_name, "execution": execution,
        "repeats": args.repeats, "environment": environment(),
        "catalog": catalog,
        "excluded_models": [m["model"] for m in catalog["models"] if m["model"] not in {r["model"] for r in rows}],
        "seed_sha256": tree_hashes(experiment / "seed"),
        "runtime_sha256": {p: file_hash(ROOT / p) for p in ["lab/goal_session.py", "lab/isolation.py"]} if execution["mode"] == "goal" else {},
        "spec": settings, "runs": rows,
    })
    print(f"Frozen {len(rows)} runs in {experiment}")
    print(f"Dry run: python lab.py run --experiment {shlex.quote(str(experiment))}")


def command(work, row, attempt):
    args = ["codex", "--ask-for-approval", "never", "exec", "--ignore-user-config",
            "--disable", "multi_agent", "--disable", "multi_agent_v2",
            "--sandbox", "workspace-write", "--model", row["model"],
            "--cd", str(work), "--json", "--ephemeral", "--color", "never",
            "--output-last-message", str(attempt / "final-message.txt")]
    if row["effort"]:
        args.extend(["-c", "model_reasoning_effort=" + json.dumps(row["effort"])])
    # Identical prompt bytes are supplied on stdin. No model or effort labels in the task.
    return args + ["-"]


def usage_from_events(path):
    totals = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0}
    completed, failed, reroutes = 0, False, []
    for line in Path(path).read_text(errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        event_type = event.get("type", event.get("method", ""))
        if event_type == "turn.completed":
            completed += 1
            for key in totals:
                totals[key] += event.get("usage", {}).get(key, 0) or 0
        if event_type in {"turn.failed", "error"}:
            failed = True
        if "rerout" in event_type.lower():
            reroutes.append(event)
    return {"usage": totals if completed else None, "completed_turns": completed,
            "event_failure": failed, "reroutes": reroutes}


def stop_process(process):
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
    else:
        process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            process.kill()
        process.wait()
    # The CLI may have exited while a render child remains in its process group.
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def cmd_run(args):
    experiment = Path(args.experiment).resolve()
    manifest = read(experiment / "manifest.json")
    if tree_hashes(experiment / "seed") != manifest["seed_sha256"]:
        raise ValueError("Frozen seed changed. Make a new plan instead of mixing inputs.")
    rows = manifest["runs"]
    execution = manifest.get("execution", {"mode": "exec"})
    goal_mode = execution["mode"] == "goal"
    if goal_mode and any(file_hash(ROOT / path) != digest for path, digest in manifest.get("runtime_sha256", {}).items()):
        raise ValueError("Frozen goal runtime changed. Create a new plan.")
    if args.only:
        unknown = set(args.only) - {r["id"] for r in rows}
        if unknown:
            raise ValueError(f"Unknown run IDs: {sorted(unknown)}")
        rows = [r for r in rows if r["id"] in args.only]
    if args.limit:
        rows = rows[:args.limit]
    if not args.execute:
        for row in rows:
            attempt = experiment / "runs" / row["id"] / "attempt-001"
            cmd = goal_command(attempt / "work", attempt / "home", args.seconds,
                               execution["goal_token_budget"], prepare=False) if goal_mode else command(attempt / "work", row, attempt)
            print(shlex.join(cmd))
            if goal_mode:
                print("  stdin selectors: " + json.dumps({"model": row["model"], "effort": row["effort"]}))
        print(f"Dry run: {len(rows)} commands; add --execute to launch model sessions. No sessions started.")
        return
    current_env = environment()
    if current_env != manifest["environment"]:
        raise ValueError("Tool environment differs from the frozen plan. Create a new plan on this host.")
    launched, suite_start = 0, time.monotonic()
    interrupted = False
    for row in rows:
        run_dir = experiment / "runs" / row["id"]
        attempts = sorted(run_dir.glob("attempt-*")) if run_dir.exists() else []
        if attempts:
            previous = read(attempts[-1] / "metrics.json") if (attempts[-1] / "metrics.json").exists() else {"status": "interrupted"}
            if previous.get("status") == "complete" or not args.retry_failed:
                print(f"Skip {row['id']}: {previous.get('status')}", flush=True)
                continue
        remaining = args.total_seconds - (time.monotonic() - suite_start)
        if remaining <= 0:
            print("Suite time limit reached; unstarted runs remain pending.")
            break
        attempt = run_dir / f"attempt-{len(attempts) + 1:03d}"
        attempt.mkdir(parents=True)
        work = attempt / "work"
        shutil.copytree(experiment / "seed", work, ignore=shutil.ignore_patterns("__pycache__"))
        subprocess.run(["git", "init", "--quiet", str(work)], check=True)
        if goal_mode:
            write(attempt / "isolation-check.json", json.loads(verify_namespace(work, attempt / "home")))
            cmd = goal_command(work, attempt / "home", min(args.seconds, remaining), execution["goal_token_budget"])
        else:
            cmd = command(work, row, attempt)
        write(attempt / "command.json", {"argv": cmd, "stdin": {"model": row["model"], "effort": row["effort"]} if goal_mode else "work/TASK.txt", "environment": current_env})
        metrics = {**row, "status": "running", "started_at": stamp(),
                   "baseline_matches": tree_hashes(work) == manifest["seed_sha256"],
                   "cost_usd": None, "human_interventions": 0,
                   "model_identity_verification": "Request pins model/effort. Server identity is not exposed by every CLI event; reported reroutes invalidate a condition."}
        write(attempt / "metrics.json", metrics)
        print(f"Start {row['id']}: {row['model']} / {row['effort'] or 'default'}", flush=True)
        started = time.monotonic()
        try:
            with (attempt / "events.jsonl").open("w") as events, (attempt / "stderr.log").open("w") as errors, (work / "TASK.txt").open() as task:
                process = subprocess.Popen(cmd, stdin=subprocess.PIPE if goal_mode else task, stdout=events, stderr=errors,
                                           text=True,
                                           start_new_session=(os.name == "posix"))
                if goal_mode:
                    process.stdin.write(json.dumps({"model": row["model"], "effort": row["effort"]}) + "\n")
                    process.stdin.close()
                try:
                    metrics["exit_code"] = process.wait(timeout=min(args.seconds, remaining))
                    metrics["status"] = "finished"
                except subprocess.TimeoutExpired:
                    stop_process(process)
                    metrics.update(status="timed_out", exit_code=process.returncode)
                except KeyboardInterrupt:
                    stop_process(process)
                    metrics.update(status="interrupted", exit_code=process.returncode)
                    interrupted = True
        except OSError as error:
            metrics.update(status="launch_failed", error=str(error), exit_code=None)
        metrics["wall_seconds"] = round(time.monotonic() - started, 3)
        if (attempt / "events.jsonl").exists():
            metrics.update(usage_from_events(attempt / "events.jsonl"))
        if goal_mode:
            native_path = attempt / "home/goal-result.json"
            if native_path.is_file():
                native = read(native_path)
                shutil.copy2(native_path, attempt / "goal-result.json")
                metrics["native_goal"] = native.get("goal")
                metrics["model_identity_verified"] = native.get("model_identity_verified", False)
                metrics["native_goal_status"] = native.get("status")
                metrics["usage"] = native.get("usage")
                metrics["completed_turns"] = native.get("completed_turns", 0)
                metrics["reroutes"] = native.get("reroutes", [])
                metrics["native_errors"] = native.get("turn_errors", [])
                if native.get("final_message"):
                    (attempt / "final-message.txt").write_text(native["final_message"])
                if native.get("status") != "complete" and metrics["status"] == "finished":
                    metrics["status"] = native.get("status", "failed")
            else:
                metrics["native_goal_status"] = "missing"
                if metrics["status"] == "finished":
                    metrics["status"] = "failed"
            native_events = attempt / "home/goal-events.jsonl"
            if native_events.is_file():
                shutil.copy2(native_events, attempt / "goal-events.jsonl")
        inputs = ["audio.wav", "audio-map.json", "spec.json", "TASK.txt", "AGENTS.md"]
        metrics["inputs_unchanged"] = all(
            (work / p).is_file() and file_hash(work / p) == manifest["seed_sha256"][p] for p in inputs)
        validation = validate_video(work / "output/final.mp4", manifest["spec"], source_audio=experiment / "seed/audio.wav")
        write(attempt / "validation.json", validation)
        artifact_validation = validate_artifacts(work, manifest["spec"]["duration_seconds"])
        write(attempt / "artifacts.json", artifact_validation)
        metrics["artifact_formats_valid"] = artifact_validation["passed"]
        if validation["passed"]:
            contact_sheet(work / "output/final.mp4", attempt / "verified-contact-sheet.png")
        required = ["storyboard.json", "output/final.mp4", "output/contact-sheet.png", "output/qa.md"]
        metrics["deliverables_present"] = all((work / p).is_file() for p in required)
        source_suffixes = {".py", ".js", ".ts", ".html", ".svg", ".blend", ".glsl"}
        metrics["creative_sources_changed"] = any(
            Path(name).suffix in source_suffixes and manifest["seed_sha256"].get(name) != digest
            for name, digest in tree_hashes(work).items()
            if not name.startswith(("lab/", "output/")))
        if metrics["status"] == "finished":
            metrics["status"] = "complete" if (
                metrics.get("exit_code") == 0 and not metrics.get("event_failure") and
                metrics.get("completed_turns", 0) > 0 and not metrics.get("reroutes") and
                metrics["inputs_unchanged"] and validation["passed"] and metrics["deliverables_present"] and metrics["artifact_formats_valid"] and
                metrics["creative_sources_changed"] and
                (not goal_mode or (metrics.get("native_goal_status") == "complete" and metrics.get("model_identity_verified")))
            ) else "failed"
        metrics["finished_at"] = stamp()
        write(attempt / "metrics.json", metrics)
        print(f"{row['id']}: {metrics['status']} ({metrics['wall_seconds']}s)", flush=True)
        launched += 1
        if interrupted:
            break
    cmd_report(argparse.Namespace(experiment=str(experiment)))
    print(f"Launched {launched} sessions. 'complete' means mechanical checks only; review creative quality manually.")


def cmd_report(args):
    experiment = Path(args.experiment).resolve()
    manifest = read(experiment / "manifest.json")
    fields = ["id", "model", "effort", "repeat", "status", "wall_seconds", "input_tokens",
              "cached_input_tokens", "output_tokens", "cost_usd", "technical_pass", "video"]
    rows = []
    review = ["blind_id,concept,story_or_dance,motion,beat_sync,composition,ending,notes"]
    blind_path = experiment / "blind-key.json"
    blind_map = read(blind_path) if blind_path.exists() else []
    for row in manifest["runs"]:
        attempts = sorted((experiment / "runs" / row["id"]).glob("attempt-*"))
        attempt = attempts[-1] if attempts else None
        metrics = read(attempt / "metrics.json") if attempt and (attempt / "metrics.json").exists() else {}
        validation = read(attempt / "validation.json") if attempt and (attempt / "validation.json").exists() else {}
        video = attempt / "work/output/final.mp4" if attempt else None
        usage = metrics.get("usage") or {}
        result = {k: row.get(k, "") for k in ["id", "model", "effort", "repeat"]}
        result.update(status=metrics.get("status", "pending"), wall_seconds=metrics.get("wall_seconds"),
                      cost_usd=None, technical_pass=validation.get("passed"),
                      video=str(video.relative_to(experiment)) if video and video.exists() else "")
        result.update({k: usage.get(k) for k in ["input_tokens", "cached_input_tokens", "output_tokens"]})
        rows.append(result)
        if video and video.exists():
            digest = file_hash(video)
            existing_export = next((item for item in blind_map if item.get("run") == row["id"] and item.get("video_sha256") == digest), None)
            blind_id = existing_export["blind_id"] if existing_export else "clip-" + secrets.token_hex(8)
            export = experiment / "review" / (blind_id + ".mp4")
            export.parent.mkdir(exist_ok=True)
            if not export.exists() or file_hash(export) != file_hash(video):
                shutil.copy2(video, export)
            if not existing_export:
                blind_map.append({"blind_id": blind_id, "run": row["id"], "model": row["model"],
                                  "effort": row["effort"], "video_sha256": digest,
                                  "attempt": attempt.name})
            review.append(blind_id + ",,,,,,,")
    with (experiment / "results.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    # Opaque random IDs avoid exposing condition order. New video bytes get a new ID.
    review[1:] = sorted(review[1:])
    # Never overwrite filled human scores on resume.
    score_path = experiment / "review-scores.csv"
    if not score_path.exists():
        score_path.write_text("\n".join(review) + "\n")
    else:
        with score_path.open() as stream:
            existing = {r["blind_id"] for r in csv.DictReader(stream)}
        with score_path.open("a") as stream:
            for line in review[1:]:
                if line.split(",")[0] not in existing:
                    stream.write(line + "\n")
    write(experiment / "blind-key.json", sorted(blind_map, key=lambda r: r["blind_id"]))
    lines = ["# Experiment results", "", "Mechanical status only. Score anonymous clips using docs/RUBRIC.md.",
             "Token counts come from CLI turn.completed events; absent usage and dollar costs remain blank.",
             "Cached input tokens are a subset of input tokens; do not add them twice.", "",
             "| Run | Model | Effort | Status | Seconds | Video |", "|---|---|---|---|---:|---|"]
    for r in rows:
        link = f"[MP4]({r['video']})" if r["video"] else "—"
        lines.append(f"| {r['id']} | {r['model']} | {r['effort'] or 'default'} | {r['status']} | {r['wall_seconds'] or '—'} | {link} |")
    (experiment / "RESULTS.md").write_text("\n".join(lines) + "\n")
    print(f"Report: {experiment / 'RESULTS.md'}")


def cmd_smoke(_):
    prepared = demo_fixture()
    settings = read(ROOT / "experiment.json")
    settings.update(duration_seconds=3, width=640, height=360, fps=24)
    destination = ROOT / "scratch" / ("smoke-" + stamp())
    # Trim fixture to keep duration requirements consistent.
    trimmed = ROOT / "scratch" / ("audio-" + stamp())
    prepare_audio(prepared / "audio.wav", trimmed, 0, 3, bpm=100, demo=True)
    seed_project(destination, trimmed, settings)
    subprocess.run([sys.executable, "render.py"], cwd=destination, check=True)
    result = validate_video(destination / "output/final.mp4", settings)
    write(destination / "output/validation.json", result)
    contact_sheet(destination / "output/final.mp4", destination / "output/contact-sheet.png")
    print(json.dumps(result, indent=2))
    print(f"Diagnostic only, no model calls: {destination / 'output/final.mp4'}")
    if not result["passed"]:
        raise ValueError("Smoke test failed.")


def positive_float(value):
    number = float(value)
    if not (0 < number < float("inf")):
        raise argparse.ArgumentTypeError("Must be positive and finite")
    return number


def positive_int(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("Must be at least 1")
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("doctor", help="Inspect required tools and audio readiness").set_defaults(func=doctor)
    sub.add_parser("discover", help="Read all catalog models/efforts; no generation").set_defaults(func=cmd_discover)
    preflight = sub.add_parser("preflight", help="Check isolated native goal APIs with paused goals; no audio or model turns")
    preflight.add_argument("--preset", default="sol-astra-goal")
    preflight.set_defaults(func=cmd_preflight)
    prep = sub.add_parser("prepare", help="Add any song or excerpt to the reusable library")
    prep.add_argument("--audio", required=True)
    prep.add_argument("--song", help="Stable folder ID; defaults to a slug of the title")
    prep.add_argument("--title", help="Track title; defaults to the source filename")
    prep.add_argument("--artist", help="Optional artist metadata; otherwise left unknown")
    prep.add_argument("--start", type=float, default=0)
    prep.add_argument("--duration", type=positive_float, help="Excerpt length; omit to use the remaining audio")
    prep.add_argument("--bpm", type=positive_float)
    prep.add_argument("--cues", help="Verified JSON sections/lyrics relative to excerpt zero")
    prep.add_argument("--license-note")
    prep.set_defaults(func=cmd_prepare)
    plan = sub.add_parser("plan", help="Freeze identical inputs and a model/effort matrix")
    plan.add_argument("--efforts", choices=["all", "default"], default="all")
    plan.add_argument("--models", nargs="+", help="Exact model IDs from discover; default includes every visible catalog model")
    plan.add_argument("--include-hidden", action="store_true", help="Also plan hidden specialist/internal entries; these may reject general tasks")
    plan.add_argument("--repeats", type=positive_int, default=1)
    plan.add_argument("--preset", help="Exact condition preset, e.g. sol-astra-goal")
    song_choice = plan.add_mutually_exclusive_group()
    song_choice.add_argument("--song", help="Prepared song ID; optional if exactly one song exists")
    song_choice.add_argument("--demo", action="store_true", help="Explicitly use synthetic diagnostic audio")
    plan.set_defaults(func=cmd_plan)
    run = sub.add_parser("run", help="Print commands; --execute starts model sessions")
    run.add_argument("--experiment", required=True)
    run.add_argument("--execute", action="store_true")
    run.add_argument("--only", nargs="+", help="Run IDs, e.g. run-001")
    run.add_argument("--limit", type=positive_int)
    run.add_argument("--seconds", type=positive_float, default=7200, help="Hard wall-clock limit per session")
    run.add_argument("--total-seconds", type=positive_float, default=43200, help="Wall-clock limit for this invocation")
    run.add_argument("--retry-failed", action="store_true", help="Retry failures in a fresh attempt folder")
    run.set_defaults(func=cmd_run)
    report = sub.add_parser("report", help="Rebuild CSV and review exports without model calls")
    report.add_argument("--experiment", required=True)
    report.set_defaults(func=cmd_report)
    sub.add_parser("smoke", help="Render and validate a 3-second synthetic fixture; no model calls").set_defaults(func=cmd_smoke)
    args = parser.parse_args()
    try:
        args.func(args)
    except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
