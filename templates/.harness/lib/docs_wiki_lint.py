#!/usr/bin/env python3
"""Karpathy wiki lint for the ENTIRE TARGET REPOSITORY (docs/), not just one specialized category.

Port of the STRONG version of `guto-wiki`
(padronizacao-documentacao/artefatos/scripts/docs-wiki-lint.py, 312 lines —
see docs/planning/research/01-guto-wiki.md §b) into orions-belt's `engine/`.
Two structural changes relative to the source, no change of RULE:

1. Local `load_config()`/`config_csv()` were REMOVED — this script imports
   `get_config`/`get_config_csv`/`project_root` from `_tooling_conf.py`
   (the framework's SINGLE parser, see its docstring). guto-wiki implemented
   the same parser 3x without extracting it
   (docs/planning/research/01-guto-wiki.md §b, "Structural observations"
   item 1) — this port does not repeat the mistake.
2. `ROOT` is no longer `Path(__file__).resolve().parents[1]` (which in
   guto-wiki assumed the script lived in `<repo>/scripts/`, i.e.
   `parents[1]` = the root of the repo being linted). `ROOT` now comes from
   `_tooling_conf.project_root()` (HARNESS_PROJECT_ROOT ->
   CLAUDE_PROJECT_DIR -> `git rev-parse --show-toplevel` -> cwd).

MATERIALIZATION (R2, orions-belt — rescue plan §2 item "Lint distribution"):
copy of this file (authored in `engine/lint/docs_wiki_lint.py`, inside the
orions-belt repo) to `.harness/lib/docs_wiki_lint.py` in the target project,
in the SAME directory where `_tooling_conf.py`/`scan_project.py`/`ds-gate.sh`
are already materialized via Copier (pattern established in F0/F5, not a new
convention). Layout difference vs. the source copy in `engine/lint/`: there
the script lives one level BELOW `_tooling_conf.py` (`engine/lint/` vs
`engine/`), here the two live SIDE BY SIDE in `.harness/lib/` — hence the
`sys.path.insert` below uses `Path(__file__).resolve().parent` (not
`.parents[1]`), same as `ds-pairs-check.py`/`ds-pair-eval.py` in the same
directory. Before this materialization, `docs/SCHEMA.md.jinja`,
`AGENTS.md.jinja` and the `repo-wiki-curator` skill told users to run
`engine/lint/docs_wiki_lint.py` or `scripts/docs-wiki-lint.py` — neither
exists in the target project (`engine/` is internal to the donor framework;
`scripts/docs-wiki-lint.py` was the script name in the reference donor
harness, never ported) — a command broken on first use. This materialization
+ updating all the prose to `.harness/lib/docs_wiki_lint.py` closes that
phantom path.

Rules (target project's docs/SCHEMA.md):
- FAIL: every non-structural .md must be cited individually or covered by a collection
  explicitly indexed in some index.md/log.md/README.md under docs/.
- FAIL: a non-markdown file (json/png/pdf/...) must be cited by name or covered by a collection
  explicitly indexed (generic containers sources/assets/img/reports do not count).
- WARN: Markdown naming off the §2 pattern (kebab-case; event=YYYY-MM-DD-slug; sequenced=NNNN-slug).
  Does not block by default — name migration is incremental via the loop. Use --strict-naming to make it FAIL.

Usage:
  python3 .harness/lib/docs_wiki_lint.py                 # entire target repo (docs/)
  python3 .harness/lib/docs_wiki_lint.py --scope <category>     # only one category (used by gates)
  python3 .harness/lib/docs_wiki_lint.py --strict-naming # naming also blocks
  python3 .harness/lib/docs_wiki_lint.py --worktree      # local diff vs HEAD
  python3 .harness/lib/docs_wiki_lint.py --staged        # staged/pre-commit diff
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
# lowercase kebab, with an optional date prefix (event) or number (sequenced); dot only for versions like v2.2
NAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}-|\d+-)?[a-z0-9]+([a-z0-9.\-]*[a-z0-9])?\.[a-z0-9]+$")
# date (YYYY-MM-DD) present but NOT as a prefix → event doc with date in suffix (§2: must be a prefix)
DATE_ANY = re.compile(r"\d{4}-\d{2}-\d{2}")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LOG_HEADING_RE = re.compile(r"^## \[(\d{4}-\d{2}-\d{2}|sem-data)\] [^·]+ · .+")
STRAY_TOOL_RE = re.compile(r"^\s*</(content|invoke|antml:invoke|antml:parameter)>\s*$")


def collect_index_corpus(scope_dir: Path) -> str:
    """Concatenates indexes under docs/ (the top always counts), to check mentions."""
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
    """Accepts coverage by an explicit collection, without letting a generic top-level cover everything."""
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
    """Live index (`index.md`) that links to `_arquivo/`.

    In some repos this could be FAIL; in this template it stays WARN because indexes may use links to
    `_arquivo/` as labeled wayfinding ("historical", "superseded", "proof in"). WARN surfaces it to
    the human eye during curation without breaking green. `log.md` is exempt as a temporal record."""
    errs: list[str] = []
    for idx in sorted(base.rglob("index.md")):
        if any(part in IGNORED_DIRS for part in idx.relative_to(DOCS).parts):
            continue
        rel = idx.relative_to(DOCS)
        for m in re.finditer(r"\]\(([^)]+)\)", idx.read_text(encoding="utf-8")):
            tgt = m.group(1).split("#")[0].strip().lstrip("./")
            if any(tok in tgt for tok in FOREIGN_LIVE_FORBIDDEN):
                errs.append(f"live index links an archived source: {rel} -> {m.group(1)}")
    return errs


def check_log_format(base: Path) -> list[str]:
    errs: list[str] = []
    for log in sorted(base.rglob("log.md")):
        if any(part in IGNORED_DIRS for part in log.relative_to(DOCS).parts):
            continue
        previous: str | None = None
        headings = [line for line in log.read_text(encoding="utf-8").splitlines() if line.startswith("## ")]
        if not headings:
            errs.append(f"{log.relative_to(DOCS)}: no ## [YYYY-MM-DD] entries")
        for line in headings:
            if not LOG_HEADING_RE.match(line):
                errs.append(f"{log.relative_to(DOCS)}: heading off the temporal format: {line}")
                continue
            date = line.split("]", 1)[0].removeprefix("## [")
            if date != "sem-data":
                if previous and previous != "sem-data" and date > previous:
                    errs.append(f"{log.relative_to(DOCS)}: log out of descending temporal order: {line}")
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
            errs.append(f"{path.relative_to(DOCS)}: frontmatter not closed")
            continue
        frontmatter = text[4:end]
        updated = re.search(r"^updated:\s*[\"']?([^\"'\n]+)[\"']?\s*$", frontmatter, flags=re.M)
        if updated and not DATE_RE.match(updated.group(1)):
            errs.append(f"{path.relative_to(DOCS)}: updated off YYYY-MM-DD: {updated.group(1)!r}")
    return errs


def check_stray_tool_tags(base: Path) -> list[str]:
    errs: list[str] = []
    for path in sorted(base.rglob("*.md")):
        if any(part in IGNORED_DIRS for part in path.relative_to(DOCS).parts):
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if STRAY_TOOL_RE.match(line):
                errs.append(f"{path.relative_to(DOCS)}:{i}: stray tool tag -> {line.strip()!r}")
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
        failures.append(f"git diff failed: {proc.stderr.strip() or proc.stdout.strip()}")
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
                failures.append(f"{new_path}: new/removed/renamed markdown requires updating docs/log.md in the same diff")
            if status.startswith(("A", "R")) and not index_changed:
                failures.append(f"{new_path}: new/renamed markdown requires updating the category index/README in the same diff")


def naming_ok(rel: Path) -> bool:
    name = rel.name
    if name in CAPS_OK or name in {"index.md", "log.md"}:
        return True
    if not NAME_RE.match(name):
        return False
    # §2: a dated event doc must have the date as a PREFIX (sorts in ls). Date in suffix is a violation.
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
        # coverage: individual mention or explicitly indexed collection.
        covered = mentioned(rel, corpus) or collection_mentioned(rel, corpus)
        if not covered:
            failures.append(f"orphan (no mention in index/log): {rel}")
        # naming (§2)
        if f.suffix == ".md" and not naming_ok(rel):
            naming_warns.append(f"naming off the §2 pattern: {rel}")

    foreign_warns = check_no_foreign_live_links(base)
    failures.extend(check_log_format(base))
    failures.extend(check_frontmatter_updated(base))
    failures.extend(check_stray_tool_tags(base))
    check_diff_policy(args.diff_base, args.staged, args.worktree, failures)

    if strict_naming:
        failures.extend(naming_warns)
        naming_warns = []

    if naming_warns:
        print(f"docs-wiki-lint: {len(naming_warns)} naming warning(s) (WARN, incremental migration):")
        for w in naming_warns[:60]:
            print(f"  ~ {w}")
        if len(naming_warns) > 60:
            print(f"  ... +{len(naming_warns) - 60} others")

    if foreign_warns:
        print(f"docs-wiki-lint: {len(foreign_warns)} live index(es) linking _arquivo/ (WARN — check whether it is labeled wayfinding):")
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
