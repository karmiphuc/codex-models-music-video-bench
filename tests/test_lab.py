"""Offline tests: synthetic media + simulated agent, never a paid model call."""
import argparse
from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from lab.catalog import discover, matrix
from lab.media import demo_audio, prepare_audio, validate_video

REPO = Path(__file__).resolve().parents[1]
loader = importlib.util.spec_from_file_location("lab_cli", REPO / "lab.py")
cli = importlib.util.module_from_spec(loader)
loader.loader.exec_module(cli)


class CatalogTests(unittest.TestCase):
    def test_nonstandard_efforts_are_preserved_and_unavailable_models_rejected(self):
        models = [
            {"model": "a", "defaultReasoningEffort": "deep", "supportedReasoningEfforts": [
                {"reasoningEffort": "quick"}, {"reasoningEffort": "deep"}]},
            {"model": "b", "defaultReasoningEffort": None, "supportedReasoningEfforts": []},
        ]
        self.assertEqual([(r["model"], r["effort"]) for r in matrix(models)],
                         [("a", "quick"), ("a", "deep"), ("b", None)])
        self.assertEqual(len(matrix(models, "default", repeats=3)), 6)
        with self.assertRaises(ValueError):
            matrix(models, selected=["not-in-account"])

    @unittest.skipUnless(os.name == "posix", "Executable script fixture")
    def test_rpc_handshake_and_pagination(self):
        with tempfile.TemporaryDirectory() as temp:
            executable = Path(temp) / "fake-codex"
            executable.write_text(f"#!{sys.executable}\n" + '''
import json, sys
initialized = False
for line in sys.stdin:
    msg = json.loads(line)
    if msg['method'] == 'initialize':
        response = {'userAgent':'test'}
    elif msg['method'] == 'initialized':
        initialized = True
        continue
    else:
        assert initialized and msg['params']['includeHidden']
        cursor = msg['params'].get('cursor')
        response = {'data':[{'model':'b' if cursor else 'a'}], 'nextCursor':None if cursor else 'page2'}
    print(json.dumps({'id':msg['id'], 'result':response}), flush=True)
''')
            executable.chmod(0o755)
            self.assertEqual([m["model"] for m in discover(str(executable), timeout=5)], ["a", "b"])


class MediaTests(unittest.TestCase):
    def test_excerpt_bounds_and_unknown_lyrics(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            demo_audio(root / "source.wav", duration=2)
            with self.assertRaises(ValueError):
                prepare_audio(root / "source.wav", root / "bad", 1, 5)
            with self.assertRaises(ValueError):
                prepare_audio(root / "source.wav", root / "nan", float("nan"), 1)
            self.assertFalse((root / "bad").exists())
            summary = prepare_audio(root / "source.wav", root / "good", 0.5, 1, demo=True)
            self.assertAlmostEqual(summary["duration_seconds"], 1, places=3)
            self.assertIsNone(summary["bpm"])
            self.assertEqual(summary["lyrics"], [])
            with self.assertRaises(FileExistsError):
                prepare_audio(root / "source.wav", root / "good", 0, 1)
            self.assertFalse(validate_video(root / "missing.mp4", {"fps": 30})["passed"])

    def test_usage_ignores_unfinished_turns_and_does_not_double_count_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "events.jsonl"
            path.write_text('\n'.join([
                'not json', '{"type":"thread.started"}',
                '{"type":"turn.completed","usage":{"input_tokens":100,"cached_input_tokens":60,"output_tokens":20}}',
                '{"type":"turn.completed","usage":{"input_tokens":50,"cached_input_tokens":10,"output_tokens":5}}',
                '{"type":"turn.failed"}',
            ]))
            result = cli.usage_from_events(path)
            self.assertEqual(result["usage"], {"input_tokens": 150, "cached_input_tokens": 70, "output_tokens": 25})
            self.assertTrue(result["event_failure"])
            path.write_text('{"type":"thread.started"}\n')
            self.assertIsNone(cli.usage_from_events(path)["usage"])


class RunnerTests(unittest.TestCase):
    def test_multiple_future_songs_keep_metadata_and_frozen_plans_separate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ["template", "lab", "prompts"]:
                shutil.copytree(REPO / name, root / name, ignore=shutil.ignore_patterns("__pycache__"))
            for name in ["experiment.json", "requirements.txt"]:
                shutil.copy2(REPO / name, root / name)
            demo_audio(root / "Future Song.wav", duration=2)
            catalog = {"models": [{"model": "fixture", "hidden": False,
                                   "supportedReasoningEfforts": [{"reasoningEffort": "deep"}]}]}
            cli.write(root / "catalog.json", catalog)
            prep = argparse.Namespace(audio=str(root / "Future Song.wav"), title="Future Song",
                                      artist="Future Artist", song=None, start=0, duration=None,
                                      bpm=None, cues=None, license_note=None)
            plan = argparse.Namespace(song="future-song", demo=False, include_hidden=False,
                                      models=None, efforts="all", repeats=1)
            with patch.object(cli, "ROOT", root), patch.object(cli, "environment", return_value={}), \
                    redirect_stdout(io.StringIO()):
                # A blank setup requires no song; choosing a real plan waits for an input.
                self.assertEqual(cli.prepared_songs(), [])
                with self.assertRaisesRegex(ValueError, "No song prepared"):
                    cli.select_song()
                cli.cmd_prepare(prep)
                first = cli.select_song()
                first_map = cli.read(first / "audio-map.json")
                self.assertEqual(first.name, "future-song")
                self.assertEqual(first_map["track"], "Future Song")
                self.assertEqual(first_map["artist"], "Future Artist")
                self.assertAlmostEqual(first_map["duration_seconds"], 2, places=3)
                cli.cmd_plan(plan)
                frozen = next((root / "experiments").glob("future-song-*/manifest.json"))
                self.assertEqual(cli.read(frozen)["spec"]["track"], "Future Song")
                frozen_hash = cli.file_hash(frozen)
                # A second song uses a new ID and can select all audio after an offset.
                prep.song, prep.title, prep.artist, prep.start = "another-song", "Another Song", None, 0.5
                cli.cmd_prepare(prep)
                second_map = cli.read(cli.select_song("another-song") / "audio-map.json")
                self.assertAlmostEqual(second_map["duration_seconds"], 1.5, places=3)
                self.assertIsNone(second_map["artist"])
                with self.assertRaisesRegex(ValueError, "Choose a prepared track"):
                    cli.select_song()
                plan.song = "another-song"
                cli.cmd_plan(plan)
                second = next((root / "experiments").glob("another-song-*/manifest.json"))
                self.assertEqual(cli.read(second)["spec"]["track"], "Another Song")
                self.assertEqual((second.parent / "seed/TASK.txt").read_bytes(),
                                 (frozen.parent / "seed/TASK.txt").read_bytes())
                self.assertEqual(cli.file_hash(frozen), frozen_hash)
                with self.assertRaises(ValueError):
                    cli.select_song("../escape")

    def test_dry_run_resume_retry_and_reports_with_simulated_agent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            demo_audio(root / "source.wav", duration=1)
            prepared = root / "prepared"
            prepare_audio(root / "source.wav", prepared, 0, 1, bpm=100, demo=True)
            experiment = root / "experiment"
            experiment.mkdir()
            spec = {"width": 320, "height": 180, "fps": 24, "duration_seconds": 1}
            cli.seed_project(experiment / "seed", prepared, spec)
            manifest = {"environment": {"fixture": True}, "spec": spec,
                        "seed_sha256": cli.tree_hashes(experiment / "seed"),
                        "runs": [{"id": "run-001", "model": "fixture", "effort": "deep", "repeat": 1}]}
            cli.write(experiment / "manifest.json", manifest)
            agent = root / "fake_agent.py"
            agent.write_text('''
import json, pathlib, subprocess, sys, time
work = pathlib.Path(sys.argv[1])
if sys.argv[2] == 'timeout':
    time.sleep(30)
    raise SystemExit()
scene = work/'scene.py'
scene.write_text(scene.read_text().replace('#61dfc2', '#f1bf62'))
subprocess.run([sys.executable, 'render.py'], cwd=work, check=True, stdout=sys.stderr)
subprocess.run([sys.executable, 'postprocess.py'], cwd=work, check=True, stdout=sys.stderr)
(work/'storyboard.json').write_text('[{"start":0,"end":1,"description":"Offline fixture"}]')
(work/'output/qa.md').write_text('Simulated agent integration fixture only.')
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':10,'cached_input_tokens':2,'output_tokens':3}}))
''')
            mode = "success"

            def fake_command(work, row, attempt):
                return [sys.executable, str(agent), str(work), mode]

            args = argparse.Namespace(experiment=str(experiment), only=None, limit=None,
                                      execute=False, retry_failed=False, seconds=30, total_seconds=60)
            with patch.object(cli, "environment", return_value={"fixture": True}), \
                    patch.object(cli, "command", side_effect=fake_command), redirect_stdout(io.StringIO()):
                cli.cmd_run(args)
                self.assertFalse((experiment / "runs").exists(), "Dry run must not start an agent")
                args.execute = True
                cli.cmd_run(args)
                attempt = experiment / "runs/run-001/attempt-001"
                self.assertEqual(cli.read(attempt / "metrics.json")["status"], "complete")
                self.assertTrue(cli.read(attempt / "validation.json")["passed"])
                scores = experiment / "review-scores.csv"
                original = scores.read_text().replace(",,,,,,,", ",5,4,3,4,5,4,keep this human note")
                scores.write_text(original)
                cli.cmd_run(args)
                self.assertEqual(len(list((experiment / "runs/run-001").iterdir())), 1)
                self.assertEqual(scores.read_text(), original)
                # An unsuccessful condition retries from the original seed, not its old work.
                metrics = cli.read(attempt / "metrics.json")
                metrics["status"] = "failed"
                cli.write(attempt / "metrics.json", metrics)
                (attempt / "work/scene.py").write_text("raise RuntimeError('contaminated')")
                args.retry_failed = True
                cli.cmd_run(args)
                second = experiment / "runs/run-001/attempt-002"
                self.assertEqual(cli.read(second / "metrics.json")["status"], "complete")
                self.assertTrue(cli.read(second / "metrics.json")["baseline_matches"])
                # Seed tampering blocks execution.
                (experiment / "seed/spec.json").write_text('{}')
                with self.assertRaisesRegex(ValueError, "Frozen seed changed"):
                    cli.cmd_run(args)

    @unittest.skipUnless(os.name == "posix", "Process group timeout test")
    def test_timeout_stops_render_children(self):
        import time
        with tempfile.TemporaryDirectory() as temp:
            marker = Path(temp) / "child-finished"
            child_code = f"import time,pathlib; time.sleep(1); pathlib.Path({str(marker)!r}).touch()"
            parent_code = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child_code!r}]); time.sleep(30)"
            process = subprocess.Popen([sys.executable, "-c", parent_code], start_new_session=True)
            time.sleep(0.15)
            cli.stop_process(process)
            time.sleep(1.1)
            self.assertFalse(marker.exists(), "Render child outlived the process group timeout")


if __name__ == "__main__":
    unittest.main()
