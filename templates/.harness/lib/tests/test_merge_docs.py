#!/usr/bin/env python3
"""test_merge_docs.py — prova de merge NÃO-destrutivo (F5).

Gate real (00-plano-consolidado.md §6-F5): "merge NÃO-destrutivo de um
CLAUDE.md preexistente" — escreve um CLAUDE.md com 2-3 linhas reais, roda o
merge, confirma que o original não foi sobrescrito (diff mostra append, não
replace) e que rodar de novo não duplica o bloco (idempotência).
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
        """O caso exato do gate: CLAUDE.md com 2-3 linhas REAIS pré-existentes."""
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
        # O CONTEÚDO ORIGINAL sobrevive INTEIRO, verbatim, sem alteração.
        self.assertIn(original.strip(), final)
        # O novo conteúdo foi ANEXADO, não substituiu.
        self.assertIn("Conteúdo autorado pelo orions-belt", final)
        # A ordem prova que foi append (original vem ANTES do bloco novo).
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
        self.assertIn("Regra original", final)  # conteúdo do usuário continua intocado
        self.assertIn("versão 2", final)  # bloco atualizado
        self.assertNotIn("versão 1", final)  # bloco antigo foi SUBSTITUÍDO, não empilhado
        self.assertEqual(final.count("orions-belt:begin"), 1, "não pode duplicar o marcador em updates sucessivos")


class MergeSettingsJsonTest(unittest.TestCase):
    """A4 (revisão adversarial pós-v1.0.0, gap real): reconciliação por
    OWNERSHIP, não por igualdade de string de `command`. Todo hook do harness
    aponta pra `.harness/hooks/<script>` (mesmo path usado no
    settings.json.jinja real) — esse é o sinal de "owned"; qualquer outro
    command é tratado como hook EXTERNO do usuário e é sempre preservado."""

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

    def test_merges_preserving_external_user_hook_and_adds_owned_hooks(self) -> None:
        target = self.tmpdir / "settings.json"
        target.write_text(json.dumps({
            "permissions": {"allow": ["Bash(npm test)"]},
            # hook EXTERNO do usuário (não aponta pra .harness/hooks/) — nunca tocado.
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
        # chave fora de "hooks" preservada verbatim
        self.assertEqual(merged["permissions"]["allow"], ["Bash(npm test)"])
        # hook EXTERNO do usuário sobrevive
        stop_commands = [h["command"] for group in merged["hooks"]["Stop"] for h in group["hooks"]]
        self.assertIn("bash meu-hook-existente.sh", stop_commands)
        # hook OWNED novo do harness foi adicionado
        self.assertTrue(any("completion-gate.py" in c for c in stop_commands))
        # evento novo (SessionStart) que não existia foi criado
        self.assertIn("SessionStart", merged["hooks"])

    def test_merge_is_idempotent_no_duplicate_owned_hooks(self) -> None:
        target = self.tmpdir / "settings.json"
        target.write_text(json.dumps({"hooks": {}}), encoding="utf-8")
        new = self.tmpdir / "new.json"
        new.write_text(json.dumps({
            "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/.harness/hooks/completion-gate.py\""}]}]},
        }), encoding="utf-8")

        _run(["settings-json", "--existing", str(target), "--new", str(new)])
        result2 = _run(["settings-json", "--existing", str(target), "--new", str(new)])
        # rodada 2: o owned da rodada 1 é descartado (removed_stale_owned=1) e
        # o mesmo conjunto é reinserido (added=1) -> nunca duplica.
        self.assertEqual(result2["hooks_added"], 1)
        self.assertEqual(result2["hooks_removed_stale_owned"], 1)

        merged = json.loads(target.read_text(encoding="utf-8"))
        stop_commands = [h["command"] for group in merged["hooks"]["Stop"] for h in group["hooks"]]
        self.assertEqual(len(stop_commands), 1, "2ª rodada não pode duplicar o hook owned")

    def test_upstream_matcher_or_timeout_change_reaches_target(self) -> None:
        """A4 achado 1: dedup por command sozinho travava mudança de matcher/
        timeout no MESMO script. Aqui o command é idêntico mas timeout/matcher
        mudam upstream -> a versão NOVA precisa vencer, não a antiga."""
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

        _run(["settings-json", "--existing", str(target), "--new", str(new)])
        merged = json.loads(target.read_text(encoding="utf-8"))
        entries = [h for group in merged["hooks"]["PreToolUse"] for h in group["hooks"]]
        self.assertEqual(len(entries), 1, "não pode duplicar — mesmo script, versão nova substitui a antiga")
        self.assertEqual(entries[0]["timeout"], 30, "timeout upstream novo precisa chegar ao projeto-alvo")
        self.assertEqual(entries[0].get("statusMessage"), "throttle: cap novo")

    def test_hook_removed_upstream_does_not_persist(self) -> None:
        """A4 achado 2: hook owned que upstream REMOVEU do template (ex.: um
        gate descontinuado) precisa sumir do projeto-alvo no próximo merge,
        não persistir para sempre."""
        target = self.tmpdir / "settings.json"
        target.write_text(json.dumps({
            "hooks": {"Stop": [{
                "hooks": [{"type": "command", "command": "bash \"$CLAUDE_PROJECT_DIR/.harness/hooks/gate-descontinuado.sh\""}],
            }]},
        }), encoding="utf-8")

        # template novo não menciona mais gate-descontinuado.sh (upstream removeu).
        new = self.tmpdir / "new.json"
        new.write_text(json.dumps({"hooks": {"Stop": [{
            "hooks": [{"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/.harness/hooks/completion-gate.py\""}],
        }]}}), encoding="utf-8")

        result = _run(["settings-json", "--existing", str(target), "--new", str(new)])
        self.assertEqual(result["hooks_removed_stale_owned"], 1)

        merged = json.loads(target.read_text(encoding="utf-8"))
        stop_commands = [h["command"] for group in merged["hooks"]["Stop"] for h in group["hooks"]]
        self.assertFalse(any("gate-descontinuado.sh" in c for c in stop_commands), "hook removido upstream não pode persistir")
        self.assertTrue(any("completion-gate.py" in c for c in stop_commands))

    def test_renamed_hook_does_not_double_fire(self) -> None:
        """A4 achado 3: rename de script upstream (foo.sh -> foo-v2.sh) não
        pode deixar as DUAS entradas registradas (double-fire)."""
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

        _run(["settings-json", "--existing", str(target), "--new", str(new)])
        merged = json.loads(target.read_text(encoding="utf-8"))
        commands = [h["command"] for group in merged["hooks"]["SessionStart"] for h in group["hooks"]]
        self.assertEqual(len(commands), 1, "rename não pode deixar as duas entradas (double-fire)")
        self.assertTrue(any("dev-doctor-v2.sh" in c for c in commands))
        self.assertFalse(any("dev-doctor.sh" in c and "v2" not in c for c in commands))

    def test_external_user_hook_on_same_event_as_owned_survives_update(self) -> None:
        """Caso combinado: mesmo evento com 1 hook owned (que vai ser
        atualizado) e 1 hook externo do usuário lado a lado — só o owned
        reconcilia, o externo nunca é tocado."""
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

        _run(["settings-json", "--existing", str(target), "--new", str(new)])
        merged = json.loads(target.read_text(encoding="utf-8"))
        commands = [h["command"] for group in merged["hooks"]["Stop"] for h in group["hooks"]]
        self.assertIn("npm run meu-check-custom", commands, "hook externo do usuário nunca é tocado")
        self.assertTrue(any("completion-gate.py" in c for c in commands))
        self.assertFalse(any("completion-gate-antigo.sh" in c for c in commands), "owned antigo removido")
        self.assertEqual(len(commands), 2)


class MergeGitignoreTest(unittest.TestCase):
    """B3, 4º arquivo sensível: .gitignore usa bloco marcado com comentário
    `#` (não `<!-- -->`, que numa linha de .gitignore vira padrão literal)."""

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
