#!/usr/bin/env python3
"""scan_project.py — scanner determinístico + classificador de aplicabilidade por stack (F5).

Motor do skill `harness-init`. ZERO chamada de LLM neste arquivo — blueprint
portado de `scan-project.mjs` do understand-anything (docs/planning/research/
07-autoconfig-patterns.md §A.4): "enumeração de arquivos, classificação por
extensão/nome, contagem, resolução de import e diffing estrutural são SEMPRE
determinísticos". A skill (SKILL.md) só decide COM BASE no JSON que este
script imprime — nunca reimplementa a lógica de detecção em prosa.

Decisão D5 (docs/planning/00-plano-consolidado.md §11): o framework instala
TUDO, mas cada componente é classificado APLICAVEL / NAO_APLICAVEL / CONDICIONAL
por REGRA (não por "achismo" de LLM). CONDICIONAL sempre exige confirmação
humana antes de ativar — nunca é assumido silenciosamente.

Zero dependência externa (stdlib puro, mesma decisão de `_tooling_conf.py` —
este script roda DENTRO de um projeto-alvo qualquer, que pode não ter PyYAML/
tomli instalado; `tomllib` é stdlib desde 3.11, usado só para TOML real
[pyproject.toml/Cargo.toml], YAML é sempre tratado por regex leve sobre texto
cru — não é um parser YAML completo, é deteccao de presença de chave).

CLI:
  scan_project.py scan             [--target DIR] [--json]
  scan_project.py classify         [--target DIR] [--json]
  scan_project.py memory-surfaces  [--target DIR] [--json]
  scan_project.py answers          [--target DIR] [--json]
  scan_project.py all              [--target DIR] [--json]   (as 4 chaves combinadas)

Todas as saídas são JSON em stdout (facilita a skill consumir sem regex).
Fail-open: qualquer exceção de leitura de arquivo individual é ignorada
(arquivo tratado como ausente), nunca derruba o scan inteiro.
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
except ModuleNotFoundError:  # pragma: no cover - só em Python <3.11, não suportado mas fail-open
    tomllib = None  # type: ignore[assignment]


# =============================================================================
# --- utilitários de leitura fail-open ---
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
# --- SCAN (determinístico) ---
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

# Ordem de prioridade quando múltiplos manifests coexistem (monorepo poliglota
# pega o primeiro da lista que existir na raiz — não soma linguagens).
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
            return "npm"  # default assumido, sem lockfile ainda
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
        # deteccao leve, nao parser YAML: presenca de bloco "deploy:" (Swarm-only key)
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
    """Heurística: subdiretório 'apps/' na raiz com >=2 subpastas contendo
    manifest próprio sugere monorepo com PROJECT_ROOT != git-root (a
    armadilha PROJECT_ROOT≠git-root documentada no harness-doador de referência)."""
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
# --- CLASSIFY (regra por componente, D5 — nunca LLM) ---
# =============================================================================

APLICAVEL = "APLICAVEL"
NAO_APLICAVEL = "NAO_APLICAVEL"
CONDICIONAL = "CONDICIONAL"

# Cada regra recebe o dict de `scan()` e devolve (status, motivo).
# Ordem = ordem de apresentação no relatório.
_ComponentRule = tuple  # (name, category, fn)


def _rule_generic_always_on(_facts: dict) -> tuple[str, str]:
    return APLICAVEL, "Metodologia/guarda genérica, sem dependência de stack."


def _rule_ui_evidence_gate(facts: dict) -> tuple[str, str]:
    wf = facts["web_framework"]
    has_playwright = "playwright" in facts["test_frameworks"]
    if not facts["has_frontend_ui"]:
        detail = f" (framework '{wf}' detectado é backend/API, não renderiza UI)" if wf else ""
        return NAO_APLICAVEL, f"Nenhum framework FRONTEND detectado{detail} — não há UI para capturar evidência visual."
    if has_playwright:
        return APLICAVEL, f"Framework frontend '{wf}' + Playwright detectados."
    return CONDICIONAL, (
        f"Framework frontend '{wf}' detectado mas Playwright não — instala inerte "
        "(hook fica no-op) até Playwright ser adicionado; confirmar antes de ativar."
    )


def _rule_ds_gate_posttool(facts: dict) -> tuple[str, str]:
    # Pós plano de resgate §R1a: o motor (.harness/lib/ds-gate.sh +
    # ds-pairs-check.py) não hardcoda mais "apps/web" — lê HARNESS_WEB_APP_DIR
    # de .harness/harness.conf (default ".") e é fail-open se o CSS de tokens
    # (DS_GATE_CSS_PATH) não existir. Mas só faz sentido em projeto com
    # Tailwind + tokens CSS (--var) num arquivo tipo globals.css — sinal que
    # este scanner não detecta hoje (nenhum fact de "usa Tailwind"); por isso
    # CONDICIONAL (nunca assumido automaticamente, D5), não APLICAVEL direto.
    wf = facts["web_framework"]
    if not facts["has_frontend_ui"]:
        detail = f" (framework '{wf}' detectado é backend/API, não renderiza UI)" if wf else ""
        return NAO_APLICAVEL, f"Nenhum framework FRONTEND detectado{detail} — ratchet de tokenização não se aplica."
    return CONDICIONAL, (
        f"Framework frontend '{wf}' detectado — hook é fail-open (no-op se "
        "HARNESS_WEB_APP_DIR/DS_GATE_CSS_PATH não existir), mas só faz sentido com "
        "Tailwind + tokens CSS (--var) num arquivo tipo globals.css; confirmar "
        "harness_web_app_dir/DS_GATE_CSS_PATH antes de contar com ele."
    )


def _rule_understand_apps_incremental(facts: dict) -> tuple[str, str]:
    candidate = facts["understand_apps_root_offset_candidate"]
    if candidate:
        return CONDICIONAL, (
            f"Detectado candidato a PROJECT_ROOT='{candidate}' (subpastas com "
            "manifest próprio) — confirmar valor exato de harness_understand_apps_root "
            "antes de ativar; nunca assumido automaticamente (D5)."
        )
    return NAO_APLICAVEL, (
        "Nenhum subdiretório tipo monorepo detectado na raiz — Understand Anything, "
        "se usado, provavelmente roda direto na raiz do git (sem a armadilha "
        "PROJECT_ROOT≠git-root que esta skill/hooks resolvem)."
    )


def _rule_prod_guards(facts: dict) -> tuple[str, str]:
    docker = facts["docker"]
    if docker["has_swarm_signal"]:
        return CONDICIONAL, (
            "docker-compose com bloco 'deploy:' (assinatura de Swarm) detectado — "
            "sugere stack de produção, mas has_prod_stack SEMPRE exige confirmação "
            "humana explícita (D5), nunca assumido só pelo sinal do compose."
        )
    if docker["has_compose"] or docker["has_dockerfile"]:
        return CONDICIONAL, (
            "Docker presente mas sem assinatura de Swarm — pode ou não ter stack de "
            "produção gerenciada por este harness; confirmar has_prod_stack manualmente."
        )
    return NAO_APLICAVEL, "Nenhum Dockerfile/compose detectado — sem sinal de stack de produção."


def _rule_e2e(facts: dict) -> tuple[str, str]:
    e2e_frameworks = {"playwright", "cypress"}
    hit = e2e_frameworks & set(facts["test_frameworks"])
    if hit:
        return CONDICIONAL, f"Framework E2E detectado ({', '.join(sorted(hit))}) — confirmar credenciais do usuário admin fixo (has_e2e)."
    return NAO_APLICAVEL, "Nenhum framework E2E (Playwright/Cypress) detectado."


def _rule_icones_lucide(facts: dict) -> tuple[str, str]:
    wf = facts["web_framework"]
    if wf in {"nextjs", "remix", "vite-spa"}:
        return CONDICIONAL, f"Framework web React-like ('{wf}') detectado — confirmar se o projeto usa Lucide como biblioteca de ícones."
    return NAO_APLICAVEL, "Sem framework web React-like — regra de ícones Lucide não se aplica."


def _rule_no_scaley_dropdown(facts: dict) -> tuple[str, str]:
    wf = facts["web_framework"]
    if wf in {"nextjs", "remix", "vite-spa"}:
        return CONDICIONAL, f"Framework web React-like ('{wf}') detectado — regra de animação de dropdown só se aplica a componentes overlay/CSS deste tipo de stack."
    return NAO_APLICAVEL, "Sem framework web React-like — sem overlay CSS a que a regra se aplique."


def _rule_web_dev_port(facts: dict) -> tuple[str, str]:
    if facts["web_framework"] is not None:
        return APLICAVEL, f"Framework web '{facts['web_framework']}' detectado — guarda de porta de dev se aplica."
    return NAO_APLICAVEL, "Nenhum framework web detectado — sem dev server cuja porta precise de guarda."


def _rule_ui_skills_bundle(facts: dict) -> tuple[str, str]:
    # As 3 skills genéricas de UI (playbook de componente, framework de
    # responsividade, workflow de mineração de className) só fazem sentido
    # com frontend de componentes — mesmo sinal de _rule_ui_evidence_gate,
    # mas sem exigir Playwright (não são gate de evidência, são conteúdo de
    # referência; instalar sem confirmação extra é seguro, ao contrário do
    # ds-gate que precisa confirmar Tailwind/tokens).
    wf = facts["web_framework"]
    if not facts["has_frontend_ui"]:
        detail = f" (framework '{wf}' detectado é backend/API, não renderiza UI)" if wf else ""
        return NAO_APLICAVEL, f"Nenhum framework FRONTEND detectado{detail} — playbooks de componente de UI não se aplicam."
    return APLICAVEL, f"Framework frontend '{wf}' detectado — playbooks de UI se aplicam."


# Tabela de componentes -> regra. Nome bate com o path/skill/hookify real
# (ver templates/{% if use_claude %}.claude{% endif %}/**).
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
# --- MEMORY SURFACES (local read-write vs global read-only, §5 do plano) ---
# =============================================================================

def _slugify_root(root: str) -> str:
    """Mesma regra observada em docs/planning/research/08-memory-surfaces.md
    achado 3: cwd absoluto com '/' -> '-'. Slug SEMPRE calculado a partir da
    RAIZ do repo-alvo (git_root), nunca do CWD de invocação — essa é a
    armadilha documentada (rodar de apps/web/ gera slug diferente)."""
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
            "Superfícies GLOBAL são SÓ DETECTADAS E REPORTADAS — nunca escritas por "
            "harness-init (docs/planning/00-plano-consolidado.md §5). NUNCA copiar a "
            "chave 'env' de ~/.claude/settings.json (pode conter segredo em claro, "
            "achado 4 do relatório 08)."
        ),
    }


# =============================================================================
# --- ANSWERS (sugestões SEGURAS para copier --data; nada bloqueante aqui) ---
# =============================================================================

# A3 (revisão adversarial pós-v1.0.0, gap real): mapa componente NAO_APLICAVEL -> flag Copier
# que deve virar `false`. Antes deste fix, o scanner CLASSIFICAVA um módulo como NAO_APLICAVEL
# (ex.: UI num backend puro) mas `suggest_answers()` nunca materializava isso em `use_*` — o
# render seguia com os defaults `true` do copier.yml e instalava o módulo mesmo assim. Só os
# componentes cuja regra pode retornar NAO_APLICAVEL de forma determinística (sem exigir
# confirmação humana — CONDICIONAL fica de fora, mesma regra D5 do resto desta função) entram
# aqui. `skill.ds-gate`/`hook.ds-gate-posttool` é CONDICIONAL mesmo sem frontend (nunca vira
# NAO_APLICAVEL sozinho por falta de sinal de Tailwind) — EXCETO quando não há frontend algum,
# caso em que a própria regra já retorna NAO_APLICAVEL (ver _rule_ds_gate_posttool).
_NAO_APLICAVEL_TO_FALSE_FLAG: dict[str, str] = {
    "hook.ui-evidence-gate": "use_ui_evidence",
    "hook.ds-gate-posttool": "use_ds_gate",
    "hookify.icones-lucide": "use_icon_guard",
    "skill.ui-skills-bundle": "use_ui_skills",
}


def suggest_answers(facts: dict) -> dict:
    """Só sugere valores que são SEMPRE seguros de aplicar sem confirmação
    humana adicional (nomes derivados, portas detectadas, flags use_* que a
    classificação determinística já rejeitou como NAO_APLICAVEL). Nunca
    inclui has_prod_stack/harness_understand_apps_root/has_e2e — esses são
    CONDICIONAL e ficam de fora daqui de propósito (D5: nada ativado
    silenciosamente); a skill os apresenta separadamente para confirmação."""
    target = Path(facts["target"])
    project_name = re.sub(r"[^a-z0-9-]", "-", target.name.lower()).strip("-") or "meu-projeto"
    project_name = re.sub(r"-{2,}", "-", project_name)
    if project_name and not project_name[0].isalpha():
        project_name = f"p-{project_name}"

    answers: dict = {
        "project_name": project_name,
        "project_root": str(target),
    }
    ports = facts["ports_detected"]
    if ports:
        # heurística simples: menor porta plausível de API (8xxx/1xxx/3xxx exceto 3000 comum de web)
        web_candidates = [p for p in ports if p in (3000, 3001, 5173, 8080)]
        api_candidates = [p for p in ports if p not in web_candidates]
        if web_candidates:
            answers["harness_dev_web_port"] = web_candidates[0]
        if api_candidates:
            answers["harness_dev_api_port"] = api_candidates[0]

    # A3: materializa NAO_APLICAVEL -> use_*=false (o render deixa de instalar
    # o módulo que o próprio scanner rejeitou, em vez de cair no default `true`).
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
