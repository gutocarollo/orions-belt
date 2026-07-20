#!/usr/bin/env python3
"""_tooling_conf — the SINGLE module for loading the harness central config.

MATERIALIZATION (F3, orions-belt): byte-identical copy of `engine/_tooling_conf.py`
(the authoring source, used by the `engine/lint/`/`engine/contract/` scripts INSIDE
the orions-belt repo). Claude/Codex hooks run as a local shell command in the
installed target project — there is no way to reference a path outside the repo
portably across machines — so this module (with no project-specific content, a
pure parser) is copied into `.harness/lib/` in the target project via Copier, and
the hooks materialized in `.claude/hooks/`/`.codex/hooks/` import it via a
`sys.path.insert` relative to the project root (`$ROOT/.harness/lib/_tooling_conf.py`),
not relative to themselves — see `hooks/subagent-throttle.sh` in the same top-level
`.claude/` directory.

Why this module exists (the mistake it fixes): `guto-wiki`
(docs/planning/research/01-guto-wiki.md §b, "Structural observations" item 1)
implemented the SAME `load_config()`/`config_csv()` (`KEY=value` format,
`#` comment, inline CSV) three times, byte-for-byte identical, in
`docs-wiki-lint.py`, `ref-integrity.py` and `scope-wiki-lint.py` — with no
shared abstraction between them. This is the DRY they never did themselves.
Every `engine/` script (hooks, lint, contract) imports `get_config()`/
`get_config_csv()`/`get_config_int()`/`get_config_bool()` from here instead of
reimplementing the parser.

Format of `.harness/harness.conf` (docs/planning/research/03-hardcodes.md §3):

    KEY=value
    # whole-line or trailing comment (preceded by a space)
    CSV_KEY=item1,item2,item3          # get_config_csv() does the split
    DERIVED_KEY=${OTHER_KEY}-suffix    # sequential top-to-bottom expansion
    LITERAL='${OTHER_KEY}'             # single quotes suppress expansion

Zero external dependencies (pure stdlib) — same design decision as guto-wiki
(docs/planning/research/01-guto-wiki.md §"Structural observations" item 2):
`configparser` would require `[x]` sections which the format does not use;
`tomllib` is stdlib only from 3.11 onward. The small parser below supports
quoted values and treats `#` as a comment delimiter only at the start of a
value or after whitespace. This keeps ordinary values such as `C# Academy`
and `p@ss#word` intact without adding a dependency.

Bash consumers (most real harness hooks are `.sh`, not `.py` — see
`engine/hooks/subagent-throttle.sh`) do not import this module directly; they
call the CLI mode (`python3 _tooling_conf.py get KEY default`). This avoids the
obvious-but-wrong alternative of reimplementing the parser in pure bash
(`source`-ing the `.conf` directly would execute shell substitutions and would
silently diverge from the quote-aware parser and multi-name file fallback) — exactly the kind of
DRY-violating duplication this module exists to avoid.

Fail-open (docs/planning/research/07-autoconfig-patterns.md §Synthesis-3):
missing, unreadable or malformed file -> the getters return the caller's
`default`. Never raises an exception, never brings down the hook that invokes it.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

# Candidate names within the root directory found, in precedence order (the
# first that exists wins). Combines two conventions:
# 1. the official pair inside `.harness/` (this framework's convention: see
#    templates/.harness/harness.conf.jinja);
# 2. loose names at the project root, for compat with whoever copied only the
#    `.conf` without the directory, or migrated from docs-tooling.conf/wiki-tooling.conf
#    (guto-wiki's 3-name fallback pattern, adapted).
_CANDIDATE_RELATIVE_PATHS: tuple[str, ...] = (
    ".harness/harness.conf",
    ".harness/.harness.conf",
    "harness.conf",
    ".harness.conf",
)

# Test/CI override: points directly at a .conf file, skipping all root
# resolution (used by the fixtures in engine/hooks/tests/).
_ENV_CONF_PATH = "HARNESS_CONF_PATH"
# Root hints, in precedence order when `start` is not passed explicitly.
# HARNESS_PROJECT_ROOT is this framework's canonical hint; CLAUDE_PROJECT_DIR
# is recognized because Claude Code hooks already export it (same pattern used
# in the original subagent-throttle.sh:
# `ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"`).
_ENV_ROOT_HINTS: tuple[str, ...] = ("HARNESS_PROJECT_ROOT", "CLAUDE_PROJECT_DIR")

_VAR_REF_RE = re.compile(r"\$\{(\w+)\}")
_LITERAL_DOLLAR = "\x00HARNESS_LITERAL_DOLLAR\x00"

_MAX_CLIMB = 64  # safety ceiling — never climbs more than this


def _find_root_with_candidate(start: Path) -> Path | None:
    """Climbs directories from `start` until it finds a directory that
    contains one of the `_CANDIDATE_RELATIVE_PATHS`, or until it crosses the
    root of a git repository (does not climb past it — avoids leaking into
    user directories outside the project), or until the filesystem root."""
    current = start.resolve()
    for _ in range(_MAX_CLIMB):
        for rel in _CANDIDATE_RELATIVE_PATHS:
            if (current / rel).is_file():
                return current
        if (current / ".git").exists():
            return None
        parent = current.parent
        if parent == current:
            return None
        current = parent
    return None


def project_root(start: Path | None = None) -> Path:
    """Resolves the target project root for consumers that need a base
    directory beyond the `.conf` itself (docs_wiki_lint.py, ref_integrity.py,
    validate_skills.py, agent_swarm_ledger.py — engine/lint/ and engine/contract/
    use this function instead of each reimplementing
    `git rev-parse --show-toplevel`, the same kind of DRY duplication this
    module already fixes for the `.conf` parser).

    Precedence order: explicit `start` -> HARNESS_PROJECT_ROOT ->
    CLAUDE_PROJECT_DIR -> `git rev-parse --show-toplevel` -> cwd. Fail-open:
    never raises an exception; if nothing resolves, returns the cwd."""
    if start is not None:
        return start.resolve()
    for env_name in _ENV_ROOT_HINTS:
        hint = os.environ.get(env_name)
        if hint:
            return Path(hint).resolve()
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0:
            out = proc.stdout.strip()
            if out:
                return Path(out).resolve()
    except (OSError, subprocess.SubprocessError):
        pass
    return Path.cwd().resolve()


def _resolve_conf_path(start: Path | None = None) -> Path | None:
    override = os.environ.get(_ENV_CONF_PATH)
    if override:
        p = Path(override)
        return p if p.is_file() else None

    if start is None:
        root_hint: str | None = None
        for env_name in _ENV_ROOT_HINTS:
            root_hint = os.environ.get(env_name)
            if root_hint:
                break
        start = Path(root_hint) if root_hint else Path.cwd()

    root = _find_root_with_candidate(start)
    if root is None:
        return None
    for rel in _CANDIDATE_RELATIVE_PATHS:
        candidate = root / rel
        if candidate.is_file():
            return candidate
    return None


def _expand_refs(value: str, values_so_far: dict[str, str]) -> str:
    """Expands `${OTHER_KEY}` using the keys already parsed up to this line
    (top-to-bottom) or environment variables — same sequential semantics as
    `source` in bash. An unresolved reference stays literal (fail-open: does
    not raise an error for an unknown key)."""

    def _sub(match: re.Match[str]) -> str:
        key = match.group(1)
        return values_so_far.get(key, os.environ.get(key, match.group(0)))

    return _VAR_REF_RE.sub(_sub, value).replace(_LITERAL_DOLLAR, "$")


def _parse_value(raw: str) -> tuple[str, bool]:
    """Parse one dotenv-like value without executing shell syntax.

    Quotes protect whitespace and ``#``. Outside quotes, ``#`` begins a
    trailing comment only when it is the first character or follows
    whitespace; embedded hashes therefore remain data. Backslash escapes the
    next character inside quotes. Matching outer quotes are removed;
    apostrophes and backslashes in unquoted data remain literal.
    """
    value = raw.strip()
    if not value:
        return "", True

    out: list[str] = []
    quote: str | None = None
    outer_quote = value[0] if value[0] in {"'", '"'} else None
    escaped = False
    for index, char in enumerate(value):
        if escaped:
            out.append(_LITERAL_DOLLAR if char == "$" else char)
            escaped = False
            continue
        if quote and char == "\\":
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = None
            else:
                out.append(char)
            continue
        if not out and index == 0 and char in {"'", '"'}:
            quote = char
            continue
        if char == "#" and (index == 0 or value[index - 1].isspace()):
            break
        out.append(char)
    if escaped:
        out.append("\\")
    return "".join(out).rstrip(), outer_quote != "'"


def load_config(start: Path | None = None) -> dict[str, str]:
    """Locates and parses the target project's `.harness/harness.conf` (see
    `_resolve_conf_path`). Fail-open: missing file or read error -> empty
    dict, never an exception."""
    values: dict[str, str] = {}
    path = _resolve_conf_path(start)
    if path is None:
        return values
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return values
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        parsed, allow_expansion = _parse_value(value)
        values[key] = _expand_refs(parsed, values) if allow_expansion else parsed
    return values


_CONF_CACHE: dict[str, str] | None = None


def _conf() -> dict[str, str]:
    global _CONF_CACHE
    if _CONF_CACHE is None:
        _CONF_CACHE = load_config()
    return _CONF_CACHE


def reset_cache_for_tests() -> None:
    """For tests only: forces a re-read of the `.conf` on the next call
    (the main process uses a process-level cache — hooks are short-lived,
    so this normally does not matter outside tests)."""
    global _CONF_CACHE
    _CONF_CACHE = None


def get_config(key: str, default: str | None = None) -> str | None:
    return _conf().get(key, default)


def get_config_csv(key: str, default: list[str] | None = None) -> list[str]:
    value = _conf().get(key)
    if not value:
        return list(default) if default else []
    return [item.strip() for item in value.split(",") if item.strip()]


def get_config_int(key: str, default: int) -> int:
    """Numeric caps (docs/planning/research/03-hardcodes.md §2.9) are always
    int in schema A. Fail-open: missing or non-numeric value -> default."""
    raw = _conf().get(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def get_config_bool(key: str, default: bool) -> bool:
    raw = _conf().get(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _cli(argv: list[str]) -> int:
    import sys

    if argv and argv[0] == "root":
        print(project_root())
        return 0

    if len(argv) < 2:
        print(
            "usage: _tooling_conf.py {get|getcsv|getint|getbool} KEY [default] | root",
            file=sys.stderr,
        )
        return 1
    cmd, key = argv[0], argv[1]
    default = argv[2] if len(argv) > 2 else None
    if cmd == "get":
        result = get_config(key, default)
        print(result if result is not None else "")
    elif cmd == "getcsv":
        default_list = default.split(",") if default else []
        print(",".join(get_config_csv(key, default_list)))
    elif cmd == "getint":
        print(get_config_int(key, int(default) if default is not None else 0))
    elif cmd == "getbool":
        default_bool = str(default).strip().lower() in {"1", "true", "yes", "on"} if default else False
        print("1" if get_config_bool(key, default_bool) else "0")
    else:
        print(f"unknown command: {cmd}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(_cli(sys.argv[1:]))
