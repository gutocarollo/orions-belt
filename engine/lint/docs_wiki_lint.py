#!/usr/bin/env python3
"""Lint for the whole TARGET REPOSITORY's Karpathy wiki (docs/), not just one specialized category.

Port of the STRONG version of `guto-wiki`
(padronizacao-documentacao/artefatos/scripts/docs-wiki-lint.py, 312 lines —
see docs/planning/research/01-guto-wiki.md §b) into the agent-harness
`engine/`. Two structural changes relative to the source, no change to any
RULE:

1. The local `load_config()`/`config_csv()` were REMOVED — this script
   imports `get_config`/`get_config_csv`/`project_root` from
   `engine/_tooling_conf.py` (the framework's SINGLE parser, see its
   docstring). guto-wiki implemented the same parser 3x without extracting
   it (docs/planning/research/01-guto-wiki.md §b, "Structural observations"
   item 1) — this port does not repeat the mistake.
2. `ROOT` is no longer `Path(__file__).resolve().parents[1]` (which in
   guto-wiki assumed the script lived in `<repo>/scripts/`, i.e.
   `parents[1]` = root of the repo being linted). In this layout the
   script lives in `engine/lint/`, fixed inside the agent-harness —
   `parents[1]` would point at `engine/`, which is WRONG when the engine is
   installed into an arbitrary target project. `ROOT` now comes from
   `_tooling_conf.project_root()` (HARNESS_PROJECT_ROOT ->
   CLAUDE_PROJECT_DIR -> `git rev-parse --show-toplevel` -> cwd).

Rules (docs/SCHEMA.md of the target project):
- FAIL: every non-structural .md must be cited individually or covered by a collection
  explicitly indexed in some index.md/log.md/README.md under docs/.
- FAIL: a non-markdown file (json/png/pdf/...) must be cited by name or covered by a collection
  explicitly indexed (generic containers sources/assets/img/reports do not count).
- WARN: Markdown naming outside the §2 standard (kebab-case; event=YYYY-MM-DD-slug; sequenced=NNNN-slug).
  Does not block by default — name migration is incremental via the loop. Use --strict-naming to make it FAIL.

Usage:
  python3 engine/lint/docs_wiki_lint.py                 # whole target repo (docs/)
  python3 engine/lint/docs_wiki_lint.py --scope <category>     # only one category (used by gates)
  python3 engine/lint/docs_wiki_lint.py --strict-naming # naming also blocks
  python3 engine/lint/docs_wiki_lint.py --worktree      # local diff vs HEAD
  python3 engine/lint/docs_wiki_lint.py --staged        # staged/pre-commit diff
  python3 engine/lint/docs_wiki_lint.py --diff-base <ref>  # CI/PR/push
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # engine/
from _tooling_conf import get_config, get_config_csv, project_root  # noqa: E402

ROOT = project_root()
DOCS = ROOT / get_config("HARNESS_DOCS_DIR", "docs")

STRUCTURAL = {"index.md", "log.md", "SCHEMA.md", "README.md"}
CAPS_OK = {"README.md", "SCHEMA.md", "CLAUDE.md", "AGENTS.md", "LICENSE", "LICENSE.md", "PROVENANCE.md"}
GENERIC_DIRS = {"sources", "assets", "img", "images", "reports", "docs", "_arquivo"}
IGNORED_DIRS = set(get_config_csv("IGNORED_TOOL_DIRS", [".understand-anything", ".anythingllm"]))
# Repo-wide stray sweep (WARN backlog): markdown allowed at the repo ROOT without
# being a stray — the conventional structural/community files.
ROOT_ALLOWED_MD = CAPS_OK | {"CONTRIBUTING.md", "CHANGELOG.md", "CODE_OF_CONDUCT.md", "SECURITY.md", "NOTICE.md"}
# Directory names never swept for strays: dependency/build output and test fixtures.
STRAY_SKIP_DIRS = {"node_modules", "vendor", "dist", "build", "out", "target", "__pycache__", "fixtures"}
# lowercase kebab, with an optional date (event) or number (sequenced) prefix; dot only for a version like v2.2
NAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}-|\d+-)?[a-z0-9]+([a-z0-9.\-]*[a-z0-9])?\.[a-z0-9]+$")
# date (YYYY-MM-DD) present but NOT as a prefix → event doc with date as a suffix (§2: must be a prefix)
DATE_ANY = re.compile(r"\d{4}-\d{2}-\d{2}")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LOG_HEADING_RE = re.compile(r"^## \[(\d{4}-\d{2}-\d{2}|sem-data)\] [^·]+ · .+")
STRAY_TOOL_RE = re.compile(r"^\s*</(content|invoke|antml:invoke|antml:parameter)>\s*$")


def collect_index_corpus(scope_dir: Path) -> str:
    """Concatenate indexes under docs/ (the top always counts), to check for a mention."""
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
    """Accept coverage by an explicit collection, without letting a generic top-level cover everything.

    DEPTH-1 COLLECTIONS COUNT (adopter report, 2026-07-30). The loop used to stop at ``i > 1``,
    which made a file sitting directly inside a first-level directory under ``docs/`` impossible to
    cover by collection: for ``docs/spec/01.md`` the ancestor tuple is ``('spec',)``, so
    ``range(1, 1, -1)`` was empty and only an individual mention could clear it. Measured effect in
    a real adopter: 36 files (14 eval CSVs, a PDF, a .sql, a .yaml, 8 research reports, 3 reviews)
    stayed orphan even though each directory had a README explaining the collection, and the
    adopter shipped two commits with ``--no-verify`` because of it. Routine bypass is how a gate
    dies.

    The guard against "one generic top-level covers the whole tree" is ``GENERIC_DIRS``, not an
    off-by-one in the range — that is why ``docs``/``assets``/``img``/``reports`` are listed there.
    At depth 1, however, ``ancestor == leaf`` and a bare substring test would be far too loose (a
    collection named ``spec`` would be "covered" by the word *specification* anywhere in an index),
    so depth 1 accepts ONLY the unambiguous forms: ``leaf/`` with the slash, or `` `leaf` `` in backticks in
    backticks. Deeper ancestors keep the original, more permissive matching.
    """
    parts = rel.parts[:-1]
    for i in range(len(parts), 0, -1):
        leaf = parts[i - 1]
        if leaf in GENERIC_DIRS:
            continue
        ancestor = "/".join(parts[:i])
        if i == 1:
            # top-level collection: require the slash or backtick form, never a bare substring
            if f"{leaf}/" in corpus or f"`{leaf}`" in corpus:
                return True
            continue
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

    In some repos this could be FAIL; in this template it is WARN because indexes may use links to
    `_arquivo/` as labeled wayfinding ("historical", "superseded", "evidence in"). WARN surfaces it
    to the human eye during curation without breaking the green. `log.md` is exempt as a temporal record."""
    errs: list[str] = []
    for idx in sorted(base.rglob("index.md")):
        if any(part in IGNORED_DIRS for part in idx.relative_to(DOCS).parts):
            continue
        rel = idx.relative_to(DOCS)
        for m in re.finditer(r"\]\(([^)]+)\)", idx.read_text(encoding="utf-8")):
            tgt = m.group(1).split("#")[0].strip().lstrip("./")
            if any(tok in tgt for tok in FOREIGN_LIVE_FORBIDDEN):
                errs.append(f"live index links to an archived source: {rel} -> {m.group(1)}")
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
                errs.append(f"{log.relative_to(DOCS)}: heading outside the temporal format: {line}")
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
            errs.append(f"{path.relative_to(DOCS)}: updated outside YYYY-MM-DD: {updated.group(1)!r}")
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


def _stray_covered(rel: Path, corpus: str) -> bool:
    """A doc living outside docs/ is NOT a stray when the wiki indexes it anyway:
    exact path cited, or an ancestor dir cited as an explicit collection ("dir/").
    Bare-filename mentions do NOT count (any cited notes.md would silence them all)."""
    if rel.as_posix() in corpus:
        return True
    parts = rel.parts[:-1]
    for i in range(len(parts), 0, -1):
        if parts[i - 1] in GENERIC_DIRS:
            continue
        if "/".join(parts[:i]) + "/" in corpus:
            return True
    return False


def check_stray_docs(corpus: str) -> list[str]:
    """Repo-wide sweep (WARN backlog): markdown scattered OUTSIDE the docs tree —
    repo root, src/, backend/, anywhere — is invisible to the wiki (never indexed,
    never curated), which is how PLANO-FINAL-v2.md graveyards form. Each stray is
    inbox for the repo-wiki-curator: classify (plan? audit? architecture?
    reference?) and `git mv` into its docs/<category>/ box (or _arquivo/) — or
    index it in place (exact path / collection "dir/" in index.md|log.md) when it
    legitimately lives outside. WARN-only: a brownfield adoption may surface
    dozens; they are incremental backlog for the maintenance loop, not an
    install-day failure."""
    lessons_rel = get_config("HARNESS_LESSONS_FILE", "tasks/lessons.md")
    warns: list[str] = []
    for f in sorted(ROOT.rglob("*.md")):
        rel = f.relative_to(ROOT)
        parts = rel.parts
        if rel.as_posix() == lessons_rel:  # canonical shared-memory file, not a stray
            continue
        if rel.name == "README.md":  # conventional locality doc, any directory
            continue
        if any(p.startswith(".") for p in parts):  # .git, .claude, .harness, ...
            continue
        if any(p in STRAY_SKIP_DIRS or p in IGNORED_DIRS for p in parts):
            continue
        try:
            rel.relative_to(DOCS.relative_to(ROOT))  # already inside the wiki
            continue
        except ValueError:
            pass
        if len(parts) == 1 and rel.name in ROOT_ALLOWED_MD:
            continue
        if _stray_covered(rel, corpus):
            continue
        warns.append(f"stray doc outside {DOCS.name}/ (classify into a category or _arquivo/): {rel}")
    return warns


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


# The wiki's own indexing layer: these files ARE the index, so a fresh render's
# bootstrap commit (which stages exactly the seeds log.md + SCHEMA.md) must not
# demand a second index update that cannot exist yet.
WIKI_INFRA_BASENAMES = {"log.md", "SCHEMA.md", "index.md", "README.md"}


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
            if status.startswith(("A", "R")) and not index_changed and Path(new_path).name not in WIKI_INFRA_BASENAMES:
                failures.append(f"{new_path}: new/renamed markdown requires updating the category's index/README in the same diff")


def naming_ok(rel: Path) -> bool:
    name = rel.name
    if name in CAPS_OK or name in {"index.md", "log.md"}:
        return True
    if not NAME_RE.match(name):
        return False
    # §2: a dated event doc must have the date as a PREFIX (sorts in ls). A date as a suffix is a violation.
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
            naming_warns.append(f"naming outside the §2 standard: {rel}")

    foreign_warns = check_no_foreign_live_links(base)
    stray_warns = check_stray_docs(corpus) if not scope else []
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
            print(f"  ... +{len(naming_warns) - 60} more")

    if foreign_warns:
        print(f"docs-wiki-lint: {len(foreign_warns)} live index(es) linking to _arquivo/ (WARN — check whether it is labeled wayfinding):")
        for w in foreign_warns:
            print(f"  ~ {w}")

    if stray_warns:
        print(f"docs-wiki-lint: {len(stray_warns)} stray doc(s) outside the wiki (WARN, curator inbox — classify into docs/<category>/):")
        for w in stray_warns[:40]:
            print(f"  ~ {w}")
        if len(stray_warns) > 40:
            print(f"  ... +{len(stray_warns) - 40} others")

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
