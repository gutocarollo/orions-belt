from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


class IsolatedDistributionTest(unittest.TestCase):
    def test_release_passes_from_materializable_checkout_without_hosted_ci(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orions-isolated-release-") as raw:
            checkout = Path(raw) / "checkout"
            subprocess.run(
                ["git", "clone", "-q", "--no-hardlinks", str(ROOT), str(checkout)], check=True
            )
            diff = subprocess.run(
                ["git", "diff", "--binary", "HEAD", "--"], cwd=ROOT, check=True, capture_output=True
            ).stdout
            subprocess.run(
                ["git", "apply", "--whitespace=nowarn"], cwd=checkout, input=diff, check=True
            )
            untracked = subprocess.run(
                ["git", "ls-files", "--others", "--exclude-standard", "-z"],
                cwd=ROOT, check=True, capture_output=True,
            ).stdout.decode("utf-8", errors="surrogateescape").split("\0")
            for relative in filter(None, untracked):
                source, destination = ROOT / relative, checkout / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                if source.is_dir():
                    shutil.copytree(source, destination, dirs_exist_ok=True, symlinks=True)
                else:
                    shutil.copy2(source, destination, follow_symlinks=False)

            report_path = checkout / "isolated-release.json"
            process = subprocess.run(
                ["python3", "engine/release_check.py", "--output", str(report_path)],
                cwd=checkout, capture_output=True, text=True, timeout=1_200, check=False,
            )
            self.assertEqual(0, process.returncode, process.stdout[-4_000:] + process.stderr[-4_000:])
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(("PASS", 20, 0), (report["status"], report["passed"], report["failed"]))
            self.assertFalse((checkout / ".github/workflows/release-check.yml").exists())


if __name__ == "__main__":
    unittest.main()
