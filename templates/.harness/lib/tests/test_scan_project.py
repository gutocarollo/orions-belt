#!/usr/bin/env python3
"""test_scan_project.py — end-to-end proof of the F5 deterministic scanner.

Real gate (docs/planning/00-plano-consolidado.md §6-F5): "the applicability
report correctly classifies the stack-specific hooks on a pure-Python fixture
and on a Next.js one". Creates the 2 REAL fixtures in a tempdir (not fake
in-memory fixtures), runs a real `git init`, calls scan_project.py as a
subprocess (the same way the harness-init skill invokes it), and validates the
JSON output.

Usage: python3 -m unittest test_scan_project -v  (from within templates/.harness/lib/tests/)
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


def _run_scan(cmd: str, target: Path, *extra_args: str) -> dict:
    proc = subprocess.run(
        [sys.executable, str(SCAN_SCRIPT), cmd, "--target", str(target), *extra_args],
        capture_output=True, text=True, timeout=15,
    )
    assert proc.returncode == 0, f"scan_project.py {cmd} falhou: {proc.stderr}"
    return json.loads(proc.stdout)


def _status_of(components: list[dict], name: str) -> str:
    for c in components:
        if c["component"] == name:
            return c["status"]
    raise AssertionError(f"component {name} not found in the report")


class ScanProjectFixtureTest(unittest.TestCase):
    """Gate fixture (a): clean pure-Python repo (only pyproject.toml + git init)."""

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
        self.assertFalse(facts["has_frontend_ui"], "fastapi is backend, must not count as frontend UI")
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
        """D5: nothing silently enabled. No stack-specific component
        (understand-apps, prod guards) may appear as APLICAVEL without a real signal."""
        report = _run_scan("classify", self.tmpdir)
        self.assertEqual(_status_of(report["components"], "skill.understand-apps-incremental"), "NAO_APLICAVEL")

    def test_answers_suggests_safe_fields_only(self) -> None:
        answers = _run_scan("answers", self.tmpdir)
        self.assertIn("project_name", answers)
        self.assertNotIn("has_prod_stack", answers, "has_prod_stack is CONDICIONAL — never auto-suggested")
        self.assertNotIn("harness_understand_apps_root", answers)

    def test_answers_materializes_nao_aplicavel_ui_flags_as_false(self) -> None:
        """A3 (real gap from the post-v1.0.0 adversarial review): a pure Python
        backend without a frontend -> use_ui_evidence/use_ds_gate/use_ui_skills/
        use_icon_guard must come out `false` in `answers`, not be left out (the
        copier.yml default is `true` — without materializing it here, the render
        installs a UI module that the scanner itself classified as NAO_APLICAVEL)."""
        answers = _run_scan("answers", self.tmpdir)
        self.assertEqual(answers.get("use_ui_evidence"), False)
        self.assertEqual(answers.get("use_ds_gate"), False)
        self.assertEqual(answers.get("use_ui_skills"), False)
        self.assertEqual(answers.get("use_icon_guard"), False)


class ScanProjectNextjsFixtureTest(unittest.TestCase):
    """Gate fixture (b): Next.js monorepo with Playwright + docker-compose + apps/{web,api}."""

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
        self.assertFalse(facts["docker"]["has_swarm_signal"], "compose without a deploy: block is not Swarm")
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
        """docker-compose present but without a Swarm signature -> CONDICIONAL, never
        APLICAVEL directly (D5: has_prod_stack always requires human confirmation)."""
        report = _run_scan("classify", self.tmpdir)
        self.assertEqual(_status_of(report["components"], "hookify.prod-destroy"), "CONDICIONAL")
        self.assertEqual(_status_of(report["components"], "skill.deploy-prod-stack"), "CONDICIONAL")

    def test_classify_marks_lucide_and_dropdown_condicional_not_forced(self) -> None:
        report = _run_scan("classify", self.tmpdir)
        self.assertEqual(_status_of(report["components"], "hookify.icones-lucide"), "CONDICIONAL")
        self.assertEqual(_status_of(report["components"], "hookify.no-scaley-dropdown"), "CONDICIONAL")

    def test_answers_does_not_disable_ui_flags_when_frontend_detected(self) -> None:
        """Counter-proof of A3: with a real frontend (Next.js), nothing in `answers`
        may force use_ui_evidence/use_ds_gate/use_ui_skills to false —
        ui-evidence is APLICAVEL (Playwright present) and ds-gate/ui-skills have
        no rejection signal, so the key must not even appear (it stays at the
        copier.yml `true` default, without override)."""
        answers = _run_scan("answers", self.tmpdir)
        self.assertNotIn("use_ui_evidence", answers)
        self.assertNotIn("use_ds_gate", answers)
        self.assertNotIn("use_ui_skills", answers)

    def test_memory_surfaces_reports_local_absent_and_never_writes(self) -> None:
        surfaces = _run_scan("memory-surfaces", self.tmpdir)
        self.assertFalse(surfaces["local"]["claude_md"])
        self.assertIn("global_claude_READONLY", surfaces)
        self.assertIn("global_codex_READONLY", surfaces)
        self.assertIn("NEVER", surfaces["policy"])


class ScanProjectNoGitTest(unittest.TestCase):
    """Plan step 0 (§5): a project that is not even a git repo (finding 5 of report 08,
    real case central-ordens-bi). scan() must still run fail-open (not hang);
    the decision to refuse/git-init belongs to the SKILL, not the script."""

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


class ScanProjectMultiRootLayoutTest(unittest.TestCase):
    """A root without a language manifest and sibling frontend/backend apps.

    This is the brownfield topology that the original root-only scanner missed.
    It also proves that discovery stays bounded: nested fixtures and dependency
    directories must not become components.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmpdir = Path(tempfile.mkdtemp(prefix="harness-init-multi-root-"))
        (cls.tmpdir / "frontend").mkdir()
        (cls.tmpdir / "backend" / "tests").mkdir(parents=True)
        (cls.tmpdir / "node_modules" / "fake").mkdir(parents=True)
        (cls.tmpdir / "frontend" / "fixtures" / "nested-app").mkdir(parents=True)
        (cls.tmpdir / "odd-service").mkdir()

        (cls.tmpdir / "frontend" / "package.json").write_text(json.dumps({
            "name": "sample-web",
            "scripts": {"dev": "next dev --port 3000", "test": "vitest"},
            "dependencies": {"next": "^15.0.0", "react": "^19.0.0"},
            "devDependencies": {"vitest": "^3.0.0", "@playwright/test": "^1.50.0"},
        }), encoding="utf-8")
        (cls.tmpdir / "frontend" / "playwright.config.ts").write_text(
            "export default { testDir: './tests' };\n", encoding="utf-8"
        )
        (cls.tmpdir / "backend" / "requirements.txt").write_text(
            "fastapi==0.115.0\npytest==8.3.0\n", encoding="utf-8"
        )
        (cls.tmpdir / "backend" / "pytest.ini").write_text(
            "[pytest]\ntestpaths = tests\n", encoding="utf-8"
        )
        (cls.tmpdir / "node_modules" / "fake" / "package.json").write_text(
            '{"dependencies":{"express":"latest"}}', encoding="utf-8"
        )
        (cls.tmpdir / "frontend" / "fixtures" / "nested-app" / "package.json").write_text(
            '{"dependencies":{"nuxt":"latest"}}', encoding="utf-8"
        )
        (cls.tmpdir / "odd-service" / "requirements.txt").write_text(
            "flask==3.0.0\n", encoding="utf-8"
        )
        (cls.tmpdir / "dev.sh").write_text(
            "uvicorn backend.main:app --port 8000 &\n"
            "npm --prefix frontend run dev -- --port 3000\n",
            encoding="utf-8",
        )
        _git(["init", "-q"], cls.tmpdir)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def test_discovers_frontend_and_backend_with_component_evidence(self) -> None:
        facts = _run_scan("scan", self.tmpdir)
        components = {row["path"]: row for row in facts["components"]}

        self.assertEqual(set(components), {"frontend", "backend"})
        self.assertEqual(components["frontend"]["web_framework"], "nextjs")
        self.assertEqual(components["backend"]["web_framework"], "fastapi")
        self.assertEqual(components["frontend"]["test_frameworks"], ["playwright", "vitest"])
        self.assertEqual(components["backend"]["test_frameworks"], ["pytest"])

        next_evidence = components["frontend"]["evidence"]["web_frameworks"][0]
        self.assertEqual(next_evidence, {
            "value": "nextjs", "source": "frontend/package.json", "confidence": "high",
        })
        fastapi_evidence = components["backend"]["evidence"]["web_frameworks"][0]
        self.assertEqual(fastapi_evidence["source"], "backend/requirements.txt")
        self.assertEqual(fastapi_evidence["confidence"], "high")

    def test_preserves_compatible_aggregates_and_port_provenance(self) -> None:
        facts = _run_scan("scan", self.tmpdir)
        self.assertEqual(facts["primary_language"], "javascript")
        self.assertEqual(facts["web_framework"], "nextjs")
        self.assertTrue(facts["has_frontend_ui"])
        self.assertEqual(facts["test_frameworks"], ["playwright", "pytest", "vitest"])
        self.assertEqual(facts["ports_detected"], [3000, 8000])
        self.assertEqual(
            {(row["port"], row["source"], row["confidence"]) for row in facts["evidence"]["ports"]},
            {(3000, "dev.sh", "medium"), (8000, "dev.sh", "medium"),
             (3000, "frontend/package.json", "high")},
        )

    def test_explicit_component_root_is_a_bounded_fallback(self) -> None:
        facts = _run_scan("scan", self.tmpdir, "--component-root", "odd-service")
        components = {row["path"]: row for row in facts["components"]}
        self.assertEqual(set(components), {"frontend", "backend", "odd-service"})
        self.assertEqual(components["odd-service"]["discovery_source"], "explicit")
        self.assertEqual(components["odd-service"]["web_framework"], "flask")

    def test_explicit_root_cannot_escape_or_cross_a_symlink(self) -> None:
        outside = Path(tempfile.mkdtemp(prefix="harness-init-outside-component-"))
        try:
            (outside / "package.json").write_text(
                '{"dependencies":{"express":"latest"}}', encoding="utf-8"
            )
            (self.tmpdir / "linked-service").symlink_to(outside, target_is_directory=True)
            facts = _run_scan(
                "scan", self.tmpdir,
                "--component-root", "../" + outside.name,
                "--component-root", "linked-service",
            )
            self.assertNotIn("linked-service", {row["path"] for row in facts["components"]})
            self.assertFalse(any(row["web_framework"] == "express" for row in facts["components"]))
        finally:
            (self.tmpdir / "linked-service").unlink(missing_ok=True)
            shutil.rmtree(outside, ignore_errors=True)

    def test_understand_root_candidate_ignores_symlinked_apps_children(self) -> None:
        outside = Path(tempfile.mkdtemp(prefix="harness-init-outside-apps-"))
        apps = self.tmpdir / "apps"
        apps.mkdir()
        try:
            for name in ("one", "two"):
                service = outside / name
                service.mkdir()
                (service / "pyproject.toml").write_text("[project]\nname='outside'\n")
                (apps / name).symlink_to(service, target_is_directory=True)
            facts = _run_scan("scan", self.tmpdir)
            self.assertIsNone(facts["understand_apps_root_offset_candidate"])
            self.assertFalse(any(row["path"].startswith("apps/") for row in facts["components"]))
        finally:
            for child in apps.iterdir():
                child.unlink(missing_ok=True)
            apps.rmdir()
            shutil.rmtree(outside, ignore_errors=True)


class ScanProjectDeclaredWorkspaceTest(unittest.TestCase):
    """Declared workspaces outside conventional names are discovered safely."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmpdir = Path(tempfile.mkdtemp(prefix="harness-init-workspace-"))
        (cls.tmpdir / "modules" / "dashboard").mkdir(parents=True)
        (cls.tmpdir / "examples" / "demo").mkdir(parents=True)
        (cls.tmpdir / "package.json").write_text(json.dumps({
            "name": "workspace-root",
            "private": True,
            "workspaces": ["modules/*", "examples/*", "too/deep/*", "any/**"],
        }), encoding="utf-8")
        (cls.tmpdir / "modules" / "dashboard" / "package.json").write_text(json.dumps({
            "name": "dashboard",
            "dependencies": {"vite": "latest", "react": "latest"},
        }), encoding="utf-8")
        (cls.tmpdir / "examples" / "demo" / "package.json").write_text(json.dumps({
            "name": "demo", "dependencies": {"express": "latest"},
        }), encoding="utf-8")

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def test_declared_one_level_workspace_is_discovered_but_excluded_or_deep_globs_are_not(self) -> None:
        facts = _run_scan("scan", self.tmpdir)
        components = {row["path"]: row for row in facts["components"]}
        self.assertEqual(set(components), {".", "modules/dashboard"})
        self.assertEqual(components["modules/dashboard"]["discovery_source"], "workspace:modules/*")
        self.assertEqual(components["modules/dashboard"]["web_framework"], "vite-spa")


if __name__ == "__main__":
    unittest.main()
