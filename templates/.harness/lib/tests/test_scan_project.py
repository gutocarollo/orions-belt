#!/usr/bin/env python3
"""test_scan_project.py — prova de ponta-a-ponta do scanner determinístico do F5.

Gate real (docs/planning/00-plano-consolidado.md §6-F5): "o relatório de
aplicabilidade classifica corretamente os hooks stack-específicos numa
fixture Python-pura e numa Next.js". Cria as 2 fixtures REAIS em tempdir
(não fixtures fake em memória), roda `git init` de verdade, chama
scan_project.py como subprocess (a mesma forma que a skill harness-init o
invoca), e valida a saída JSON.

Uso: python3 -m unittest test_scan_project -v  (de dentro de templates/.harness/lib/tests/)
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
SCAN_SCRIPT = HERE.parent / "scan_project.py"


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _run_scan(cmd: str, target: Path) -> dict:
    proc = subprocess.run(
        [sys.executable, str(SCAN_SCRIPT), cmd, "--target", str(target)],
        capture_output=True, text=True, timeout=15,
    )
    assert proc.returncode == 0, f"scan_project.py {cmd} falhou: {proc.stderr}"
    return json.loads(proc.stdout)


def _status_of(components: list[dict], name: str) -> str:
    for c in components:
        if c["component"] == name:
            return c["status"]
    raise AssertionError(f"componente {name} não encontrado no relatório")


class ScanProjectFixtureTest(unittest.TestCase):
    """Fixture (a) do gate: repo Python puro limpo (só pyproject.toml + git init)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmpdir = Path(tempfile.mkdtemp(prefix="harness-init-python-pure-"))
        (cls.tmpdir / "pyproject.toml").write_text(
            '[project]\nname = "fixture"\nversion = "0.1.0"\ndependencies = ["fastapi"]\n'
            "\n[tool.uv]\n",
            encoding="utf-8",
        )
        (cls.tmpdir / "pytest.ini").write_text("[pytest]\ntestpaths = tests\n", encoding="utf-8")
        (cls.tmpdir / "tests").mkdir()
        (cls.tmpdir / "tests" / "test_smoke.py").write_text("def test_smoke():\n    assert True\n", encoding="utf-8")
        _git(["init", "-q"], cls.tmpdir)
        _git(["config", "user.email", "test@example.com"], cls.tmpdir)
        _git(["config", "user.name", "Test"], cls.tmpdir)
        _git(["add", "-A"], cls.tmpdir)
        _git(["commit", "-q", "-m", "init fixture"], cls.tmpdir)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def test_scan_detects_python_and_git(self) -> None:
        facts = _run_scan("scan", self.tmpdir)
        self.assertTrue(facts["is_git_repo"])
        self.assertEqual(facts["primary_language"], "python")
        self.assertEqual(facts["package_manager"], "uv")
        self.assertFalse(facts["has_frontend_ui"], "fastapi é backend, não deve contar como UI frontend")
        self.assertIn("pytest", facts["test_frameworks"])

    def test_classify_marks_ui_evidence_and_ds_gate_not_applicable(self) -> None:
        report = _run_scan("classify", self.tmpdir)
        self.assertEqual(_status_of(report["components"], "hook.ui-evidence-gate"), "NAO_APLICAVEL")
        self.assertEqual(_status_of(report["components"], "skill.ui-evidence"), "NAO_APLICAVEL")
        self.assertEqual(_status_of(report["components"], "hook.ds-gate-posttool"), "NAO_APLICAVEL")

    def test_classify_marks_prod_guards_not_applicable_without_docker(self) -> None:
        report = _run_scan("classify", self.tmpdir)
        self.assertEqual(_status_of(report["components"], "hookify.prod-destroy"), "NAO_APLICAVEL")
        self.assertEqual(_status_of(report["components"], "skill.deploy-prod-stack"), "NAO_APLICAVEL")

    def test_classify_marks_generic_components_always_applicable(self) -> None:
        report = _run_scan("classify", self.tmpdir)
        for name in ("skill.marathon", "skill.prova-de-conclusao", "hook.completion-gate",
                     "hook.subagent-throttle", "skill.grill-me"):
            self.assertEqual(_status_of(report["components"], name), "APLICAVEL", name)

    def test_classify_never_returns_condicional_silently_active(self) -> None:
        """D5: nada ativado silenciosamente. Nenhum componente stack-específico
        (understand-apps, prod guards) pode aparecer como APLICAVEL sem sinal real."""
        report = _run_scan("classify", self.tmpdir)
        self.assertEqual(_status_of(report["components"], "skill.understand-apps-incremental"), "NAO_APLICAVEL")

    def test_answers_suggests_safe_fields_only(self) -> None:
        answers = _run_scan("answers", self.tmpdir)
        self.assertIn("project_name", answers)
        self.assertNotIn("has_prod_stack", answers, "has_prod_stack é CONDICIONAL — nunca sugerido automaticamente")
        self.assertNotIn("harness_understand_apps_root", answers)

    def test_answers_materializes_nao_aplicavel_ui_flags_as_false(self) -> None:
        """A3 (gap real da revisão adversarial pós-v1.0.0): backend Python puro
        sem frontend -> use_ui_evidence/use_ds_gate/use_ui_skills/use_icon_guard
        precisam vir `false` em `answers`, não ficar de fora (default do
        copier.yml é `true` — sem materializar aqui, o render instala módulo
        de UI que o próprio scanner classificou como NAO_APLICAVEL)."""
        answers = _run_scan("answers", self.tmpdir)
        self.assertEqual(answers.get("use_ui_evidence"), False)
        self.assertEqual(answers.get("use_ds_gate"), False)
        self.assertEqual(answers.get("use_ui_skills"), False)
        self.assertEqual(answers.get("use_icon_guard"), False)


class ScanProjectNextjsFixtureTest(unittest.TestCase):
    """Fixture (b) do gate: monorepo Next.js com Playwright + docker-compose + apps/{web,api}."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmpdir = Path(tempfile.mkdtemp(prefix="harness-init-nextjs-"))
        (cls.tmpdir / "apps" / "web").mkdir(parents=True)
        (cls.tmpdir / "apps" / "api").mkdir(parents=True)
        (cls.tmpdir / "package.json").write_text(json.dumps({
            "name": "nextjs-fixture",
            "scripts": {"dev": "next dev --port 3000", "test:e2e": "playwright test"},
            "dependencies": {"next": "^15.0.0", "react": "^19.0.0", "lucide-react": "^0.400.0"},
            "devDependencies": {"@playwright/test": "^1.45.0"},
        }), encoding="utf-8")
        (cls.tmpdir / "playwright.config.ts").write_text("export default { testDir: './tests' };\n", encoding="utf-8")
        (cls.tmpdir / "docker-compose.yml").write_text(
            "services:\n  web:\n    build: .\n    ports:\n      - \"3000:3000\"\n"
            "  api:\n    build: ./apps/api\n    ports:\n      - \"8000:8000\"\n",
            encoding="utf-8",
        )
        (cls.tmpdir / "apps" / "web" / "package.json").write_text('{"name": "web-sub"}', encoding="utf-8")
        (cls.tmpdir / "apps" / "api" / "pyproject.toml").write_text('[project]\nname = "api-sub"\n', encoding="utf-8")
        _git(["init", "-q"], cls.tmpdir)
        _git(["config", "user.email", "test@example.com"], cls.tmpdir)
        _git(["config", "user.name", "Test"], cls.tmpdir)
        _git(["add", "-A"], cls.tmpdir)
        _git(["commit", "-q", "-m", "init fixture"], cls.tmpdir)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def test_scan_detects_nextjs_playwright_docker_monorepo(self) -> None:
        facts = _run_scan("scan", self.tmpdir)
        self.assertEqual(facts["web_framework"], "nextjs")
        self.assertTrue(facts["has_frontend_ui"])
        self.assertIn("playwright", facts["test_frameworks"])
        self.assertTrue(facts["docker"]["has_compose"])
        self.assertFalse(facts["docker"]["has_swarm_signal"], "compose sem bloco deploy: não é Swarm")
        self.assertEqual(facts["understand_apps_root_offset_candidate"], "apps")
        self.assertIn(3000, facts["ports_detected"])
        self.assertIn(8000, facts["ports_detected"])

    def test_classify_marks_ui_evidence_gate_applicable(self) -> None:
        report = _run_scan("classify", self.tmpdir)
        self.assertEqual(_status_of(report["components"], "hook.ui-evidence-gate"), "APLICAVEL")
        self.assertEqual(_status_of(report["components"], "skill.ui-evidence"), "APLICAVEL")

    def test_classify_marks_understand_apps_condicional_with_candidate(self) -> None:
        report = _run_scan("classify", self.tmpdir)
        row = next(c for c in report["components"] if c["component"] == "skill.understand-apps-incremental")
        self.assertEqual(row["status"], "CONDICIONAL")
        self.assertIn("apps", row["reason"])

    def test_classify_marks_prod_guards_condicional_not_silently_active(self) -> None:
        """docker-compose presente mas sem assinatura Swarm -> CONDICIONAL, nunca
        APLICAVEL direto (D5: has_prod_stack sempre exige confirmação humana)."""
        report = _run_scan("classify", self.tmpdir)
        self.assertEqual(_status_of(report["components"], "hookify.prod-destroy"), "CONDICIONAL")
        self.assertEqual(_status_of(report["components"], "skill.deploy-prod-stack"), "CONDICIONAL")

    def test_classify_marks_lucide_and_dropdown_condicional_not_forced(self) -> None:
        report = _run_scan("classify", self.tmpdir)
        self.assertEqual(_status_of(report["components"], "hookify.icones-lucide"), "CONDICIONAL")
        self.assertEqual(_status_of(report["components"], "hookify.no-scaley-dropdown"), "CONDICIONAL")

    def test_answers_does_not_disable_ui_flags_when_frontend_detected(self) -> None:
        """Contraprova de A3: com frontend real (Next.js), nada em `answers`
        pode forçar use_ui_evidence/use_ds_gate/use_ui_skills para false —
        ui-evidence é APLICAVEL (Playwright presente) e ds-gate/ui-skills não
        têm sinal de rejeição, então a chave nem deve aparecer (fica no
        default `true` do copier.yml, sem override)."""
        answers = _run_scan("answers", self.tmpdir)
        self.assertNotIn("use_ui_evidence", answers)
        self.assertNotIn("use_ds_gate", answers)
        self.assertNotIn("use_ui_skills", answers)

    def test_memory_surfaces_reports_local_absent_and_never_writes(self) -> None:
        surfaces = _run_scan("memory-surfaces", self.tmpdir)
        self.assertFalse(surfaces["local"]["claude_md"])
        self.assertIn("global_claude_READONLY", surfaces)
        self.assertIn("global_codex_READONLY", surfaces)
        self.assertIn("NUNCA", surfaces["policy"])


class ScanProjectNoGitTest(unittest.TestCase):
    """Passo 0 do plano (§5): projeto que nem é repo git (achado 5 do relatório 08,
    caso real central-ordens-bi). scan() ainda deve rodar fail-open (não travar);
    a decisão de recusar/git-init é da SKILL, não do script."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmpdir = Path(tempfile.mkdtemp(prefix="harness-init-no-git-"))
        (cls.tmpdir / "orders.json").write_text("{}", encoding="utf-8")

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def test_scan_reports_not_a_git_repo_without_crashing(self) -> None:
        facts = _run_scan("scan", self.tmpdir)
        self.assertFalse(facts["is_git_repo"])
        self.assertIsNone(facts["git_root"])


if __name__ == "__main__":
    unittest.main()
