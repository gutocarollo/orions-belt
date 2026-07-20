#!/usr/bin/env python3
"""ref_integrity.py — git-aware referential integrity (renames/deletes).

Port of `guto-wiki` (padronizacao-documentacao/artefatos/scripts/
ref-integrity.py — see docs/planning/research/01-guto-wiki.md §b) into
orions-belt's `engine/`. Same structural swap as the sibling
`docs_wiki_lint.py`: local `load_config()`/`config_csv()` REMOVED, replaced
by the import from `_tooling_conf.py` (single parser — does not repeat the
DRY triplication guto-wiki itself never fixed). `ROOT` now comes from
`_tooling_conf.project_root()` instead of an inline
`git rev-parse --show-toplevel` (the SAME call existed here — now centralized
in the shared module, along with the HARNESS_PROJECT_ROOT/CLAUDE_PROJECT_DIR
fallback that `docs_wiki_lint.py` also uses).

MATERIALIZATION (R2, orions-belt — rescue plan §2 item "Lint distribution"):
copy of this file (authored in `engine/lint/ref_integrity.py`, inside the
orions-belt repo) to `.harness/lib/ref_integrity.py` in the target project,
in the SAME directory where `_tooling_conf.py`/`scan_project.py`/`ds-gate.sh`
are already materialized via Copier (F0/F5 pattern). Layout difference vs.
the source copy in `engine/lint/`: here the script lives SIDE BY SIDE with
`_tooling_conf.py` in `.harness/lib/`, hence the `sys.path.insert` below uses
`Path(__file__).resolve().parent` (not `.parents[1]`), same as
`ds-pairs-check.py`/`ds-pair-eval.py` in the same directory. Before this
materialization, the `ref-integrity` skill, the `repo-wiki-curator` skill and
`docs/SCHEMA.md.jinja` told users to run `scripts/ref-integrity.py` or
`engine/lint/ref_integrity.py` — neither exists in the target project — a
command broken on first use. This materialization + updating all the prose to
`.harness/lib/ref_integrity.py` closes that phantom path.

SINGLE SOURCE (SOLID/DRY) consumed by 3 thin adapters:
  - pre-commit git hook  → --staged   (resolve/grep in the INDEX; blocks the commit)
  - invocable skill      → --range A..B
  - scheduled loop       → --since <ref>

Two deterministic checks:
  (A) broken-md-links   — markdown links `](path)` that do not resolve.
  (B) stale-citations   — live citations to the OLD PATH/name of files renamed/deleted
                          in the selector's git diff. Reconciles false-positive vs false-negative:
                          basename that VANISHED from the repo → search by basename (catches a citation with no path);
                          basename that STILL exists (renamed) → search only by the old full PATH
                          (does not flag `multi-tenancy.md` which resolves to the new location).

The "where-to-search" axis governs BOTH checks: --staged uses the INDEX (git show :path /
git cat-file -e :path / git grep --cached); --range/--since use the working tree at HEAD.

Two levels of exemption:
  - is_archive (check A and B): docs/_arquivo/, .understand-anything/ (+.trash) — pure archaeology.
  - is_historical (check B only / stale-citation): + docs/adr/, docs/auditorias/, docs/qa-evidence/, **/log.md
    — a prose CITATION to an old name is a legitimate snapshot, but a broken clickable markdown LINK there is NOT
    exempt (check A enforces: the index must not have a dead link).
Known exceptions (generator auto-output, manual backup): `.ref-integrity-allowlist`.

Exit 1 if there is a real broken reference; 0 otherwise. `--json` for machine output.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # .harness/lib/
from _tooling_conf import get_config_csv, project_root  # noqa: E402

ALLOW_EXT = {".md", ".json", ".txt", ".py", ".sh", ".toml", ".mjs", ".ts",
             ".tsx", ".css", ".yaml", ".yml", ".snyk"}
GENERIC_BASENAMES = {"index.md", "log.md", "readme.md", "schema.md", "__init__.py",
                     "config.json", "package.json", "utils.py", "types.ts"}
LINK_RE = re.compile(r"\]\(\s*([^)\s]+)")


def _fence_flags(text: str) -> list[bool]:
    """1:1 with `text.splitlines()`: True if the line is inside (or is the marker of) a code fence.
    Single source of the fence logic — does not go through join/splitlines (avoids losing the final blank line)."""
    flags: list[bool] = []
    in_fence = False
    for line in text.splitlines():
        s = line.lstrip()
        if s.startswith("```") or s.startswith("~~~"):
            in_fence = not in_fence
            flags.append(True)  # the fence marker itself is also blanked
        else:
            flags.append(in_fence)
    return flags


def blank_code_fences(text: str) -> str:
    """Blanks the content of ``` / ~~~ blocks (1:1 per line). A link/citation INSIDE a fence is a code
    EXAMPLE, not a navigable reference — must not flag."""
    lines = text.splitlines()
    return "\n".join("" if fl else ln for ln, fl in zip(lines, _fence_flags(text)))


ROOT = str(project_root())


def sh(args: list[str]) -> str:
    # cwd=ROOT is a correction introduced by this port, not a cosmetic
    # detail: in the source (guto-wiki), `ROOT = sh(["git","rev-parse",
    # "--show-toplevel"]).strip()` was DERIVED from the process's ambient cwd
    # — ROOT and "git repo of the cwd" could never diverge. Here `ROOT` comes
    # from `project_root()`, which can be OVERRIDDEN via HARNESS_PROJECT_ROOT/
    # CLAUDE_PROJECT_DIR to a path different from the process's real cwd.
    # Without `cwd=ROOT` on every git call, the git commands would operate on
    # the repo of the ambient cwd while the file paths would be resolved
    # against `ROOT` — a silent mismatch. Same correction applied in
    # `exists_in_index()` and `git_grep()` below (subprocess.run calls that do
    # not go through `sh()`).
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True).stdout

ARCHIVE_PREFIXES = set(get_config_csv("REF_INTEGRITY_ARCHIVE_PREFIXES", ["docs/_arquivo/"]))
ARCHIVE_CONTAINS = set(get_config_csv("IGNORED_TOOL_DIRS", [".understand-anything", ".anythingllm", ".trash-"]))


def load_allowlist() -> set[str]:
    """Terms to ignore globally (generator auto-output, backups). 1 per line; '#' = comment."""
    p = os.path.join(ROOT, ".ref-integrity-allowlist")
    terms: set[str] = set()
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.split("#", 1)[0].strip()
            if line:
                terms.add(line)
    return terms


def is_archive(path: str) -> bool:
    """Pure archaeology — not even a clickable link needs to resolve (dead/scratch docs)."""
    p = path.replace("\\", "/")
    return any(p.startswith(prefix) for prefix in ARCHIVE_PREFIXES) or any(token in p for token in ARCHIVE_CONTAINS)


def is_historical(path: str) -> bool:
    """Historical record/snapshot: a prose CITATION to an old name is legitimate (check B exempts it).
    But a broken clickable markdown LINK is NOT exempt here (check A uses is_archive, narrower)."""
    p = path.replace("\\", "/")
    if is_archive(p):
        return True
    # immutable ADR (Nygard), audits and qa-evidence = dated snapshots; log.md = append-only
    if p.startswith(("docs/adr/", "docs/auditorias/", "docs/qa-evidence/")):
        return True
    if os.path.basename(p) == "log.md":
        return True
    return False


def has_allowed_ext(path: str) -> bool:
    base = os.path.basename(path)
    if base.endswith(".snyk") or base == ".snyk":  # dotfile: splitext gives empty ext
        return True
    return os.path.splitext(path)[1] in ALLOW_EXT


def tracked_files() -> list[str]:
    return [x for x in sh(["git", "ls-files"]).splitlines() if x]


def exists_in_index(relpath: str) -> bool:
    if subprocess.run(["git", "cat-file", "-e", f":{relpath}"],
                      cwd=ROOT, capture_output=True).returncode == 0:
        return True
    # a directory is not a blob addressable via `:path`; it exists in the index if there is a tracked file under it
    # (otherwise a link to a dir — e.g. `sources/some-subdir/` — becomes a false-positive only in --staged mode).
    return bool(sh(["git", "ls-files", "--", f"{relpath}/"]).strip())


def path_exists(rel: str, cached: bool) -> bool:
    rel = os.path.normpath(rel)
    if not rel or rel.startswith(".."):
        return False
    return exists_in_index(rel) if cached else os.path.exists(os.path.join(ROOT, rel))


PATH_TOKEN = r"[\w./-]*"


def rd_pairs(diff_args: list[str]) -> list[tuple[str, str | None]]:
    out = sh(["git", "diff", "--name-status", "--diff-filter=RD", *diff_args])
    pairs: list[tuple[str, str | None]] = []
    for line in out.splitlines():
        parts = line.split("\t")
        if not parts or not parts[0]:
            continue
        st = parts[0]
        if st.startswith("R") and len(parts) >= 3:
            pairs.append((parts[1], parts[2]))
        elif st == "D" and len(parts) >= 2:
            pairs.append((parts[1], None))
    return pairs


def git_grep(term: str, cached: bool) -> list[tuple[str, int, str]]:
    # term is the PATTERN (-e); searches the index (--cached) or the tracked working tree.
    cmd = ["git", "grep", "-n", "-F"] + (["--cached"] if cached else []) + ["-e", term]
    res = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    hits: list[tuple[str, int, str]] = []
    for line in res.stdout.splitlines():
        m = re.match(r"^(.+?):(\d+):(.*)$", line)
        if m:
            hits.append((m.group(1), int(m.group(2)), m.group(3)))
    return hits


_blank_cache: dict = {}


def _in_fence(f: str, ln: int, cached: bool) -> bool:
    """True if line `ln` of `f` is inside a code fence (only applies to .md). Uses 1:1 flags
    (not the round-tripped blanked text) — the last line of the file is indexed correctly."""
    key = (f, cached)
    if key not in _blank_cache:
        try:
            text = sh(["git", "show", f":{f}"]) if cached else open(os.path.join(ROOT, f), encoding="utf-8").read()
        except OSError:
            text = ""
        _blank_cache[key] = _fence_flags(text)
    fl = _blank_cache[key]
    return 1 <= ln <= len(fl) and fl[ln - 1]


def check_stale_citations(diff_args, cached, tracked_bases, allow) -> list[dict]:
    findings: list[dict] = []
    seen = set()
    for old, new in rd_pairs(diff_args):
        base = os.path.basename(old)
        by_basename = not (base.lower() in GENERIC_BASENAMES or base in tracked_bases)
        term = base if by_basename else old
        if term in allow or base in allow:
            continue
        for f, ln, content in git_grep(term, cached):
            if not has_allowed_ext(f) or is_historical(f) or f == new:
                continue
            if f.endswith(".md") and _in_fence(f, ln, cached):
                continue
            # isolated token (not a suffix/prefix of a longer name, e.g. e01-leaderboard.png)
            m2 = re.search(r"(?<![\w-])(" + PATH_TOKEN + re.escape(term) + PATH_TOKEN + r")(?![\w-])", content)
            if not m2:
                continue
            # if the path around the match RESOLVES (was fixed to the new location, or is another file
            # that only contains the name as a substring), it is not stale.
            tok = m2.group(1).lstrip("./")
            cands = [os.path.join(os.path.dirname(f), tok), tok]
            if any(path_exists(c, cached) for c in cands):
                continue
            key = (f, ln, term)
            if key in seen:
                continue
            seen.add(key)
            findings.append({"check": "stale-citation", "old": old, "new": new,
                             "term": term, "file": f, "line": ln,
                             "snippet": content.strip()[:120]})
    return findings


def _md_targets(text: str):
    for i, line in enumerate(text.splitlines(), 1):
        for m in LINK_RE.finditer(line):
            tgt = m.group(1).split("#")[0].strip()
            if tgt and not tgt.startswith(("http://", "https://", "mailto:", "#", "<", "tel:")):
                yield i, tgt, line


def _resolve_link(f: str, tgt: str, staged: bool) -> bool:
    tgt = urllib.parse.unquote(tgt)  # link with space/accent (%20) resolves to the real name on disk
    # tries dir-relative AND repo-relative (docs cite repo-relative paths without a leading '/')
    if tgt.startswith("/"):
        cands = [tgt.lstrip("/")]
    else:
        cands = [os.path.normpath(os.path.join(os.path.dirname(f), tgt)), os.path.normpath(tgt)]
    cands = [c for c in cands if c and not c.startswith("..")]
    return any((exists_in_index(c) if staged else os.path.exists(os.path.join(ROOT, c))) for c in cands)


def _scan_md_text(f: str, text: str, staged: bool, allow: set[str]) -> list[dict]:
    findings: list[dict] = []
    for ln, tgt, line in _md_targets(blank_code_fences(text)):  # a link in a fence is an example, not navigable
        if tgt in allow:
            continue
        if tgt.startswith("{"):
            # Runtime placeholder (`{baseDir}/...`, `{skillDir}/...`) — Claude Skills authoring
            # convention where the skill loader resolves the token at load time, not a literal repo
            # path. Real finding while porting 4 third-party skills (agentic-actions-auditor, fp-check,
            # sarif-parsing, semgrep-rule-creator) into templates/: 42 of the 46 initial findings were
            # this pattern. Pattern-based (not per-item allowlist) because the convention repeats in
            # any new skill that adopts `{baseDir}` — 1 rule covers all, not one line per link.
            continue
        if not _resolve_link(f, tgt, staged):
            findings.append({"check": "broken-md-link", "file": f, "line": ln,
                             "target": tgt, "snippet": line.strip()[:120]})
    return findings


def check_md_links(staged: bool, allow: set[str]) -> list[dict]:
    findings: list[dict] = []
    if staged:
        files = [f for f in sh(["git", "diff", "--cached", "--name-only",
                                "--diff-filter=ACM"]).splitlines() if f.endswith(".md")]
    else:
        files = [f for f in tracked_files() if f.endswith(".md")]
    for f in files:
        if is_archive(f):  # a broken clickable link is noise even in log/audit/adr; only _arquivo is exempt
            continue
        try:
            text = sh(["git", "show", f":{f}"]) if staged else open(os.path.join(ROOT, f), encoding="utf-8").read()
        except OSError:
            continue
        findings += _scan_md_text(f, text, staged, allow)
    return findings


def selftest() -> int:
    """Institutionalized negative test (lesson: a guard only counts after you SEE the FAIL). Creates 2
    temporary .md in docs/: one with a real dead link (MUST flag) and one with the same dead link ONLY
    inside a code fence (must NOT flag — validates blank_code_fences). Restores the state at the end."""
    d = os.path.join(ROOT, "docs")
    os.makedirs(d, exist_ok=True)
    dead = os.path.join(d, ".selftest-ref-dead.md")
    fenced = os.path.join(d, ".selftest-ref-fence.md")
    open(dead, "w", encoding="utf-8").write("[x](./nao-existe-zzz-selftest.md)\n")
    open(fenced, "w", encoding="utf-8").write("```\n[x](./nao-existe-zzz-selftest.md)\n```\n")
    ok = True
    try:
        rel_dead, rel_fenced = os.path.relpath(dead, ROOT), os.path.relpath(fenced, ROOT)
        if not _scan_md_text(rel_dead, open(dead, encoding="utf-8").read(), False, set()):
            print("SELFTEST FAIL: dead link not detected"); ok = False
        else:
            print("selftest: dead link detected — OK")
        if _scan_md_text(rel_fenced, open(fenced, encoding="utf-8").read(), False, set()):
            print("SELFTEST FAIL: link in code fence flagged (blank_code_fences broken)"); ok = False
        else:
            print("selftest: link in code fence ignored — OK")
    finally:
        os.remove(dead)
        os.remove(fenced)
    print("ref-integrity --selftest: PASS" if ok else "ref-integrity --selftest: FAIL")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Git-aware referential integrity (renames/deletes).")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--staged", action="store_true", help="pre-commit: staged + index")
    g.add_argument("--range", metavar="A..B", help="skill: commit range")
    g.add_argument("--since", metavar="REF", help="loop: REF..HEAD")
    g.add_argument("--selftest", action="store_true", help="negative test of the detector itself")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        return selftest()

    allow = load_allowlist()
    tracked_bases = {os.path.basename(p) for p in tracked_files()}
    findings: list[dict] = []

    if a.staged:
        findings += check_stale_citations(["--cached"], True, tracked_bases, allow)
        findings += check_md_links(staged=True, allow=allow)
    else:
        rng = a.range if a.range else f"{a.since}..HEAD"
        findings += check_stale_citations([rng], False, tracked_bases, allow)
        findings += check_md_links(staged=False, allow=allow)

    # global dedup (A and B may report the same link for a deleted file)
    uniq, keys = [], set()
    for x in findings:
        k = (x["file"], x["line"], x.get("target") or x.get("term"))
        if k not in keys:
            keys.add(k)
            uniq.append(x)
    findings = uniq

    if a.json:
        print(json.dumps(findings, indent=2, ensure_ascii=False))
    elif not findings:
        print("ref-integrity: OK — no broken references")
    else:
        print(f"ref-integrity: FAIL — {len(findings)} broken reference(s):")
        for x in findings:
            if x["check"] == "broken-md-link":
                print(f"  [link]  {x['file']}:{x['line']} → {x['target']} (does not resolve)")
            else:
                print(f"  [stale] {x['file']}:{x['line']} → cites '{x['term']}' (removed; new: {x['new'] or '—'})")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
