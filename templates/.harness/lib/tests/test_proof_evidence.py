from __future__ import annotations
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODULE_PATH = HERE.parent / "proof_evidence.py"
SPEC = importlib.util.spec_from_file_location("proof_evidence", MODULE_PATH)
assert SPEC and SPEC.loader
proof = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(proof)


class ProofEvidenceTests(unittest.TestCase):
    def test_valid_command_manifest_and_reject_failed_record(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
            (root / "seed").write_text("x")
            subprocess.run(["git", "add", "seed"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "seed"], cwd=root, check=True)
            manifest = root / "proof.json"
            old = Path.cwd()
            try:
                import os
                os.chdir(root)
                test_file = root / "test_sample.py"
                test_file.write_text("import unittest\nclass T(unittest.TestCase):\n def test_ok(self): self.assertTrue(True)\n")
                subprocess.run(["git", "add", "test_sample.py"], cwd=root, check=True)
                subprocess.run(["git", "commit", "-qm", "test"], cwd=root, check=True)
                args = type("Args", (), {"id": "T1", "type": "test", "manifest": "proof.json", "command": ["--", sys.executable, "-m", "unittest", "test_sample", "-v"]})
                self.assertEqual(proof.run(args), 0)
            finally:
                os.chdir(old)
            self.assertTrue(proof.verify_manifest(manifest, root)[0])
            data = json.loads(manifest.read_text())
            data["records"][0]["exit_code"] = 1
            manifest.write_text(json.dumps(data))
            self.assertTrue(proof.verify_manifest(manifest, root)[0])
            self.assertEqual(proof.summary(manifest, root), (0, 1, ["T1"]))

    def test_irrelevant_trivial_command_is_rejected(self) -> None:
        args = type("Args", (), {"id": "T1", "type": "test", "manifest": "proof.json", "command": ["--", "true"]})
        with self.assertRaises(SystemExit):
            proof.run(args)

    def test_python_pass_and_help_are_semantically_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
            (root / "seed").write_text("x")
            subprocess.run(["git", "add", "seed"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "seed"], cwd=root, check=True)
            import os
            old = Path.cwd()
            try:
                os.chdir(root)
                for index, command in enumerate(([sys.executable, "-c", "pass"], [sys.executable, "-c", "print('1 passed')"], [sys.executable, "-m", "unittest", "-h"])):
                    args = type("Args", (), {"id": f"F{index}", "type": "test", "manifest": "proof.json", "command": ["--", *command]})
                    self.assertEqual(proof.run(args), 2)
            finally:
                os.chdir(old)


if __name__ == "__main__":
    unittest.main()
