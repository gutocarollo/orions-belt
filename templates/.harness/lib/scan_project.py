#!/usr/bin/env python3
"""scan_project.py — deterministic scanner + per-stack applicability classifier (F5).

Engine for the `harness-init` skill. ZERO LLM calls in this file — blueprint
ported from `scan-project.mjs` of understand-anything (docs/planning/research/
07-autoconfig-patterns.md §A.4): "file enumeration, classification by
extension/name, counting, import resolution and structural diffing are ALWAYS
deterministic". The skill (SKILL.md) only decides BASED ON the JSON this
script prints — it never reimplements the detection logic in prose.

Decision D5 (docs/planning/00-plano-consolidado.md §11): the framework installs
EVERYTHING, but each component is classified APLICAVEL / NAO_APLICAVEL / CONDICIONAL
by RULE (not by LLM "guesswork"). CONDICIONAL always requires human
confirmation before activating — it is never silently assumed.

Zero external dependencies (pure stdlib, same decision as `_tooling_conf.py` —
this script runs INSIDE any target project, which may not have PyYAML/
tomli installed; `tomllib` is stdlib since 3.11, used only for real TOML
[pyproject.toml/Cargo.toml]; YAML is always handled by lightweight regex over
raw text — it is not a full YAML parser, it is key-presence detection).

CLI:
  scan_project.py scan             [--target DIR] [--json]
  scan_project.py classify         [--target DIR] [--json]
  scan_project.py memory-surfaces  [--target DIR] [--json]
  scan_project.py answers          [--target DIR] [--json]
  scan_project.py all              [--target DIR] [--json]   (the 4 keys combined)

All outputs are JSON on stdout (so the skill can consume them without regex).
Fail-open: any individual file-read exception is ignored (file treated as
absent), never bringing down the whole scan.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - only on Python <3.11, unsupported but fail-open
    tomllib = None  # type: ignore[assignment]


# =============================================================================
# --- fail-open reading utilities ---
# =============================================================================

def _read_text(p: Path) -> str | None:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _read_toml(p: Path) -> dict:
    if tomllib is None:
        return {}
    try:
        with open(p, "rb") as fh:
            return tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _read_json(p: Path) -> dict:
    text = _read_text(p)
    if text is None:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def _sh(args: list[str], cwd: Path) -> str:
    try:
        proc = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=10)
        return proc.stdout.strip() if proc.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


# =============================================================================
# --- SCAN (deterministic) ---
# =============================================================================

MANIFEST_LANGUAGE = {
    "pyproject.toml": "python",
    "requirements.txt": "python",
    "setup.py": "python",
    "setup.cfg": "python",
    "Pipfile": "python",
    "package.json": "javascript",
    "go.mod": "go",
    "Cargo.toml": "rust",
    "pom.xml": "java",
    "build.gradle": "java",
    "build.gradle.kts": "java",
    "composer.json": "php",
    "Gemfile": "ruby",
    "mix.exs": "elixir",
}

# Priority order when multiple manifests coexist (a polyglot monorepo
# picks the first one in the list that exists at the root — it does not sum languages).
MANIFEST_PRIORITY = [
    "pyproject.toml", "requirements.txt", "setup.py", "setup.cfg", "Pipfile",
    "package.json", "go.mod", "Cargo.toml", "pom.xml", "build.gradle",
    "build.gradle.kts", "composer.json", "Gemfile", "mix.exs",
]

PORT_PATTERNS = [
    re.compile(r"\bPORT\s*=\s*['\"]?(\d{2,5})", re.I),
    re.compile(r"--port[= ](\d{2,5})"),
    re.compile(r"\b(\d{2,5}):(\d{2,5})\b"),  # docker-compose "host:container"
]


def _detect_package_manager(target: Path, language: str | None) -> str | None:
    if language == "javascript":
        if (target / "pnpm-lock.yaml").is_file():
            return "pnpm"
        if (target / "yarn.lock").is_file():
            return "yarn"
        if (target / "package-lock.json").is_file():
            return "npm"
        if (target / "package.json").is_file():
            return "npm"  # assumed default, no lockfile yet
    if language == "python":
        if (target / "uv.lock").is_file():
            return "uv"
        if (target / "poetry.lock").is_file():
            return "poetry"
        pyproject = _read_toml(target / "pyproject.toml")
        if "tool" in pyproject and "uv" in pyproject.get("tool", {}):
            return "uv"
        if "tool" in pyproject and "poetry" in pyproject.get("tool", {}):
            return "poetry"
        if (target / "requirements.txt").is_file():
            return "pip"
    return None


def _package_json_deps(target: Path) -> dict[str, str]:
    pkg = _read_json(target / "package.json")
    deps: dict[str, str] = {}
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        deps.update(pkg.get(key, {}) or {})
    return deps


FRONTEND_FRAMEWORKS = {"nextjs", "remix", "nuxt", "vite-spa"}
BACKEND_FRAMEWORKS = {"express", "fastapi", "django", "flask"}


def _detect_web_framework(target: Path, language: str | None) -> str | None:
    if language == "javascript":
        deps = _package_json_deps(target)
        if "next" in deps:
            return "nextjs"
        if "@remix-run/react" in deps:
            return "remix"
        if "nuxt" in deps or "nuxt3" in deps:
            return "nuxt"
        if "vite" in deps and ("react" in deps or "vue" in deps):
            return "vite-spa"
        if "express" in deps:
            return "express"
    if language == "python":
        for req_file in ("requirements.txt", "pyproject.toml"):
            text = _read_text(target / req_file) or ""
            low = text.lower()
            if "fastapi" in low:
                return "fastapi"
            if "django" in low:
                return "django"
            if "flask" in low:
                return "flask"
    return None


def _detect_test_frameworks(target: Path) -> list[str]:
    found: list[str] = []
    if any((target / n).exists() for n in (
        "playwright.config.ts", "playwright.config.js", "playwright.config.mjs",
    )):
        found.append("playwright")
    deps = _package_json_deps(target)
    if "@playwright/test" in deps and "playwright" not in found:
        found.append("playwright")
    if "jest" in deps or any((target / n).exists() for n in ("jest.config.js", "jest.config.ts")):
        found.append("jest")
    if "vitest" in deps or (target / "vitest.config.ts").exists():
        found.append("vitest")
    if "cypress" in deps or (target / "cypress.config.js").exists():
        found.append("cypress")
    pytest_ini = (target / "pytest.ini").exists() or (target / "setup.cfg").exists()
    pyproject = _read_toml(target / "pyproject.toml")
    if pytest_ini or "pytest" in pyproject.get("tool", {}) or (target / "conftest.py").exists():
        found.append("pytest")
    return found


def _detect_docker(target: Path) -> dict:
    dockerfile = (target / "Dockerfile").is_file() or any(
        p.name == "Dockerfile" for p in target.glob("*/Dockerfile")
    )
    compose_files = [
        n for n in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")
        if (target / n).is_file()
    ]
    has_compose = bool(compose_files)
    has_swarm_signal = False
    for n in compose_files:
        text = _read_text(target / n) or ""
        # lightweight detection, not a YAML parser: presence of a "deploy:" block (Swarm-only key)
        if re.search(r"^\s*deploy:\s*$", text, re.M):
            has_swarm_signal = True
    return {
        "has_dockerfile": dockerfile,
        "has_compose": has_compose,
        "compose_files": compose_files,
        "has_swarm_signal": has_swarm_signal,
    }


def _detect_ports(target: Path) -> list[int]:
    ports: set[int] = set()
    candidates = list(target.glob(".env*")) + [
        target / n for n in ("docker-compose.yml", "docker-compose.yaml", "compose.yml")
    ]
    pkg = target / "package.json"
    if pkg.is_file():
        candidates.append(pkg)
    for p in candidates:
        text = _read_text(p)
        if not text:
            continue
        for pat in PORT_PATTERNS:
            for m in pat.finditer(text):
                for g in m.groups():
                    if g and g.isdigit():
                        v = int(g)
                        if 1024 <= v <= 65535:
                            ports.add(v)
    return sorted(ports)


def _detect_understand_root_offset(target: Path) -> str | None:
    """Heuristic: an 'apps/' subdirectory at the root with >=2 subfolders each
    containing its own manifest suggests a monorepo with PROJECT_ROOT != git-root
    (the PROJECT_ROOT≠git-root pitfall documented in the reference donor harness)."""
    apps_dir = target / "apps"
    if not apps_dir.is_dir():
        return None
    sub_with_manifest = 0
    for child in apps_dir.iterdir():
        if not child.is_dir():
            continue
        if any((child / m).exists() for m in MANIFEST_PRIORITY):
            sub_with_manifest += 1
    return "apps" if sub_with_manifest >= 2 else None


def scan(target: Path) -> dict:
    is_git = _sh(["git", "rev-parse", "--is-inside-work-tree"], target) == "true"
    git_root = _sh(["git", "rev-parse", "--show-toplevel"], target) if is_git else None

    manifest = next((m for m in MANIFEST_PRIORITY if (target / m).is_file()), None)
    language = MANIFEST_LANGUAGE.get(manifest) if manifest else None

    docker = _detect_docker(target)
    package_manager = _detect_package_manager(target, language)
    web_framework = _detect_web_framework(target, language)
    test_frameworks = _detect_test_frameworks(target)
    ports = _detect_ports(target)
    understand_root = _detect_understand_root_offset(target)

    local_surfaces = {
        "claude_md": (target / ".claude" / "CLAUDE.md").is_file() or (target / "CLAUDE.md").is_file(),
        "claude_md_path": str(
            (target / ".claude" / "CLAUDE.md") if (target / ".claude" / "CLAUDE.md").is_file()
            else (target / "CLAUDE.md") if (target / "CLAUDE.md").is_file() else ""
        ) or None,
        "agents_md": (target / "AGENTS.md").is_file(),
        "claude_settings_json": (target / ".claude" / "settings.json").is_file(),
        "gitignore_claude_block": bool(
            re.search(r"^\.claude/\*", _read_text(target / ".gitignore") or "", re.M)
        ),
        "lessons_file": (target / "tasks" / "lessons.md").is_file(),
        "docs_log": (target / "docs" / "log.md").is_file(),
    }

    return {
        "target": str(target),
        "is_git_repo": is_git,
        "git_root": git_root,
        "primary_manifest": manifest,
        "primary_language": language,
        "package_manager": package_manager,
        "web_framework": web_framework,
        "has_frontend_ui": web_framework in FRONTEND_FRAMEWORKS,
        "test_frameworks": test_frameworks,
        "docker": docker,
        "ports_detected": ports,
        "understand_apps_root_offset_candidate": understand_root,
        "local_memory_surfaces": local_surfaces,
    }


# =============================================================================
# --- CLASSIFY (per-component rule, D5 — never LLM) ---
# =============================================================================

APLICAVEL = "APLICAVEL"
NAO_APLICAVEL = "NAO_APLICAVEL"
CONDICIONAL = "CONDICIONAL"

# Each rule receives the `scan()` dict and returns (status, reason).
# Order = presentation order in the report.
_ComponentRule = tuple  # (name, category, fn)


def _rule_generic_always_on(_facts: dict) -> tuple[str, str]:
    return APLICAVEL, "Generic methodology/guard, no stack dependency."


def _rule_ui_evidence_gate(facts: dict) -> tuple[str, str]:
    wf = facts["web_framework"]
    has_playwright = "playwright" in facts["test_frameworks"]
    if not facts["has_frontend_ui"]:
        detail = f" (detected framework '{wf}' is backend/API, does not render UI)" if wf else ""
        return NAO_APLICAVEL, f"No FRONTEND framework detected{detail} — there is no UI to capture visual evidence from."
    if has_playwright:
        return APLICAVEL, f"Frontend framework '{wf}' + Playwright detected."
    return CONDICIONAL, (
        f"Frontend framework '{wf}' detected but not Playwright — installs inert "
        "(hook stays no-op) until Playwright is added; confirm before activating."
    )


def _rule_ds_gate_posttool(facts: dict) -> tuple[str, str]:
    # Post rescue-plan §R1a: the engine (.harness/lib/ds-gate.sh +
    # ds-pairs-check.py) no longer hardcodes "apps/web" — it reads HARNESS_WEB_APP_DIR
    # from .harness/harness.conf (default ".") and is fail-open if the tokens CSS
    # (DS_GATE_CSS_PATH) does not exist. But it only makes sense in a project with
    # Tailwind + CSS tokens (--var) in a globals.css-like file — a signal this
    # scanner does not detect today (no "uses Tailwind" fact); hence
    # CONDICIONAL (never automatically assumed, D5), not APLICAVEL directly.
    wf = facts["web_framework"]
    if not facts["has_frontend_ui"]:
        detail = f" (detected framework '{wf}' is backend/API, does not render UI)" if wf else ""
        return NAO_APLICAVEL, f"No FRONTEND framework detected{detail} — the tokenization ratchet does not apply."
    return CONDICIONAL, (
        f"Frontend framework '{wf}' detected — hook is fail-open (no-op if "
        "HARNESS_WEB_APP_DIR/DS_GATE_CSS_PATH does not exist), but only makes sense with "
        "Tailwind + CSS tokens (--var) in a globals.css-like file; confirm "
        "harness_web_app_dir/DS_GATE_CSS_PATH before relying on it."
    )


def _rule_understand_apps_incremental(facts: dict) -> tuple[str, str]:
    candidate = facts["understand_apps_root_offset_candidate"]
    if candidate:
        return CONDICIONAL, (
            f"Detected PROJECT_ROOT candidate='{candidate}' (subfolders with "
            "their own manifest) — confirm the exact value of harness_understand_apps_root "
            "before activating; never automatically assumed (D5)."
        )
    return NAO_APLICAVEL, (
        "No monorepo-like subdirectory detected at the root — Understand Anything, "
        "if used, most likely runs directly at the git root (without the "
        "PROJECT_ROOT≠git-root pitfall this skill/hooks solve)."
    )


def _rule_prod_guards(facts: dict) -> tuple[str, str]:
    docker = facts["docker"]
    if docker["has_swarm_signal"]:
        return CONDICIONAL, (
            "docker-compose with a 'deploy:' block (Swarm signature) detected — "
            "suggests a production stack, but has_prod_stack ALWAYS requires explicit "
            "human confirmation (D5), never assumed from the compose signal alone."
        )
    if docker["has_compose"] or docker["has_dockerfile"]:
        return CONDICIONAL, (
            "Docker present but without a Swarm signature — may or may not have a "
            "production stack managed by this harness; confirm has_prod_stack manually."
        )
    return NAO_APLICAVEL, "No Dockerfile/compose detected — no production stack signal."


def _rule_e2e(facts: dict) -> tuple[str, str]:
    e2e_frameworks = {"playwright", "cypress"}
    hit = e2e_frameworks & set(facts["test_frameworks"])
    if hit:
        return CONDICIONAL, f"E2E framework detected ({', '.join(sorted(hit))}) — confirm the fixed admin user credentials (has_e2e)."
    return NAO_APLICAVEL, "No E2E framework (Playwright/Cypress) detected."


def _rule_icones_lucide(facts: dict) -> tuple[str, str]:
    wf = facts["web_framework"]
    if wf in {"nextjs", "remix", "vite-spa"}:
        return CONDICIONAL, f"React-like web framework ('{wf}') detected — confirm whether the project uses Lucide as its icon library."
    return NAO_APLICAVEL, "No React-like web framework — the Lucide icons rule does not apply."


def _rule_no_scaley_dropdown(facts: dict) -> tuple[str, str]:
    wf = facts["web_framework"]
    if wf in {"nextjs", "remix", "vite-spa"}:
        return CONDICIONAL, f"React-like web framework ('{wf}') detected — the dropdown animation rule only applies to overlay/CSS components of this kind of stack."
    return NAO_APLICAVEL, "No React-like web framework — no CSS overlay for the rule to apply to."


def _rule_web_dev_port(facts: dict) -> tuple[str, str]:
    if facts["web_framework"] is not None:
        return APLICAVEL, f"Web framework '{facts['web_framework']}' detected — the dev port guard applies."
    return NAO_APLICAVEL, "No web framework detected — no dev server whose port needs a guard."


def _rule_ui_skills_bundle(facts: dict) -> tuple[str, str]:
    # The 3 generic UI skills (component playbook, responsiveness framework,
    # className mining workflow) only make sense with a component frontend —
    # same signal as _rule_ui_evidence_gate, but without requiring Playwright
    # (they are not an evidence gate, they are reference content; installing
    # without extra confirmation is safe, unlike the ds-gate which needs to
    # confirm Tailwind/tokens).
    wf = facts["web_framework"]
    if not facts["has_frontend_ui"]:
        detail = f" (detected framework '{wf}' is backend/API, does not render UI)" if wf else ""
        return NAO_APLICAVEL, f"No FRONTEND framework detected{detail} — UI component playbooks do not apply."
    return APLICAVEL, f"Frontend framework '{wf}' detected — UI playbooks apply."


# Component -> rule table. Name matches the real path/skill/hookify
# (see templates/{% if use_claude %}.claude{% endif %}/**).
COMPONENTS: list[_ComponentRule] = [
    ("hookify.bare-python", "hookify", _rule_generic_always_on),
    ("hookify.mass-sed", "hookify", _rule_generic_always_on),
    ("hookify.relative-cd", "hookify", _rule_generic_always_on),
    ("hookify.icones-lucide", "hookify", _rule_icones_lucide),
    ("hookify.no-scaley-dropdown", "hookify", _rule_no_scaley_dropdown),
    ("hookify.web-dev-port", "hookify", _rule_web_dev_port),
    ("hookify.db-port-5432", "hookify", _rule_generic_always_on),
    ("hookify.prod-destroy", "hookify-prod", _rule_prod_guards),
    ("hookify.prod-image-source", "hookify-prod", _rule_prod_guards),
    ("hookify.prod-prune", "hookify-prod", _rule_prod_guards),
    ("hookify.prod-push-latest", "hookify-prod", _rule_prod_guards),
    ("hookify.prod-update-monitor", "hookify-prod", _rule_prod_guards),
    ("hook.ui-evidence-gate", "hook", _rule_ui_evidence_gate),
    ("hook.ds-gate-posttool", "hook", _rule_ds_gate_posttool),
    ("hook.understand-context-inject", "hook", _rule_understand_apps_incremental),
    ("hook.understand-apps-diff-guard", "hook", _rule_understand_apps_incremental),
    ("skill.understand-apps-incremental", "skill", _rule_understand_apps_incremental),
    ("skill.deploy-prod-stack", "skill", _rule_prod_guards),
    ("skill.ui-evidence", "skill", _rule_ui_evidence_gate),
    ("skill.ui-skills-bundle", "skill", _rule_ui_skills_bundle),
    ("has_e2e", "answer", _rule_e2e),
    ("skill.git-delivery", "skill", _rule_generic_always_on),
    ("skill.marathon", "skill", _rule_generic_always_on),
    ("skill.prova-de-conclusao", "skill", _rule_generic_always_on),
    ("skill.grill-me", "skill", _rule_generic_always_on),
    ("skill.adversarial-review", "skill", _rule_generic_always_on),
    ("skill.repo-wiki-curator", "skill", _rule_generic_always_on),
    ("skill.ref-integrity", "skill", _rule_generic_always_on),
    ("skill.deliverable-contract", "skill", _rule_generic_always_on),
    ("hook.lessons-inject", "hook", _rule_generic_always_on),
    ("hook.completion-gate", "hook", _rule_generic_always_on),
    ("hook.subagent-throttle", "hook", _rule_generic_always_on),
    ("hook.lei-zero-kickoff", "hook", _rule_generic_always_on),
    ("hook.git-doctor", "hook", _rule_generic_always_on),
    ("hook.marathon-reinject", "hook", _rule_generic_always_on),
    ("hook.marathon-precompact", "hook", _rule_generic_always_on),
    ("hook.marathon-stop-gate", "hook", _rule_generic_always_on),
    ("hook.reap-leaks", "hook", _rule_generic_always_on),
    ("hook.deliverable-scrub-gate", "hook", _rule_generic_always_on),
]


def classify(facts: dict) -> dict:
    report = []
    for name, category, rule in COMPONENTS:
        status, reason = rule(facts)
        report.append({"component": name, "category": category, "status": status, "reason": reason})
    counts = {APLICAVEL: 0, NAO_APLICAVEL: 0, CONDICIONAL: 0}
    for row in report:
        counts[row["status"]] += 1
    return {"components": report, "counts": counts}


# =============================================================================
# --- MEMORY SURFACES (local read-write vs global read-only, §5 of the plan) ---
# =============================================================================

def _slugify_root(root: str) -> str:
    """Same rule observed in docs/planning/research/08-memory-surfaces.md
    finding 3: absolute cwd with '/' -> '-'. Slug is ALWAYS computed from the
    target repo ROOT (git_root), never from the invocation CWD — that is the
    documented pitfall (running from apps/web/ produces a different slug)."""
    return root.replace("/", "-")


def memory_surfaces(facts: dict) -> dict:
    home = Path(os.environ.get("HOME", str(Path.home())))
    target = Path(facts["target"])
    root = facts.get("git_root") or str(target)
    slug = _slugify_root(root)

    global_claude = {
        "claude_md_global": (home / ".claude" / "CLAUDE.md").is_file(),
        "claude_rules_global": sorted(
            p.name for p in (home / ".claude" / "rules").glob("*.md")
        ) if (home / ".claude" / "rules").is_dir() else [],
        "claude_settings_global": (home / ".claude" / "settings.json").is_file(),
        "claude_project_memory_dir": str(home / ".claude" / "projects" / slug / "memory"),
        "claude_project_memory_exists": (home / ".claude" / "projects" / slug / "memory").is_dir(),
    }
    global_codex = {
        "agents_md_global": (home / ".codex" / "AGENTS.md").is_file(),
        "config_toml_global": (home / ".codex" / "config.toml").is_file(),
        "rules_global": sorted(
            p.name for p in (home / ".codex" / "rules").glob("*.rules")
        ) if (home / ".codex" / "rules").is_dir() else [],
        "memories_sqlite_present": any((home / ".codex").glob("memories_*.sqlite")),
    }

    return {
        "slug_computed_from": root,
        "local": facts["local_memory_surfaces"],
        "global_claude_READONLY": global_claude,
        "global_codex_READONLY": global_codex,
        "policy": (
            "GLOBAL surfaces are ONLY DETECTED AND REPORTED — never written by "
            "harness-init (docs/planning/00-plano-consolidado.md §5). NEVER copy the "
            "'env' key from ~/.claude/settings.json (it may contain a secret in "
            "cleartext, finding 4 of report 08)."
        ),
    }


# =============================================================================
# --- ANSWERS (SAFE suggestions for copier --data; nothing blocking here) ---
# =============================================================================

# A3 (adversarial review post-v1.0.0, real gap): map of NAO_APLICAVEL component -> Copier flag
# that should become `false`. Before this fix, the scanner CLASSIFIED a module as NAO_APLICAVEL
# (e.g. UI in a pure backend) but `suggest_answers()` never materialized that into `use_*` — the
# render proceeded with copier.yml's `true` defaults and installed the module anyway. Only the
# components whose rule can return NAO_APLICAVEL deterministically (without requiring human
# confirmation — CONDICIONAL is excluded, same D5 rule as the rest of this function) go
# here. `skill.ds-gate`/`hook.ds-gate-posttool` is CONDICIONAL even without a frontend (it never
# becomes NAO_APLICAVEL on its own from a missing Tailwind signal) — EXCEPT when there is no
# frontend at all, a case in which the rule itself already returns NAO_APLICAVEL (see _rule_ds_gate_posttool).
_NAO_APLICAVEL_TO_FALSE_FLAG: dict[str, str] = {
    "hook.ui-evidence-gate": "use_ui_evidence",
    "hook.ds-gate-posttool": "use_ds_gate",
    "hookify.icones-lucide": "use_icon_guard",
    "skill.ui-skills-bundle": "use_ui_skills",
}


def suggest_answers(facts: dict) -> dict:
    """Only suggests values that are ALWAYS safe to apply without additional
    human confirmation (derived names, detected ports, use_* flags that the
    deterministic classification already rejected as NAO_APLICAVEL). Never
    includes has_prod_stack/harness_understand_apps_root/has_e2e — those are
    CONDICIONAL and are deliberately left out of here (D5: nothing activated
    silently); the skill presents them separately for confirmation."""
    target = Path(facts["target"])
    project_name = re.sub(r"[^a-z0-9-]", "-", target.name.lower()).strip("-") or "my-project"
    project_name = re.sub(r"-{2,}", "-", project_name)
    if project_name and not project_name[0].isalpha():
        project_name = f"p-{project_name}"

    answers: dict = {
        "project_name": project_name,
        "project_root": str(target),
    }
    ports = facts["ports_detected"]
    if ports:
        # simple heuristic: smallest plausible API port (8xxx/1xxx/3xxx except 3000, common for web)
        web_candidates = [p for p in ports if p in (3000, 3001, 5173, 8080)]
        api_candidates = [p for p in ports if p not in web_candidates]
        if web_candidates:
            answers["harness_dev_web_port"] = web_candidates[0]
        if api_candidates:
            answers["harness_dev_api_port"] = api_candidates[0]

    # A3: materialize NAO_APLICAVEL -> use_*=false (the render stops installing
    # the module the scanner itself rejected, instead of falling back to the `true` default).
    report = classify(facts)
    for row in report["components"]:
        flag = _NAO_APLICAVEL_TO_FALSE_FLAG.get(row["component"])
        if flag and row["status"] == NAO_APLICAVEL:
            answers[flag] = False

    return answers


# =============================================================================
# --- CLI ---
# =============================================================================

def _target_from_args(args: list[str]) -> Path:
    if "--target" in args:
        idx = args.index("--target")
        return Path(args[idx + 1]).resolve()
    return Path.cwd().resolve()


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: scan_project.py {scan|classify|memory-surfaces|answers|all} [--target DIR]", file=sys.stderr)
        return 1
    cmd, rest = argv[0], argv[1:]
    target = _target_from_args(rest)
    facts = scan(target)

    if cmd == "scan":
        out = facts
    elif cmd == "classify":
        out = classify(facts)
    elif cmd == "memory-surfaces":
        out = memory_surfaces(facts)
    elif cmd == "answers":
        out = suggest_answers(facts)
    elif cmd == "all":
        out = {
            "scan": facts,
            "classify": classify(facts),
            "memory_surfaces": memory_surfaces(facts),
            "answers": suggest_answers(facts),
        }
    else:
        print(f"unknown command: {cmd}", file=sys.stderr)
        return 1

    print(json.dumps(out, indent=2, ensure_ascii=False, sort_keys=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
