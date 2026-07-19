#!/usr/bin/env python3
"""Lint da wiki Karpathy do REPOSITÓRIO-ALVO inteiro (docs/), não só uma categoria especializada.

Porte da versão FORTE do `guto-wiki`
(padronizacao-documentacao/artefatos/scripts/docs-wiki-lint.py, 312 linhas —
ver docs/planning/research/01-guto-wiki.md §b) para o `engine/` do
harness-wiki. Duas mudanças estruturais em relação à fonte, nenhuma
mudança de REGRA:

1. `load_config()`/`config_csv()` locais foram REMOVIDOS — este script
   importa `get_config`/`get_config_csv`/`project_root` de
   `_tooling_conf.py` (o parser ÚNICO do framework, ver seu docstring). O
   guto-wiki implementou o mesmo parser 3x sem extrair
   (docs/planning/research/01-guto-wiki.md §b, "Observações estruturais"
   item 1) — este porte não repete o erro.
2. `ROOT` deixou de ser `Path(__file__).resolve().parents[1]` (que na
   guto-wiki assumia o script morando em `<repo>/scripts/`, ou seja
   `parents[1]` = raiz do próprio repo que está sendo lintado). `ROOT` agora
   vem de `_tooling_conf.project_root()` (HARNESS_PROJECT_ROOT ->
   CLAUDE_PROJECT_DIR -> `git rev-parse --show-toplevel` -> cwd).

MATERIALIZAÇÃO (R2, harness-wiki — plano de resgate §2 item "Distribuição de
lint"): cópia deste arquivo (autoria em `engine/lint/docs_wiki_lint.py`,
dentro do repo harness-wiki) para `.harness/lib/docs_wiki_lint.py` no
projeto-alvo, no MESMO diretório onde `_tooling_conf.py`/`scan_project.py`/
`ds-gate.sh` já são materializados via Copier (padrão estabelecido em F0/F5,
não uma convenção nova). Diferença de layout vs. a cópia-fonte em
`engine/lint/`: lá o script mora um nível ABAIXO de `_tooling_conf.py`
(`engine/lint/` vs `engine/`), aqui os dois vivem LADO A LADO em
`.harness/lib/` — por isso o `sys.path.insert` abaixo usa
`Path(__file__).resolve().parent` (não `.parents[1]`), igual a
`ds-pairs-check.py`/`ds-pair-eval.py` no mesmo diretório. Antes desta
materialização, `docs/SCHEMA.md.jinja`, `AGENTS.md.jinja` e a skill
`repo-wiki-curator` mandavam rodar `engine/lint/docs_wiki_lint.py` ou
`scripts/docs-wiki-lint.py` — nenhum dos dois existe no projeto-alvo
(`engine/` é interno ao framework-doador; `scripts/docs-wiki-lint.py` era o
nome do script no harness-doador de referência, nunca portado) — comando
quebrado no primeiro uso. Esta materialização + a atualização de toda a
prosa para `.harness/lib/docs_wiki_lint.py` fecha esse path-fantasma.

Regras (docs/SCHEMA.md do projeto-alvo):
- FAIL: todo .md não-estrutural precisa estar citado individualmente ou coberto por uma coleção
  explicitamente indexada em algum index.md/log.md/README.md sob docs/.
- FAIL: arquivo não-markdown (json/png/pdf/...) precisa estar citado pelo nome ou coberto por uma coleção
  explicitamente indexada (containers genéricos sources/assets/img/reports não contam).
- WARN: naming de Markdown fora do padrão §2 (kebab-case; event=YYYY-MM-DD-slug; sequenced=NNNN-slug).
  Não bloqueia por default — a migração de nomes é incremental via loop. Use --strict-naming para tornar FAIL.

Uso:
  python3 .harness/lib/docs_wiki_lint.py                 # repo-alvo inteiro (docs/)
  python3 .harness/lib/docs_wiki_lint.py --scope <categoria>     # só uma categoria (usado por gates)
  python3 .harness/lib/docs_wiki_lint.py --strict-naming # naming também bloqueia
  python3 .harness/lib/docs_wiki_lint.py --worktree      # diff local vs HEAD
  python3 .harness/lib/docs_wiki_lint.py --staged        # diff staged/pre-commit
  python3 .harness/lib/docs_wiki_lint.py --diff-base <ref>  # CI/PR/push
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # .harness/lib/
from _tooling_conf import get_config, get_config_csv, project_root  # noqa: E402

ROOT = project_root()
DOCS = ROOT / get_config("HARNESS_DOCS_DIR", "docs")

STRUCTURAL = {"index.md", "log.md", "SCHEMA.md", "README.md"}
CAPS_OK = {"README.md", "SCHEMA.md", "CLAUDE.md", "AGENTS.md", "LICENSE", "LICENSE.md", "PROVENANCE.md"}
GENERIC_DIRS = {"sources", "assets", "img", "images", "reports", "docs", "_arquivo"}
IGNORED_DIRS = set(get_config_csv("IGNORED_TOOL_DIRS", [".understand-anything", ".anythingllm"]))
# kebab minúsculo, com prefixo opcional de data (event) ou número (sequenced); ponto só p/ versão tipo v2.2
NAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}-|\d+-)?[a-z0-9]+([a-z0-9.\-]*[a-z0-9])?\.[a-z0-9]+$")
# data (YYYY-MM-DD) presente mas NÃO como prefixo → event doc com data em sufixo (§2: deve ser prefixo)
DATE_ANY = re.compile(r"\d{4}-\d{2}-\d{2}")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LOG_HEADING_RE = re.compile(r"^## \[(\d{4}-\d{2}-\d{2}|sem-data)\] [^·]+ · .+")
STRAY_TOOL_RE = re.compile(r"^\s*</(content|invoke|antml:invoke|antml:parameter)>\s*$")


def collect_index_corpus(scope_dir: Path) -> str:
    """Concatena índices sob docs/ (o topo sempre conta), para checar menção."""
    parts: list[str] = []
    for name in ("index.md", "log.md", "README.md"):
        top = DOCS / name
        if top.exists():
            parts.append(top.read_text(encoding="utf-8"))
    for idx in DOCS.rglob("index.md"):
        parts.append(idx.read_text(encoding="utf-8"))
    for lg in DOCS.rglob("log.md"):
        parts.append(lg.read_text(encoding="utf-8"))
    for readme in DOCS.rglob("README.md"):
        parts.append(readme.read_text(encoding="utf-8"))
    return "\n".join(parts)


def mentioned(rel: Path, corpus: str) -> bool:
    return rel.as_posix() in corpus or rel.name in corpus


def collection_mentioned(rel: Path, corpus: str) -> bool:
    """Aceita cobertura por coleção explícita, sem deixar top-level genérico cobrir tudo."""
    parts = rel.parts[:-1]
    for i in range(len(parts), 1, -1):
        leaf = parts[i - 1]
        if leaf in GENERIC_DIRS:
            continue
        ancestor = "/".join(parts[:i])
        if (
            f"{ancestor}/" in corpus
            or ancestor in corpus
            or f"{leaf}/" in corpus
            or f"`{leaf}`" in corpus
        ):
            return True
    return False


FOREIGN_LIVE_FORBIDDEN = ("_arquivo/",)


def check_no_foreign_live_links(base: Path) -> list[str]:
    """Índice vivo (`index.md`) que linka `_arquivo/`.

    Em alguns repos isso pode ser FAIL; neste template fica WARN porque índices podem usar links a
    `_arquivo/` como wayfinding rotulado ("históricos", "superados", "prova em"). WARN surfacia para
    o olho humano na curadoria sem quebrar o verde. `log.md` é isento por ser registro temporal."""
    errs: list[str] = []
    for idx in sorted(base.rglob("index.md")):
        if any(part in IGNORED_DIRS for part in idx.relative_to(DOCS).parts):
            continue
        rel = idx.relative_to(DOCS)
        for m in re.finditer(r"\]\(([^)]+)\)", idx.read_text(encoding="utf-8")):
            tgt = m.group(1).split("#")[0].strip().lstrip("./")
            if any(tok in tgt for tok in FOREIGN_LIVE_FORBIDDEN):
                errs.append(f"índice vivo linka fonte arquivada: {rel} -> {m.group(1)}")
    return errs


def check_log_format(base: Path) -> list[str]:
    errs: list[str] = []
    for log in sorted(base.rglob("log.md")):
        if any(part in IGNORED_DIRS for part in log.relative_to(DOCS).parts):
            continue
        previous: str | None = None
        headings = [line for line in log.read_text(encoding="utf-8").splitlines() if line.startswith("## ")]
        if not headings:
            errs.append(f"{log.relative_to(DOCS)}: sem entradas ## [YYYY-MM-DD]")
        for line in headings:
            if not LOG_HEADING_RE.match(line):
                errs.append(f"{log.relative_to(DOCS)}: heading fora do formato temporal: {line}")
                continue
            date = line.split("]", 1)[0].removeprefix("## [")
            if date != "sem-data":
                if previous and previous != "sem-data" and date > previous:
                    errs.append(f"{log.relative_to(DOCS)}: log fora de ordem temporal decrescente: {line}")
                previous = date
            else:
                previous = "sem-data"
    return errs


def check_frontmatter_updated(base: Path) -> list[str]:
    errs: list[str] = []
    for path in sorted(base.rglob("*.md")):
        if path.name in STRUCTURAL:
            continue
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            continue
        end = text.find("\n---\n", 4)
        if end == -1:
            errs.append(f"{path.relative_to(DOCS)}: frontmatter nao fechado")
            continue
        frontmatter = text[4:end]
        updated = re.search(r"^updated:\s*[\"']?([^\"'\n]+)[\"']?\s*$", frontmatter, flags=re.M)
        if updated and not DATE_RE.match(updated.group(1)):
            errs.append(f"{path.relative_to(DOCS)}: updated fora de YYYY-MM-DD: {updated.group(1)!r}")
    return errs


def check_stray_tool_tags(base: Path) -> list[str]:
    errs: list[str] = []
    for path in sorted(base.rglob("*.md")):
        if any(part in IGNORED_DIRS for part in path.relative_to(DOCS).parts):
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if STRAY_TOOL_RE.match(line):
                errs.append(f"{path.relative_to(DOCS)}:{i}: tag de ferramenta solta -> {line.strip()!r}")
    return errs


def git_diff_name_status(diff_base: str | None, staged: bool, worktree: bool, failures: list[str]) -> list[tuple[str, list[str]]]:
    if not diff_base and not staged and not worktree:
        return []
    cmd = ["git", "diff", "--name-status", "--find-renames"]
    if staged:
        cmd.insert(2, "--cached")
    elif worktree:
        cmd.append("HEAD")
    else:
        cmd.append(f"{diff_base}...HEAD")
    proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    if proc.returncode != 0:
        failures.append(f"git diff falhou: {proc.stderr.strip() or proc.stdout.strip()}")
        return []
    entries: list[tuple[str, list[str]]] = []
    for raw in proc.stdout.splitlines():
        parts = raw.split("\t")
        if len(parts) >= 2:
            entries.append((parts[0], parts[1:]))
    if worktree:
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        entries.extend(("A", [path]) for path in untracked.stdout.splitlines() if path)
    return entries


def check_diff_policy(diff_base: str | None, staged: bool, worktree: bool, failures: list[str]) -> None:
    entries = git_diff_name_status(diff_base, staged, worktree, failures)
    if not entries:
        return
    docs_entries = [(status, paths) for status, paths in entries if any(path.startswith("docs/") for path in paths)]
    if not docs_entries:
        return
    log_changed = any("docs/log.md" in paths for _, paths in entries)
    index_changed = any(path.endswith(("index.md", "README.md")) and path.startswith("docs/") for _, paths in entries for path in paths)
    for status, paths in docs_entries:
        old_path = paths[0]
        new_path = paths[-1]
        if any(path.endswith(".md") for path in {old_path, new_path}) and status[0] in {"A", "D", "R"}:
            if not log_changed:
                failures.append(f"{new_path}: markdown novo/removido/renomeado exige atualizar docs/log.md no mesmo diff")
            if status.startswith(("A", "R")) and not index_changed:
                failures.append(f"{new_path}: markdown novo/renomeado exige atualizar index/README da categoria no mesmo diff")


def naming_ok(rel: Path) -> bool:
    name = rel.name
    if name in CAPS_OK or name in {"index.md", "log.md"}:
        return True
    if not NAME_RE.match(name):
        return False
    # §2: event doc datado deve ter a data em PREFIXO (ordena no ls). Data em sufixo é violação.
    if DATE_ANY.search(name) and not re.match(r"^\d{4}-\d{2}-\d{2}-", name):
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope")
    parser.add_argument("--strict-naming", action="store_true")
    parser.add_argument("--diff-base")
    parser.add_argument("--staged", action="store_true")
    parser.add_argument("--worktree", action="store_true")
    args = parser.parse_args()

    strict_naming = args.strict_naming
    scope = args.scope
    base = DOCS / scope if scope else DOCS
    corpus = collect_index_corpus(base)

    failures: list[str] = []
    naming_warns: list[str] = []

    for f in sorted(base.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(DOCS)
        if any(part in IGNORED_DIRS for part in rel.parts):
            continue
        if rel.name in STRUCTURAL and f.suffix == ".md":
            continue
        # cobertura: menção individual ou coleção explicitamente indexada.
        covered = mentioned(rel, corpus) or collection_mentioned(rel, corpus)
        if not covered:
            failures.append(f"órfão (sem menção em index/log): {rel}")
        # naming (§2)
        if f.suffix == ".md" and not naming_ok(rel):
            naming_warns.append(f"naming fora do padrão §2: {rel}")

    foreign_warns = check_no_foreign_live_links(base)
    failures.extend(check_log_format(base))
    failures.extend(check_frontmatter_updated(base))
    failures.extend(check_stray_tool_tags(base))
    check_diff_policy(args.diff_base, args.staged, args.worktree, failures)

    if strict_naming:
        failures.extend(naming_warns)
        naming_warns = []

    if naming_warns:
        print(f"docs-wiki-lint: {len(naming_warns)} aviso(s) de naming (WARN, migração incremental):")
        for w in naming_warns[:60]:
            print(f"  ~ {w}")
        if len(naming_warns) > 60:
            print(f"  ... +{len(naming_warns) - 60} outros")

    if foreign_warns:
        print(f"docs-wiki-lint: {len(foreign_warns)} índice(s) vivo(s) linkando _arquivo/ (WARN — confira se é wayfinding rotulado):")
        for w in foreign_warns:
            print(f"  ~ {w}")

    if failures:
        print("docs-wiki-lint: FAIL")
        for x in failures:
            print(f"- {x}")
        return 1

    scope_txt = f" (scope={scope})" if scope else ""
    print(f"docs-wiki-lint: OK{scope_txt}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
