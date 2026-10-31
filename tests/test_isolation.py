"""No model calls: validate the exact matrix and actual filesystem isolation."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from lab.catalog import preset_matrix
from lab.isolation import goal_command, verify_namespace


class IsolationTests(unittest.TestCase):
    def test_requested_preset_is_exact_and_rejects_unsupported_conditions(self):
        root = Path(__file__).resolve().parents[1]
        preset = json.loads((root / "presets/sol-astra-goal.json").read_text())
        expected = [("gpt-6.1-sol", e) for e in ["medium", "high", "max", "ultra"]]
        expected += [("gpt-6-astra", e) for e in ["high", "max"]]
        self.assertEqual([(c["model"], c["effort"]) for c in preset["conditions"]], expected)
        catalog = [{"model": model, "supportedReasoningEfforts": [{"reasoningEffort": e} for e in efforts]}
                   for model, efforts in [("gpt-6.1-sol", ["medium", "high", "max", "ultra"]), ("gpt-6-astra", ["high", "max"])]]
        self.assertEqual(len(preset_matrix(catalog, preset["conditions"])), 6)
        with self.assertRaisesRegex(ValueError, "not advertised"):
            preset_matrix(catalog, [{"model": "gpt-6-astra", "effort": "ultra"}])

    @unittest.skipUnless(os.name == "posix" and shutil.which("bwrap"), "Linux bubblewrap required")
    def test_dry_command_does_not_create_state_or_expose_selectors(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            command = goal_command(root / "work", root / "home", 30, prepare=False)
            self.assertFalse((root / "home").exists())
            self.assertNotIn("--model", command)
            self.assertNotIn("--effort", command)
            self.assertIn("--unshare-pid", command)
            self.assertIn("/workspace/run", command)

    @unittest.skipUnless(os.name == "posix" and shutil.which("bwrap"), "Linux bubblewrap required")
    def test_real_namespace_hides_sibling_runs_and_existing_home(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            work = root / "work"
            work.mkdir()
            (root / "manifest.json").write_text('{"poison":"must remain invisible"}')
            (root / "other-run").mkdir()
            auth = root / "fixture-auth.json"
            auth.write_text('{}')
            try:
                result = json.loads(verify_namespace(work, root / "home", auth_file=auth))
            except subprocess.CalledProcessError as error:
                if any(s in (error.stderr or "") for s in ["Operation not permitted", "No permissions to create", "setting up uid map: Permission denied"]):
                    self.skipTest("Host kernel does not permit unprivileged namespaces; actual goal run fails closed")
                raise AssertionError("Bubblewrap isolation check failed: " + (error.stderr or str(error))) from error
            self.assertTrue(result["filesystem_isolated"])
            self.assertEqual(result["cwd"], "/workspace/run")


if __name__ == "__main__":
    unittest.main()
