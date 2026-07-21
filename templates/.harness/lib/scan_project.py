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
  scan_project.py scan             [--target DIR] [--component-root DIR ...] [--json]
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
from typing import Iterable

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
    re.compile(r"(?:--port|-p)(?:=|\s+)(\d{2,5})"),
    re.compile(r"\b(\d{2,5}):(\d{2,5})\b"),  # docker-compose "host:container"
]
SHELL_PORT_ARRAY = re.compile(r"\bPORTS?\s*=\s*\(([^)]*)\)", re.I)

# Discovery is deliberately bounded.  These are product/source roots, not a
# request to recursively crawl the repository (which would classify fixtures,
# vendored code and build outputs as real applications).
DIRECT_COMPONENT_DIRS = {
    "frontend", "backend", "web", "api", "client", "server", "worker",
}
COMPONENT_CONTAINER_DIRS = {"apps", "packages", "services"}
EXCLUDED_COMPONENT_PARTS = {
    ".git", ".hg", ".svn", ".next", ".turbo", ".venv", "venv",
    "node_modules", "vendor", "dist", "build", "coverage", "fixtures",
    "examples", "__pycache__",
}

SOURCE_LANGUAGE_SUFFIXES = {
    ".py": "python", ".sh": "shell", ".bash": "shell",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".go": "go", ".rs": "rust",
}


def _source_inventory(target: Path) -> dict:
    """Multi-signal inventory so an auxiliary manifest cannot define the repo."""
    counts: dict[str, int] = {}
    files = 0
    try:
        paths = target.rglob("*")
        for path in paths:
            try:
                rel = path.relative_to(target)
                if any(part in EXCLUDED_COMPONENT_PARTS for part in rel.parts) or not path.is_file():
                    continue
            except OSError:
                continue
            language = SOURCE_LANGUAGE_SUFFIXES.get(path.suffix.lower())
            if language:
                counts[language] = counts.get(language, 0) + 1
                files += 1
    except OSError:
        pass
    ordered = sorted(counts.items(), key=lambda row: (-row[1], row[0]))
    primary = ordered[0][0] if ordered else None
    confidence = "high" if files >= 10 and ordered and ordered[0][1] / files >= 0.5 else "medium" if files else "none"
    return {"counts": dict(ordered), "files": files, "primary_language": primary, "confidence": confidence}


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
    requirements = (_read_text(target / "requirements.txt") or "").lower()
    pytest_dependency = bool(re.search(r"(?m)^\s*pytest(?:\b|[-_])", requirements))
    if pytest_ini or pytest_dependency or "pytest" in pyproject.get("tool", {}) or (target / "conftest.py").exists():
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
    return sorted({row["port"] for row in _detect_port_evidence(target, target)})


def _relative_source(path: Path, project_root: Path) -> str:
    try:
        return path.relative_to(project_root).as_posix() or "."
    except ValueError:
        return str(path)


def _detect_port_evidence(target: Path, project_root: Path) -> list[dict]:
    """Return ports together with their provenance.

    Only known configuration surfaces in the component directory are read.
    Shell launchers are intentionally restricted to a small allowlist rather
    than scanning every source file for number-shaped strings.
    """
    evidence: list[dict] = []
    candidates = list(target.glob(".env*")) + [
        target / n for n in (
            "docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml",
            "package.json", "dev.sh", "start.sh", "run.sh",
        )
    ]
    for p in candidates:
        if not p.is_file():
            continue
        text = _read_text(p)
        if not text:
            continue
        if p.suffix == ".sh":
            for array_match in SHELL_PORT_ARRAY.finditer(text):
                for raw_port in re.findall(r"\b\d{2,5}\b", array_match.group(1)):
                    value = int(raw_port)
                    if 1024 <= value <= 65535:
                        evidence.append({
                            "port": value,
                            "source": _relative_source(p, project_root),
                            "confidence": "high",
                        })
        for pat in PORT_PATTERNS:
            for m in pat.finditer(text):
                for g in m.groups():
                    if g and g.isdigit():
                        v = int(g)
                        if 1024 <= v <= 65535:
                            evidence.append({
                                "port": v,
                                "source": _relative_source(p, project_root),
                                "confidence": "high" if p.name == "package.json" or p.name.startswith(".env") or "compose" in p.name else "medium",
                            })
    # Stable and duplicate-free even when a compose mapping captures host and
    # container ports with the same value.
    unique = {(row["port"], row["source"], row["confidence"]): row for row in evidence}
    return [unique[key] for key in sorted(unique)]


def _manifest_names(root: Path) -> list[str]:
    return [
        name for name in MANIFEST_PRIORITY
        if (root / name).is_file() and not (root / name).is_symlink()
    ]


def _safe_component_dir(target: Path, candidate: Path) -> Path | None:
    """Resolve a candidate without accepting an escape or symlinked root."""
    if candidate.is_symlink() or not candidate.is_dir():
        return None
    try:
        resolved_target = target.resolve(strict=True)
        lexical_relative = candidate.absolute().relative_to(target.absolute())
        cursor = target.absolute()
        for part in lexical_relative.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                return None
        resolved = candidate.resolve(strict=True)
        relative = resolved.relative_to(resolved_target)
    except (OSError, ValueError):
        return None
    if any(part in EXCLUDED_COMPONENT_PARTS for part in relative.parts):
        return None
    return resolved


def _workspace_patterns(target: Path) -> list[str]:
    patterns: list[str] = []
    package = _read_json(target / "package.json")
    workspaces = package.get("workspaces", [])
    if isinstance(workspaces, dict):
        workspaces = workspaces.get("packages", [])
    if isinstance(workspaces, list):
        patterns.extend(item for item in workspaces if isinstance(item, str))

    # pnpm-workspace.yaml is parsed only for its documented list of package
    # globs.  No general YAML interpretation is attempted.
    text = _read_text(target / "pnpm-workspace.yaml") or ""
    in_packages = False
    for raw in text.splitlines():
        if re.match(r"^packages\s*:\s*$", raw):
            in_packages = True
            continue
        if in_packages and re.match(r"^[A-Za-z_]", raw):
            break
        match = re.match(r"^\s*-\s*['\"]?([^'\"#]+?)['\"]?\s*$", raw) if in_packages else None
        if match:
            patterns.append(match.group(1).strip())
    return patterns


def _expand_bounded_workspace_pattern(target: Path, pattern: str) -> Iterable[Path]:
    """Expand only one-level workspace globs (e.g. apps/*), never **."""
    clean = pattern.strip().rstrip("/")
    if not clean or clean.startswith(("/", "../")) or "**" in clean:
        return []
    parts = Path(clean).parts
    if len(parts) > 2 or any(part in EXCLUDED_COMPONENT_PARTS for part in parts):
        return []
    if "*" not in clean:
        return [target / clean]
    if len(parts) == 2 and parts[1] == "*" and "*" not in parts[0]:
        parent = target / parts[0]
        try:
            return sorted((p for p in parent.iterdir() if p.is_dir()), key=lambda p: p.name) if parent.is_dir() else []
        except OSError:
            return []
    return []


def _discover_component_roots(target: Path, explicit_roots: list[str] | None = None) -> list[tuple[Path, str]]:
    """Discover manifest-bearing component roots with a strict depth bound."""
    candidates: dict[Path, str] = {}

    def add(candidate: Path, source: str) -> None:
        safe = _safe_component_dir(target, candidate)
        if safe is not None and _manifest_names(safe):
            candidates.setdefault(safe, source)

    add(target, "project-root")
    for raw in explicit_roots or []:
        candidate = Path(raw)
        add(candidate if candidate.is_absolute() else target / candidate, "explicit")

    for pattern in _workspace_patterns(target):
        for candidate in _expand_bounded_workspace_pattern(target, pattern):
            add(candidate, f"workspace:{pattern}")

    for name in sorted(DIRECT_COMPONENT_DIRS):
        add(target / name, f"conventional:{name}")

    # Brownfield repos often have sibling services with domain-specific names
    # (for example `faz-engine/`) and no workspace declaration. Scan exactly
    # one level of root children and require a supported manifest; exclusions
    # and _safe_component_dir keep dependencies, fixtures and symlinks out.
    try:
        root_children = sorted(target.iterdir(), key=lambda p: p.name)
    except OSError:
        root_children = []
    for child in root_children:
        if child.name in EXCLUDED_COMPONENT_PARTS:
            continue
        add(child, f"root-child:{child.name}")

    for container_name in sorted(COMPONENT_CONTAINER_DIRS):
        container = target / container_name
        if not container.is_dir() or container.is_symlink():
            continue
        try:
            children = sorted(container.iterdir(), key=lambda p: p.name)
        except OSError:
            continue
        for child in children:
            add(child, f"conventional:{container_name}/*")

    return sorted(candidates.items(), key=lambda row: (row[0] != target.resolve(), _relative_source(row[0], target)))


def _framework_evidence(component: Path, project_root: Path, framework: str | None) -> list[dict]:
    if framework is None:
        return []
    if framework in BACKEND_FRAMEWORKS and framework != "express" and (component / "requirements.txt").is_file():
        source = component / "requirements.txt"
    elif framework in BACKEND_FRAMEWORKS and framework != "express" and (component / "pyproject.toml").is_file():
        source = component / "pyproject.toml"
    elif (component / "package.json").is_file():
        source = component / "package.json"
    else:
        source = component / "pyproject.toml"
    return [{"value": framework, "source": _relative_source(source, project_root), "confidence": "high"}]


def _test_framework_evidence(component: Path, project_root: Path, frameworks: list[str]) -> list[dict]:
    evidence: list[dict] = []
    config_names = {
        "playwright": ("playwright.config.ts", "playwright.config.js", "playwright.config.mjs", "package.json"),
        "vitest": ("vitest.config.ts", "package.json"),
        "jest": ("jest.config.js", "jest.config.ts", "package.json"),
        "cypress": ("cypress.config.js", "package.json"),
        "pytest": ("pytest.ini", "pyproject.toml", "setup.cfg", "conftest.py", "requirements.txt"),
    }
    for framework in frameworks:
        name = next((n for n in config_names[framework] if (component / n).exists()), "package.json")
        evidence.append({"value": framework, "source": _relative_source(component / name, project_root), "confidence": "high"})
    return evidence


def _scan_component(component: Path, project_root: Path, discovery_source: str) -> dict:
    manifests = _manifest_names(component)
    manifest = manifests[0] if manifests else None
    language = MANIFEST_LANGUAGE.get(manifest) if manifest else None
    framework = _detect_web_framework(component, language)
    tests = _detect_test_frameworks(component)
    port_evidence = _detect_port_evidence(component, project_root)
    return {
        "path": _relative_source(component, project_root),
        "discovery_source": discovery_source,
        "manifests": manifests,
        "primary_manifest": manifest,
        "primary_language": language,
        "package_manager": _detect_package_manager(component, language),
        "web_framework": framework,
        "has_frontend_ui": framework in FRONTEND_FRAMEWORKS,
        "test_frameworks": tests,
        "ports_detected": sorted({row["port"] for row in port_evidence}),
        "evidence": {
            "web_frameworks": _framework_evidence(component, project_root, framework),
            "test_frameworks": _test_framework_evidence(component, project_root, tests),
            "ports": port_evidence,
        },
    }


def _detect_understand_root_offset(target: Path) -> str | None:
    """Heuristic: an 'apps/' subdirectory at the root with >=2 subfolders each
    containing its own manifest suggests a monorepo with PROJECT_ROOT != git-root
    (the PROJECT_ROOT≠git-root pitfall documented in the reference donor harness)."""
    apps_dir = target / "apps"
    safe_apps = _safe_component_dir(target, apps_dir)
    if safe_apps is None:
        return None
    sub_with_manifest = 0
    for child in safe_apps.iterdir():
        safe_child = _safe_component_dir(target, child)
        if safe_child is None:
            continue
        if _manifest_names(safe_child):
            sub_with_manifest += 1
    return "apps" if sub_with_manifest >= 2 else None


def scan(target: Path, explicit_component_roots: list[str] | None = None) -> dict:
    is_git = _sh(["git", "rev-parse", "--is-inside-work-tree"], target) == "true"
    git_root = _sh(["git", "rev-parse", "--show-toplevel"], target) if is_git else None

    component_roots = _discover_component_roots(target, explicit_component_roots)
    components = [_scan_component(path, target, source) for path, source in component_roots]
    root_component = next((row for row in components if row["path"] == "."), None)
    representative = root_component or next((row for row in components if row["has_frontend_ui"]), None)
    representative = representative or (components[0] if components else None)

    source_inventory = _source_inventory(target)
    manifest = representative["primary_manifest"] if representative else None
    language = representative["primary_language"] if representative else None
    # A child utility is evidence of a component, not authority over a
    # manifest-less polyglot framework repository.
    if root_component is None and source_inventory["files"] >= 10:
        manifest = None
        language = source_inventory["primary_language"]

    docker = _detect_docker(target)
    package_manager = representative["package_manager"] if representative and manifest else None
    frontend = next((row for row in components if row["has_frontend_ui"]), None)
    framework_component = frontend or next((row for row in components if row["web_framework"]), None)
    web_framework = framework_component["web_framework"] if framework_component else None
    test_frameworks = sorted({name for row in components for name in row["test_frameworks"]})
    root_port_evidence = _detect_port_evidence(target, target)
    all_port_evidence = root_port_evidence + [ev for row in components for ev in row["evidence"]["ports"] if row["path"] != "."]
    ports = sorted({row["port"] for row in all_port_evidence})
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
        "repository_role": "application" if root_component or web_framework else "tooling-framework",
        "source_inventory": source_inventory,
        "package_manager": package_manager,
        "web_framework": web_framework,
        "has_frontend_ui": web_framework in FRONTEND_FRAMEWORKS,
        "test_frameworks": test_frameworks,
        "components": components,
        "component_discovery": {
            "mode": "bounded-manifest",
            "max_depth": 2,
            "explicit_roots": explicit_component_roots or [],
            "excluded_parts": sorted(EXCLUDED_COMPONENT_PARTS),
        },
        "evidence": {"ports": all_port_evidence},
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
        if idx + 1 >= len(args):
            raise ValueError("--target requires a directory")
        return Path(args[idx + 1]).resolve()
    return Path.cwd().resolve()


def _component_roots_from_args(args: list[str]) -> list[str]:
    roots: list[str] = []
    for idx, value in enumerate(args):
        if value == "--component-root":
            if idx + 1 >= len(args):
                raise ValueError("--component-root requires a directory")
            roots.append(args[idx + 1])
    return roots


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: scan_project.py {scan|classify|memory-surfaces|answers|all} [--target DIR]", file=sys.stderr)
        return 1
    cmd, rest = argv[0], argv[1:]
    try:
        target = _target_from_args(rest)
        component_roots = _component_roots_from_args(rest)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    facts = scan(target, component_roots)

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
