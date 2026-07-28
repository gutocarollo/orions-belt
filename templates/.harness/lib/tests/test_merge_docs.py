#!/usr/bin/env python3
"""test_merge_docs.py — proof of NON-destructive merge (F5).

Real gate (00-plano-consolidado.md §6-F5): "NON-destructive merge of a
preexisting CLAUDE.md" — writes a CLAUDE.md with 2-3 real lines, runs the
merge, confirms the original was not overwritten (diff shows append, not
replace) and that running again does not duplicate the block (idempotency).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "merge_docs.py"


def _run(args: list[str]) -> dict:
    proc = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, timeout=15)
    assert proc.returncode == 0, f"merge_docs.py falhou: {proc.stderr}"
    return json.loads(proc.stdout)


class MergeMarkdownTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="merge-docs-test-"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_creates_fresh_file_when_absent(self) -> None:
        new = self.tmpdir / "new.md"
        new.write_text("# Novo conteúdo do harness\n", encoding="utf-8")
        target = self.tmpdir / "CLAUDE.md"
        result = _run(["markdown", "--existing", str(target), "--new", str(new)])
        self.assertEqual(result["action"], "created")
        self.assertIn("Novo conteúdo do harness", target.read_text(encoding="utf-8"))

    def test_appends_without_destroying_preexisting_content(self) -> None:
        """The exact gate case: a CLAUDE.md with 2-3 REAL preexisting lines."""
        target = self.tmpdir / "CLAUDE.md"
        original = (
            "# Regras do meu projeto\n\n"
            "- Nunca commitar direto na main.\n"
            "- Rodar `make test` antes de qualquer PR.\n"
        )
        target.write_text(original, encoding="utf-8")

        new = self.tmpdir / "new.md"
        new.write_text("# Conteúdo autorado pelo orions-belt\n\nLEI ZERO etc.\n", encoding="utf-8")

        result = _run(["markdown", "--existing", str(target), "--new", str(new), "--label", "v1"])
        self.assertEqual(result["action"], "appended")

        final = target.read_text(encoding="utf-8")
        # The ORIGINAL CONTENT survives WHOLE, verbatim, unchanged.
        self.assertIn(original.strip(), final)
        # The new content was APPENDED, it did not replace.
        self.assertIn("Conteúdo autorado pelo orions-belt", final)
        # The order proves it was an append (original comes BEFORE the new block).
        self.assertLess(final.index("Nunca commitar direto na main"), final.index("orions-belt:begin"))

    def test_second_run_updates_block_idempotently_without_duplicating(self) -> None:
        target = self.tmpdir / "CLAUDE.md"
        target.write_text("# Regras do projeto\n\n- Regra original.\n", encoding="utf-8")

        new_v1 = self.tmpdir / "new_v1.md"
        new_v1.write_text("Conteúdo versão 1 do harness.\n", encoding="utf-8")
        _run(["markdown", "--existing", str(target), "--new", str(new_v1), "--label", "v1"])

        new_v2 = self.tmpdir / "new_v2.md"
        new_v2.write_text("Conteúdo versão 2 do harness (atualizado).\n", encoding="utf-8")
        result2 = _run(["markdown", "--existing", str(target), "--new", str(new_v2), "--label", "v2"])
        self.assertEqual(result2["action"], "updated-block")

        final = target.read_text(encoding="utf-8")
        self.assertIn("Regra original", final)  # user content stays untouched
        self.assertIn("versão 2", final)  # updated block
        self.assertNotIn("versão 1", final)  # old block was REPLACED, not stacked
        self.assertEqual(final.count("orions-belt:begin"), 1, "must not duplicate the marker on successive updates")


class MergeSettingsJsonTest(unittest.TestCase):
    """A4 (post-v1.0.0 adversarial review, real gap): reconciliation by
    OWNERSHIP, not by `command` string equality. Every harness hook
    points to `.harness/hooks/<script>` (the same path used in the real
    settings.json.jinja) — that is the "owned" signal; any other
    command is treated as an EXTERNAL user hook and is always preserved."""

    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="merge-settings-test-"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_creates_fresh_when_absent(self) -> None:
        new = self.tmpdir / "new.json"
        new.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "x"}]}]}}), encoding="utf-8")
        target = self.tmpdir / "settings.json"
        result = _run(["settings-json", "--existing", str(target), "--new", str(new)])
        self.assertEqual(result["action"], "created")

    def test_fresh_create_then_reconcile_is_byte_idempotent(self) -> None:
        new = self.tmpdir / "new.json"
        # Deliberately non-canonical event order reproduces a first brownfield
        # install followed by the ownership reconciler's second pass.
        new.write_text(json.dumps({"hooks": {
            "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "python3 .harness/hooks/x.py"}]}],
            "PostToolUse": [{"hooks": [{"type": "command", "command": "bash .harness/hooks/y.sh"}]}],
        }}), encoding="utf-8")
        target = self.tmpdir / "settings.json"
        _run([
            "settings-json", "--existing", str(target), "--new", str(new),
            "--owned-command", "bash \"$CLAUDE_PROJECT_DIR/.harness/hooks/subagent-throttle.sh\"",
        ])
        first = target.read_bytes()
        _run(["settings-json", "--existing", str(target), "--new", str(new)])
        self.assertEqual(target.read_bytes(), first)

    def test_new_non_hook_key_reaches_a_brownfield_target(self) -> None:
        """G-brownfield (real gap, 2026-07-28): a key the template introduces
        outside `hooks` — the plugin-engine declaration for the hookify rules —
        used to land ONLY on the greenfield `created` path. On any pre-existing
        settings.json it was silently dropped, i.e. never on the installer's
        primary use case, leaving the shipped rules with no declared engine."""
        target = self.tmpdir / "settings.json"
        target.write_text(json.dumps({
            "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo user-own"}]}]},
        }), encoding="utf-8")
        new = self.tmpdir / "new.json"
        new.write_text(json.dumps({
            "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "bash .harness/hooks/completion-gate.py"}]}]},
            "enabledPlugins": {"hookify@claude-plugins-official": True},
        }), encoding="utf-8")
        result = _run(["settings-json", "--existing", str(target), "--new", str(new)])
        merged = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(merged.get("enabledPlugins"), {"hookify@claude-plugins-official": True})
        self.assertIn("enabledPlugins", result["keys_added"])
        self.assertIn("user-own", json.dumps(merged), "external hook must survive")

    def test_new_key_merge_never_overwrites_a_local_decision(self) -> None:
        """Additive, never destructive: an entry the project already declares
        wins, and unrelated entries of the same object are preserved."""
        target = self.tmpdir / "settings.json"
        target.write_text(json.dumps({
            "hooks": {},
            "enabledPlugins": {"hookify@claude-plugins-official": False, "mine@my-market": True},
        }), encoding="utf-8")
        new = self.tmpdir / "new.json"
        new.write_text(json.dumps({
            "hooks": {},
            "enabledPlugins": {"hookify@claude-plugins-official": True},
        }), encoding="utf-8")
        _run(["settings-json", "--existing", str(target), "--new", str(new)])
        merged = json.loads(target.read_text(encoding="utf-8"))
        self.assertIs(merged["enabledPlugins"]["hookify@claude-plugins-official"], False)
        self.assertIs(merged["enabledPlugins"]["mine@my-market"], True)

    def test_new_key_merge_is_idempotent(self) -> None:
        target = self.tmpdir / "settings.json"
        target.write_text(json.dumps({"hooks": {}}), encoding="utf-8")
        new = self.tmpdir / "new.json"
        new.write_text(json.dumps({
            "hooks": {},
            "extraKnownMarketplaces": {"claude-plugins-official": {"source": {"source": "github", "repo": "anthropics/claude-plugins-official"}}},
        }), encoding="utf-8")
        _run(["settings-json", "--existing", str(target), "--new", str(new)])
        first = target.read_bytes()
        second = _run(["settings-json", "--existing", str(target), "--new", str(new)])
        self.assertEqual(target.read_bytes(), first)
        self.assertEqual(second["keys_added"], [])

    def test_merges_preserving_external_user_hook_and_adds_owned_hooks(self) -> None:
        target = self.tmpdir / "settings.json"
        target.write_text(json.dumps({
            "permissions": {"allow": ["Bash(npm test)"]},
            # EXTERNAL user hook (does not point to .harness/hooks/) — never touched.
            "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "bash meu-hook-existente.sh"}]}]},
        }), encoding="utf-8")

        new = self.tmpdir / "new.json"
        new.write_text(json.dumps({
            "hooks": {
                "Stop": [{"hooks": [{"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/.harness/hooks/completion-gate.py\""}]}],
                "SessionStart": [{"hooks": [{"type": "command", "command": "bash \"$CLAUDE_PROJECT_DIR/.harness/hooks/lessons-inject.sh\""}]}],
            },
        }), encoding="utf-8")

        result = _run(["settings-json", "--existing", str(target), "--new", str(new)])
        self.assertEqual(result["action"], "merged")
        self.assertEqual(result["hooks_added"], 2)
        self.assertEqual(result["hooks_kept"], 1)
        self.assertEqual(result["hooks_removed_stale_owned"], 0)

        merged = json.loads(target.read_text(encoding="utf-8"))
        # key outside "hooks" preserved verbatim
        self.assertEqual(merged["permissions"]["allow"], ["Bash(npm test)"])
        # EXTERNAL user hook survives
        stop_commands = [h["command"] for group in merged["hooks"]["Stop"] for h in group["hooks"]]
        self.assertIn("bash meu-hook-existente.sh", stop_commands)
        # new OWNED harness hook was added
        self.assertTrue(any("completion-gate.py" in c for c in stop_commands))
        # new event (SessionStart) that did not exist was created
        self.assertIn("SessionStart", merged["hooks"])

    def test_first_adoption_preserves_external_hook_inside_harness_namespace(self) -> None:
        target = self.tmpdir / "settings.json"
        custom = "bash .harness/hooks/my-company-security.sh"
        target.write_text(json.dumps({
            "permissions": {"allow": ["Bash(make test)"]},
            "hooks": {"Stop": [{"hooks": [{"type": "command", "command": custom}]}]},
        }), encoding="utf-8")
        new = self.tmpdir / "new.json"
        new.write_text(json.dumps({
            "hooks": {"Stop": [{"hooks": [{
                "type": "command",
                "command": "python3 .harness/hooks/completion-gate.py",
            }]}]},
        }), encoding="utf-8")
        result = _run(["settings-json", "--existing", str(target), "--new", str(new)])
        commands = [
            h["command"] for group in json.loads(target.read_text())["hooks"]["Stop"]
            for h in group["hooks"]
        ]
        self.assertIn(custom, commands)
        self.assertEqual(result["hooks_removed_stale_owned"], 0)

    def test_merge_is_idempotent_no_duplicate_owned_hooks(self) -> None:
        target = self.tmpdir / "settings.json"
        target.write_text(json.dumps({"hooks": {}}), encoding="utf-8")
        new = self.tmpdir / "new.json"
        new.write_text(json.dumps({
            "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/.harness/hooks/completion-gate.py\""}]}]},
        }), encoding="utf-8")

        _run(["settings-json", "--existing", str(target), "--new", str(new)])
        result2 = _run(["settings-json", "--existing", str(target), "--new", str(new)])
        # round 2: round 1's owned is discarded (removed_stale_owned=1) and
        # the same set is reinserted (added=1) -> never duplicates.
        self.assertEqual(result2["hooks_added"], 1)
        self.assertEqual(result2["hooks_removed_stale_owned"], 1)

        merged = json.loads(target.read_text(encoding="utf-8"))
        stop_commands = [h["command"] for group in merged["hooks"]["Stop"] for h in group["hooks"]]
        self.assertEqual(len(stop_commands), 1, "2nd round must not duplicate the owned hook")

    def test_upstream_matcher_or_timeout_change_reaches_target(self) -> None:
        """A4 finding 1: dedup by command alone blocked matcher/
        timeout changes on the SAME script. Here the command is identical but
        timeout/matcher change upstream -> the NEW version must win, not the old one."""
        target = self.tmpdir / "settings.json"
        target.write_text(json.dumps({
            "hooks": {"PreToolUse": [{
                "hooks": [{
                    "type": "command",
                    "command": "bash \"$CLAUDE_PROJECT_DIR/.harness/hooks/subagent-throttle.sh\"",
                    "timeout": 10,
                }],
            }]},
        }), encoding="utf-8")

        new = self.tmpdir / "new.json"
        new.write_text(json.dumps({
            "hooks": {"PreToolUse": [{
                "matcher": "Task|Agent",
                "hooks": [{
                    "type": "command",
                    "command": "bash \"$CLAUDE_PROJECT_DIR/.harness/hooks/subagent-throttle.sh\"",
                    "timeout": 30,
                    "statusMessage": "throttle: cap novo",
                }],
            }]},
        }), encoding="utf-8")

        _run([
            "settings-json", "--existing", str(target), "--new", str(new),
            "--owned-command", "bash \"$CLAUDE_PROJECT_DIR/.harness/hooks/subagent-throttle.sh\"",
        ])
        merged = json.loads(target.read_text(encoding="utf-8"))
        entries = [h for group in merged["hooks"]["PreToolUse"] for h in group["hooks"]]
        self.assertEqual(len(entries), 1, "must not duplicate — same script, new version replaces the old")
        self.assertEqual(entries[0]["timeout"], 30, "new upstream timeout must reach the target project")
        self.assertEqual(entries[0].get("statusMessage"), "throttle: cap novo")

    def test_hook_removed_upstream_does_not_persist(self) -> None:
        """A4 finding 2: an owned hook that upstream REMOVED from the template (e.g. a
        discontinued gate) must disappear from the target project on the next merge,
        not persist forever."""
        target = self.tmpdir / "settings.json"
        target.write_text(json.dumps({
            "hooks": {"Stop": [{
                "hooks": [{"type": "command", "command": "bash \"$CLAUDE_PROJECT_DIR/.harness/hooks/gate-descontinuado.sh\""}],
            }]},
        }), encoding="utf-8")

        # new template no longer mentions gate-descontinuado.sh (upstream removed it).
        new = self.tmpdir / "new.json"
        new.write_text(json.dumps({"hooks": {"Stop": [{
            "hooks": [{"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/.harness/hooks/completion-gate.py\""}],
        }]}}), encoding="utf-8")

        result = _run([
            "settings-json", "--existing", str(target), "--new", str(new),
            "--owned-command", "bash \"$CLAUDE_PROJECT_DIR/.harness/hooks/gate-descontinuado.sh\"",
        ])
        self.assertEqual(result["hooks_removed_stale_owned"], 1)

        merged = json.loads(target.read_text(encoding="utf-8"))
        stop_commands = [h["command"] for group in merged["hooks"]["Stop"] for h in group["hooks"]]
        self.assertFalse(any("gate-descontinuado.sh" in c for c in stop_commands), "hook removed upstream must not persist")
        self.assertTrue(any("completion-gate.py" in c for c in stop_commands))

    def test_renamed_hook_does_not_double_fire(self) -> None:
        """A4 finding 3: an upstream script rename (foo.sh -> foo-v2.sh) must
        not leave BOTH entries registered (double-fire)."""
        target = self.tmpdir / "settings.json"
        target.write_text(json.dumps({
            "hooks": {"SessionStart": [{
                "hooks": [{"type": "command", "command": "bash \"$CLAUDE_PROJECT_DIR/.harness/hooks/dev-doctor.sh\""}],
            }]},
        }), encoding="utf-8")

        new = self.tmpdir / "new.json"
        new.write_text(json.dumps({
            "hooks": {"SessionStart": [{
                "hooks": [{"type": "command", "command": "bash \"$CLAUDE_PROJECT_DIR/.harness/hooks/dev-doctor-v2.sh\""}],
            }]},
        }), encoding="utf-8")

        _run([
            "settings-json", "--existing", str(target), "--new", str(new),
            "--owned-command", "bash \"$CLAUDE_PROJECT_DIR/.harness/hooks/dev-doctor.sh\"",
        ])
        merged = json.loads(target.read_text(encoding="utf-8"))
        commands = [h["command"] for group in merged["hooks"]["SessionStart"] for h in group["hooks"]]
        self.assertEqual(len(commands), 1, "rename must not leave both entries (double-fire)")
        self.assertTrue(any("dev-doctor-v2.sh" in c for c in commands))
        self.assertFalse(any("dev-doctor.sh" in c and "v2" not in c for c in commands))

    def test_external_user_hook_on_same_event_as_owned_survives_update(self) -> None:
        """Combined case: same event with 1 owned hook (which will be
        updated) and 1 external user hook side by side — only the owned one
        reconciles, the external one is never touched."""
        target = self.tmpdir / "settings.json"
        target.write_text(json.dumps({
            "hooks": {"Stop": [
                {"hooks": [{"type": "command", "command": "bash \"$CLAUDE_PROJECT_DIR/.harness/hooks/completion-gate-antigo.sh\""}]},
                {"hooks": [{"type": "command", "command": "npm run meu-check-custom"}]},
            ]},
        }), encoding="utf-8")

        new = self.tmpdir / "new.json"
        new.write_text(json.dumps({
            "hooks": {"Stop": [
                {"hooks": [{"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/.harness/hooks/completion-gate.py\""}]},
            ]},
        }), encoding="utf-8")

        _run([
            "settings-json", "--existing", str(target), "--new", str(new),
            "--owned-command", "bash \"$CLAUDE_PROJECT_DIR/.harness/hooks/completion-gate-antigo.sh\"",
        ])
        merged = json.loads(target.read_text(encoding="utf-8"))
        commands = [h["command"] for group in merged["hooks"]["Stop"] for h in group["hooks"]]
        self.assertIn("npm run meu-check-custom", commands, "hook externo do usuário nunca é tocado")
        self.assertTrue(any("completion-gate.py" in c for c in commands))
        self.assertFalse(any("completion-gate-antigo.sh" in c for c in commands), "owned antigo removido")
        self.assertEqual(len(commands), 2)


class MergeGitignoreTest(unittest.TestCase):
    """B3, 4th sensitive file: .gitignore uses a block marked with a `#`
    comment (not `<!-- -->`, which on a .gitignore line becomes a literal pattern)."""

    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="merge-gitignore-test-"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_creates_fresh_when_absent(self) -> None:
        new = self.tmpdir / "new.gitignore"
        new.write_text("__pycache__/\n*.pyc\n", encoding="utf-8")
        target = self.tmpdir / ".gitignore"
        result = _run(["gitignore", "--existing", str(target), "--new", str(new)])
        self.assertEqual(result["action"], "created")
        self.assertIn("__pycache__/", target.read_text(encoding="utf-8"))

    def test_appends_without_destroying_preexisting_patterns(self) -> None:
        target = self.tmpdir / ".gitignore"
        original = "node_modules/\n.env\ndist/\n"
        target.write_text(original, encoding="utf-8")

        new = self.tmpdir / "new.gitignore"
        new.write_text("__pycache__/\n*.py[cod]\n", encoding="utf-8")

        result = _run(["gitignore", "--existing", str(target), "--new", str(new), "--label", "v1"])
        self.assertEqual(result["action"], "appended")

        final = target.read_text(encoding="utf-8")
        self.assertIn("node_modules/", final)
        self.assertIn(".env", final)
        self.assertIn("dist/", final)
        self.assertIn("__pycache__/", final)
        self.assertLess(final.index("node_modules/"), final.index("orions-belt:begin"))

    def test_second_run_updates_block_without_duplicating(self) -> None:
        target = self.tmpdir / ".gitignore"
        target.write_text("meu-padrao-custom/\n", encoding="utf-8")

        new_v1 = self.tmpdir / "v1.gitignore"
        new_v1.write_text("padrao-v1/\n", encoding="utf-8")
        _run(["gitignore", "--existing", str(target), "--new", str(new_v1), "--label", "v1"])

        new_v2 = self.tmpdir / "v2.gitignore"
        new_v2.write_text("padrao-v2/\n", encoding="utf-8")
        result2 = _run(["gitignore", "--existing", str(target), "--new", str(new_v2), "--label", "v2"])
        self.assertEqual(result2["action"], "updated-block")

        final = target.read_text(encoding="utf-8")
        self.assertIn("meu-padrao-custom/", final)
        self.assertIn("padrao-v2/", final)
        self.assertNotIn("padrao-v1/", final)
        self.assertEqual(final.count("orions-belt:begin"), 1)


if __name__ == "__main__":
    unittest.main()
