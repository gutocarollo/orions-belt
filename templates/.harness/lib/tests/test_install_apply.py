from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
LIB = HERE.parent
SPEC = importlib.util.spec_from_file_location("install_apply", LIB / "install_apply.py")
assert SPEC and SPEC.loader
install_apply = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = install_apply
SPEC.loader.exec_module(install_apply)


class InstallApplyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="install-apply-test-")
        self.root = Path(self.tmp.name)
        self.scratch = self.root / "scratch"
        self.target = self.root / "target"
        self.external = self.root / "external"
        self.scratch.mkdir()
        self.target.mkdir()
        self.external.mkdir()
        (self.scratch / ".harness/lib").mkdir(parents=True)
        shutil.copy2(LIB / "merge_docs.py", self.scratch / ".harness/lib/merge_docs.py")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def source(self, rel: str, content: str) -> None:
        path = self.scratch / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def apply(
        self,
        *,
        dry_run: bool = False,
        fail_after: int | None = None,
        preserve: list[str] | None = None,
    ) -> int:
        previous = os.environ.get("ORIONS_BELT_FAIL_AFTER")
        try:
            if fail_after is None:
                os.environ.pop("ORIONS_BELT_FAIL_AFTER", None)
            else:
                os.environ["ORIONS_BELT_FAIL_AFTER"] = str(fail_after)
            args = ["--scratch", str(self.scratch), "--target", str(self.target)]
            if dry_run:
                args.append("--dry-run")
            for path in preserve or []:
                args.extend(("--preserve", path))
            return install_apply.main(args)
        finally:
            if previous is None:
                os.environ.pop("ORIONS_BELT_FAIL_AFTER", None)
            else:
                os.environ["ORIONS_BELT_FAIL_AFTER"] = previous

    def manifest(self) -> dict:
        return json.loads((self.target / ".harness/install-manifest.json").read_text())

    def test_greenfield_creates_files_and_manifest(self) -> None:
        self.source("owned.txt", "v1\n")
        self.assertEqual(self.apply(), 0)
        self.assertEqual((self.target / "owned.txt").read_text(), "v1\n")
        entry = self.manifest()["files"]["owned.txt"]
        self.assertEqual(entry["strategy"], "owned")
        self.assertEqual(len(entry["last_applied_sha256"]), 64)

    def test_owned_mode_drift_is_repaired(self) -> None:
        self.source("tool.sh", "#!/bin/sh\nexit 0\n")
        source = self.scratch / "tool.sh"
        source.chmod(0o755)
        self.assertEqual(self.apply(), 0)
        installed = self.target / "tool.sh"
        installed.chmod(0o644)
        self.assertEqual(self.apply(), 0)
        self.assertEqual(stat.S_IMODE(installed.stat().st_mode), 0o755)
        self.assertEqual(self.manifest()["files"]["tool.sh"]["mode"], "0o755")

    def test_unknown_collision_aborts_before_any_write(self) -> None:
        self.source("a-new.txt", "new\n")
        self.source("z-collision.txt", "harness\n")
        (self.target / "z-collision.txt").write_text("user\n")
        self.assertEqual(self.apply(), 2)
        self.assertFalse((self.target / "a-new.txt").exists())
        self.assertEqual((self.target / "z-collision.txt").read_text(), "user\n")
        self.assertFalse((self.target / ".harness/install-manifest.json").exists())

    def test_plan_output_parent_symlink_cannot_write_inside_target(self) -> None:
        self.source("owned.txt", "v1\n")
        through = self.external / "through"
        through.symlink_to(self.target, target_is_directory=True)
        rc = install_apply.main([
            "--scratch", str(self.scratch), "--target", str(self.target),
            "--dry-run", "--plan-json", str(through / "plan.json"),
        ])
        self.assertEqual(rc, 2)
        self.assertFalse((self.target / "plan.json").exists())

    def test_exact_existing_content_is_safely_adopted(self) -> None:
        self.source("same.txt", "same\n")
        (self.target / "same.txt").write_text("same\n")
        self.assertEqual(self.apply(), 0)
        self.assertIn("same.txt", self.manifest()["files"])

    def test_explicit_preserve_keeps_unowned_path_across_updates(self) -> None:
        self.source("custom-skill.md", "harness version\n")
        (self.target / "custom-skill.md").write_text("project version\n")
        self.assertEqual(self.apply(preserve=["custom-skill.md"]), 0)
        self.assertEqual((self.target / "custom-skill.md").read_text(), "project version\n")
        self.assertEqual(self.manifest()["files"]["custom-skill.md"]["strategy"], "preserve")
        self.source("custom-skill.md", "harness v2\n")
        (self.target / "custom-skill.md").write_text("project edited\n")
        self.assertEqual(self.apply(), 0)
        self.assertEqual((self.target / "custom-skill.md").read_text(), "project edited\n")

    def test_living_seed_is_created_then_local_edits_survive_updates(self) -> None:
        self.source("tasks/lessons.md", "seed\n")
        self.assertEqual(self.apply(), 0)
        living = self.target / "tasks/lessons.md"
        self.assertEqual(living.read_text(), "seed\n")
        living.write_text("local learning\n")
        self.source("tasks/lessons.md", "new upstream seed\n")
        self.assertEqual(self.apply(), 0)
        self.assertEqual(living.read_text(), "local learning\n")
        self.assertEqual(self.manifest()["files"]["tasks/lessons.md"]["strategy"], "seed")

    def test_retired_author_qa_is_pruned_from_manifest(self) -> None:
        retired = "tests/test_install_report.sh"
        self.source(retired, "old\n")
        self.assertEqual(self.apply(), 0)
        (self.scratch / retired).unlink()
        (self.target / retired).unlink()
        self.assertEqual(self.apply(), 0)
        self.assertNotIn(retired, self.manifest()["files"])

    def test_preserve_path_missing_from_render_is_an_error(self) -> None:
        self.source("owned.txt", "v1\n")
        self.assertEqual(self.apply(preserve=["absent.txt"]), 2)
        self.assertEqual(list(self.target.iterdir()), [])

    def test_owned_file_updates_but_local_edit_conflicts(self) -> None:
        self.source("owned.txt", "v1\n")
        self.assertEqual(self.apply(), 0)
        self.source("owned.txt", "v2\n")
        self.assertEqual(self.apply(), 0)
        self.assertEqual((self.target / "owned.txt").read_text(), "v2\n")
        (self.target / "owned.txt").write_text("local\n")
        self.source("owned.txt", "v3\n")
        self.assertEqual(self.apply(), 2)
        self.assertEqual((self.target / "owned.txt").read_text(), "local\n")

    def test_sensitive_marked_block_preserves_user_content(self) -> None:
        self.source("AGENTS.md", "# Harness v1\n")
        (self.target / "AGENTS.md").write_text("# User\nkeep me\n")
        self.assertEqual(self.apply(), 0)
        first = (self.target / "AGENTS.md").read_text()
        self.assertIn("keep me", first)
        self.assertIn("# Harness v1", first)
        self.source("AGENTS.md", "# Harness v2\n")
        self.assertEqual(self.apply(), 0)
        second = (self.target / "AGENTS.md").read_text()
        self.assertIn("keep me", second)
        self.assertNotIn("# Harness v1", second)
        self.assertEqual(second.count("orions-belt:begin"), 1)

    def test_settings_ownership_inventory_preserves_same_namespace_external_hook(self) -> None:
        external_command = "bash .harness/hooks/my-company-security.sh"
        harness_v1 = "python3 .harness/hooks/completion-gate-v1.py"
        harness_v2 = "python3 .harness/hooks/completion-gate-v2.py"

        def settings(command: str) -> str:
            return json.dumps({"hooks": {"Stop": [{"hooks": [
                {"type": "command", "command": command},
            ]}]}})

        self.source(".claude/settings.json", settings(harness_v1))
        target_settings = self.target / ".claude/settings.json"
        target_settings.parent.mkdir(parents=True)
        target_settings.write_text(settings(external_command))
        self.assertEqual(self.apply(), 0)
        first = json.loads(target_settings.read_text())
        first_commands = [h["command"] for g in first["hooks"]["Stop"] for h in g["hooks"]]
        self.assertEqual(set(first_commands), {external_command, harness_v1})
        inventory = self.manifest()["files"][".claude/settings.json"]["owned_hook_identities"]
        self.assertEqual(len(inventory), 1)
        self.assertIn(harness_v1, inventory[0])

        self.source(".claude/settings.json", settings(harness_v2))
        self.assertEqual(self.apply(), 0)
        second = json.loads(target_settings.read_text())
        second_commands = [h["command"] for g in second["hooks"]["Stop"] for h in g["hooks"]]
        self.assertEqual(set(second_commands), {external_command, harness_v2})
        self.assertNotIn(harness_v1, second_commands)

    def test_same_command_in_an_external_event_is_preserved(self) -> None:
        command = "bash .harness/hooks/shared.sh"
        self.source(".claude/settings.json", json.dumps({
            "hooks": {"Stop": [{"matcher": "", "hooks": [{"type": "command", "command": command}]}]},
        }))
        target_settings = self.target / ".claude/settings.json"
        target_settings.parent.mkdir(parents=True)
        target_settings.write_text(json.dumps({
            "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": command}]}]},
        }))
        self.assertEqual(self.apply(), 0)
        data = json.loads(target_settings.read_text())
        self.assertIn("PreToolUse", data["hooks"])
        self.assertIn("Stop", data["hooks"])

    def test_malformed_settings_schema_returns_controlled_error(self) -> None:
        self.source(".claude/settings.json", json.dumps({
            "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "true"}]}]},
        }))
        target_settings = self.target / ".claude/settings.json"
        target_settings.parent.mkdir(parents=True)
        target_settings.write_text('{"hooks": []}')
        self.assertEqual(self.apply(), 2)
        self.assertEqual(target_settings.read_text(), '{"hooks": []}')

    def test_symlinked_parent_is_fatal_and_external_is_untouched(self) -> None:
        self.source(".codex/agents/reviewer.toml", "model = 'x'\n")
        (self.target / ".codex").symlink_to(self.external, target_is_directory=True)
        before = sorted(self.external.rglob("*"))
        self.assertEqual(self.apply(), 2)
        self.assertEqual(sorted(self.external.rglob("*")), before)
        self.assertTrue((self.target / ".codex").is_symlink())

    def test_destination_symlink_is_fatal_and_preserved(self) -> None:
        self.source("AGENTS.md", "# Harness\n")
        external_file = self.external / "AGENTS.md"
        external_file.write_text("central\n")
        (self.target / "AGENTS.md").symlink_to(external_file)
        self.assertEqual(self.apply(), 2)
        self.assertTrue((self.target / "AGENTS.md").is_symlink())
        self.assertEqual(external_file.read_text(), "central\n")

    def test_dry_run_does_not_write(self) -> None:
        self.source("new.txt", "new\n")
        self.assertEqual(self.apply(dry_run=True), 0)
        self.assertEqual(list(self.target.iterdir()), [])

    def test_dry_run_refuses_pending_journal_without_recovery(self) -> None:
        self.source("owned.txt", "v1\n")
        run_id = "a" * 32
        backup = self.target / ".harness/install-backups" / run_id
        backup.mkdir(parents=True)
        journal = self.target / ".harness/install-journal.json"
        journal.write_text(json.dumps({
            "version": install_apply.JOURNAL_VERSION,
            "backup_root": str(backup),
            "entries": [],
        }))
        before = journal.read_bytes()
        self.assertEqual(self.apply(dry_run=True), 2)
        self.assertEqual(journal.read_bytes(), before)
        self.assertTrue(backup.is_dir())

    def test_plan_output_inside_target_is_rejected_without_write(self) -> None:
        self.source("new.txt", "new\n")
        rc = install_apply.main([
            "--scratch", str(self.scratch),
            "--target", str(self.target),
            "--dry-run",
            "--plan-json", str(self.target / ".harness/plan.json"),
        ])
        self.assertEqual(rc, 2)
        self.assertEqual(list(self.target.iterdir()), [])

    def test_first_install_failure_restores_exact_empty_target(self) -> None:
        self.source("nested/a.txt", "a1\n")
        self.source("nested/b.txt", "b1\n")
        self.assertEqual(self.apply(fail_after=1), 2)
        self.assertEqual(list(self.target.iterdir()), [])

    def test_rollback_preserves_preexisting_empty_directory(self) -> None:
        existing_dir = self.target / "preexisting-empty"
        existing_dir.mkdir()
        self.source("preexisting-empty/a.txt", "a\n")
        self.assertEqual(self.apply(fail_after=1), 2)
        self.assertTrue(existing_dir.is_dir())
        self.assertEqual(list(existing_dir.iterdir()), [])

    def test_edit_between_plan_and_apply_is_not_overwritten(self) -> None:
        self.source("owned.txt", "v1\n")
        self.assertEqual(self.apply(), 0)
        self.source("owned.txt", "v2\n")
        manifest = install_apply.load_manifest(self.target)
        plan = install_apply.build_plan(self.scratch, self.target, manifest)
        destination = self.target / "owned.txt"
        destination.write_text("user-after-plan\n")
        next_manifest = install_apply.manifest_for(plan, manifest, {})
        with self.assertRaises(install_apply.InstallError):
            install_apply.apply_plan(plan, self.target, next_manifest)
        self.assertEqual(destination.read_text(), "user-after-plan\n")

    def test_pinned_root_cannot_be_redirected_by_parent_symlink_swap(self) -> None:
        self.source("owned.txt", "anchored\n")
        moved = self.root / "target-moved"
        original_identity = install_apply.target_identity(self.target)
        with install_apply.pinned_target(self.target) as anchored:
            self.assertIsInstance(anchored, install_apply.TargetRoot)
            self.target.rename(moved)
            self.target.symlink_to(self.external, target_is_directory=True)
            manifest = install_apply.load_manifest(anchored)
            plan = install_apply.build_plan(self.scratch, anchored, manifest)
            install_apply.apply_plan(
                plan, anchored, install_apply.manifest_for(plan, manifest, {})
            )
            with self.assertRaises(install_apply.InstallError):
                install_apply.assert_target_identity(self.target, original_identity)
        self.assertFalse((self.external / "owned.txt").exists())
        self.assertEqual((moved / "owned.txt").read_text(), "anchored\n")
        self.target.unlink()
        moved.rename(self.target)

    def test_intermediate_directory_symlink_swap_is_rejected(self) -> None:
        self.source("nested/owned.txt", "anchored\n")
        manifest = install_apply.load_manifest(self.target)
        plan = install_apply.build_plan(self.scratch, self.target, manifest)
        nested = self.target / "nested"
        moved = self.root / "nested-before-swap"
        nested.mkdir()
        nested.rename(moved)
        nested.symlink_to(self.external, target_is_directory=True)

        with self.assertRaises(install_apply.InstallError):
            install_apply.apply_plan(
                plan, self.target, install_apply.manifest_for(plan, manifest, {})
            )

        self.assertFalse((self.external / "owned.txt").exists())
        self.assertEqual(list(moved.iterdir()), [])

    def test_tampered_journal_cannot_delete_external_backup_root(self) -> None:
        victim = self.root / "victim"
        victim.mkdir()
        (victim / "owned.txt").write_text("external-data\n")
        journal = self.target / ".harness/install-journal.json"
        journal.parent.mkdir(parents=True)
        journal.write_text(json.dumps({
            "version": install_apply.JOURNAL_VERSION,
            "backup_root": str(self.target / ".." / "victim"),
            "entries": [],
        }))
        self.assertEqual(self.apply(), 2)
        self.assertEqual((victim / "owned.txt").read_text(), "external-data\n")
        self.assertTrue(victim.is_dir())
        self.assertFalse((self.target / "owned.txt").exists())

    def test_tampered_journal_rejects_symlinked_backup_run(self) -> None:
        run_id = "a" * 32
        backup_parent = self.target / ".harness/install-backups"
        backup_parent.mkdir(parents=True)
        (backup_parent / run_id).symlink_to(self.external, target_is_directory=True)
        journal = self.target / ".harness/install-journal.json"
        journal.write_text(json.dumps({
            "version": install_apply.JOURNAL_VERSION,
            "backup_root": f".harness/install-backups/{run_id}",
            "entries": [],
        }))
        self.assertEqual(self.apply(), 2)
        self.assertEqual(list(self.external.iterdir()), [])

    def test_injected_failure_rolls_back_files_and_manifest(self) -> None:
        self.source("a.txt", "a1\n")
        self.source("b.txt", "b1\n")
        self.assertEqual(self.apply(), 0)
        manifest_before = (self.target / ".harness/install-manifest.json").read_bytes()
        self.source("a.txt", "a2\n")
        self.source("b.txt", "b2\n")
        self.assertEqual(self.apply(fail_after=1), 2)
        self.assertEqual((self.target / "a.txt").read_text(), "a1\n")
        self.assertEqual((self.target / "b.txt").read_text(), "b1\n")
        self.assertEqual((self.target / ".harness/install-manifest.json").read_bytes(), manifest_before)
        self.assertFalse((self.target / ".harness/install-journal.json").exists())

    def test_recovery_refuses_to_overwrite_a_post_crash_edit(self) -> None:
        self.source("owned.txt", "before\n")
        self.assertEqual(self.apply(), 0)
        destination = self.target / "owned.txt"
        before = destination.read_bytes()
        before_mode = stat.S_IMODE(destination.stat().st_mode)
        after = b"transaction\n"
        run_id = "b" * 32
        backup_root = self.target / ".harness/install-backups" / run_id
        backup = backup_root / "owned.txt"
        backup.parent.mkdir(parents=True)
        backup.write_bytes(before)
        destination.write_text("user-after-crash\n")
        journal = self.target / ".harness/install-journal.json"
        journal.write_text(json.dumps({
            "version": install_apply.JOURNAL_VERSION,
            "backup_root": f".harness/install-backups/{run_id}",
            "entries": [{
                "path": "owned.txt",
                "existed": True,
                "before_sha256": install_apply.sha256_bytes(before),
                "before_mode": oct(before_mode),
                "after_sha256": install_apply.sha256_bytes(after),
                "after_mode": "0o644",
            }],
        }))
        self.assertEqual(self.apply(), 2)
        self.assertEqual(destination.read_text(), "user-after-crash\n")
        self.assertTrue(journal.exists())


if __name__ == "__main__":
    unittest.main()
