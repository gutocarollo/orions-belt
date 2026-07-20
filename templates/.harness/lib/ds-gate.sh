#!/usr/bin/env bash
# =============================================================================
# ds-gate.sh — Generic design-system tokenization gate (engine).
# -----------------------------------------------------------------------------
# PORTED from apps/web/scripts/ds-gate.sh (reference donor harness) — rescue
# plan §R1a. Proves "how much of the design is tokenized" DETERMINISTICALLY:
# counts, per dimension, HARDCODED design colors/values that bypass the
# Tailwind/CSS-var tokens. RATCHET mode: compares against .ds-baseline.txt
# (inside the web app directory) and FAILS (exit 1) only if some dimension
# INCREASES. Without a baseline (1st run), it runs in report-only mode and
# never fails — the ratchet is born from the first explicit
# `--update-baseline`, not from a guessed value.
#
# GENERICITY (vs. the source version): no hardcoded brand string. The web app
# directory comes from HARNESS_WEB_APP_DIR (.harness/harness.conf, read at
# runtime via _tooling_conf.py — same directory as this script) or from an
# explicit `--dir <path>`. Brand exclusions (e.g. custom color-scale name,
# tokens file path) come from DS_BRAND_EXCLUDE_PATTERNS (ERE CSV) — default
# empty, engine stricter when unconfigured (never more permissive by omission).
#
# Usage:
#   bash .harness/lib/ds-gate.sh [--dir <web-app-dir>] [check|--report|--update-baseline]
#
# Allowlist (2 levels, both versioned/auditable, INSIDE the web app
# directory):
#   - inline: comment the line with  // ds-allow: <reason>   (or /* ds-allow: */)
#   - by path: globs in .ds-allowlist (one per line; '#'=comment)
# =============================================================================
set -uo pipefail

LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${HARNESS_PROJECT_ROOT:-${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}}"
if [ -z "$PROJECT_ROOT" ]; then
  echo "ds-gate: could not resolve the project root (neither HARNESS_PROJECT_ROOT/CLAUDE_PROJECT_DIR nor git repo) — fail-open." >&2
  exit 0
fi

CONF_PY="$LIB_DIR/_tooling_conf.py"
_conf_get() {
  if command -v python3 >/dev/null 2>&1 && [ -f "$CONF_PY" ]; then
    HARNESS_PROJECT_ROOT="$PROJECT_ROOT" python3 "$CONF_PY" get "$1" "$2" 2>/dev/null && return 0
  fi
  echo "$2"
}
_conf_getcsv() {
  if command -v python3 >/dev/null 2>&1 && [ -f "$CONF_PY" ]; then
    HARNESS_PROJECT_ROOT="$PROJECT_ROOT" python3 "$CONF_PY" getcsv "$1" "" 2>/dev/null
  fi
}

WEB_APP_DIR_ARG=""
if [[ "${1:-}" == "--dir" ]]; then
  WEB_APP_DIR_ARG="${2:-}"
  shift 2 2>/dev/null || shift "$#"
fi
WEB_APP_DIR="${WEB_APP_DIR_ARG:-$(_conf_get HARNESS_WEB_APP_DIR .)}"
WEB_APP_DIR="${WEB_APP_DIR%/}"
[ -z "$WEB_APP_DIR" ] && WEB_APP_DIR="."

TARGET_DIR="$PROJECT_ROOT"
[ "$WEB_APP_DIR" != "." ] && TARGET_DIR="$PROJECT_ROOT/$WEB_APP_DIR"
if [ ! -d "$TARGET_DIR" ]; then
  echo "ds-gate: web app directory ($TARGET_DIR) does not exist — nothing to check (fail-open)."
  exit 0
fi
cd "$TARGET_DIR" || { echo "ds-gate: failed to enter $TARGET_DIR — fail-open." >&2; exit 0; }

DS_BRAND_EXCLUDE_ERE="$(_conf_getcsv DS_BRAND_EXCLUDE_PATTERNS | tr ',' '|')"
_brand_filter() {
  if [[ -n "$DS_BRAND_EXCLUDE_ERE" ]]; then
    grep -viE "$DS_BRAND_EXCLUDE_ERE"
  else
    cat
  fi
}

ROOT="."
SRC_GLOB='--include=*.tsx --include=*.ts'
EXCLUDE='--exclude-dir=node_modules --exclude-dir=.next --exclude-dir=dist --exclude-dir=build --exclude-dir=scripts'
BASELINE=".ds-baseline.txt"
ALLOWFILE=".ds-allowlist"
MODE="${1:-check}"

# by-path allowlist: one real GLOB per line (fnmatch), not substring.
#
# H2/A6.3 (post-v1.0.0 adversarial audit, bypass REPRODUCED): the previous
# version read `.ds-allowlist` and did `grep -vF` (LITERAL substring) against
# `$ROOT/<line>` — a pattern like `legacy/**` never matched any real path
# because the substring "**" does not exist in any real path; the docs
# promised "glob" (comment at the top of this file and docs/manual/
# 05-hooks-posttooluse.md) but in practice the allowlist was inoperative for
# any entry with a wildcard. Fix: filter via `.harness/lib/
# ds_allowlist_filter.py` (real fnmatch, same dependency `_tooling_conf.py`
# already requires) — each pattern matches against the relative path (before
# the first ':' in the grep -n output). `fnmatch` does not treat `/` as
# special (`*`/`**` match any suffix, including subdirectories) — enough to
# "accept a whole legacy folder/file", documented here instead of promising
# `pathlib.Path.match`/shell-glob semantics (which would STOP at `/` for a
# single `*`). SEPARATE script on purpose (not inline `python3 - <<HEREDOC`):
# `python3 -` reads the PROGRAM ITSELF from stdin — a heredoc consumes stdin
# to load the source and `sys.stdin` arrives empty to the program, silently
# discarding the entire grep pipe input (real bug found this round while
# testing the 1st version of the fix — see comment at the top of
# ds_allowlist_filter.py).
build_allow_patterns() {
  if [[ -f "$ALLOWFILE" ]]; then
    grep -vE '^\s*#|^\s*$' "$ALLOWFILE" 2>/dev/null
  fi
}
mapfile -t ALLOW_PATTERNS < <(build_allow_patterns)

_allowlist_filter() {
  if [[ ${#ALLOW_PATTERNS[@]} -eq 0 ]] || ! command -v python3 >/dev/null 2>&1 || [[ ! -f "$LIB_DIR/ds_allowlist_filter.py" ]]; then
    cat
    return
  fi
  python3 "$LIB_DIR/ds_allowlist_filter.py" "${ALLOW_PATTERNS[@]}"
}

# counts occurrences of an ERE in .ts/.tsx, excluding dirs, `ds-allow:`,
# allowlisted paths (real glob, see _allowlist_filter) and the configured
# brand exclude (DS_BRAND_EXCLUDE_PATTERNS)
count() {
  local ere="$1"; shift
  local extra_filter="${1:-cat}"
  local out
  out=$(grep -rEn $SRC_GLOB $EXCLUDE "$ere" "$ROOT" 2>/dev/null | grep -v 'ds-allow:')
  printf '%s\n' "$out" | _allowlist_filter | eval "$extra_filter" | _brand_filter | grep -c .
}

# ---- Dimensions (ERE + extra filter). Generic Tailwind/shadcn engine. -------
declare -A DIMS
declare -A FILT
DIMS[color-gray]='(^|[^-a-z])(bg|text|border|ring|divide|from|via|to|fill|stroke)-gray-(50|100|200|300|400|500|600|700|800|900|950)'
FILT[color-gray]='cat'
# color-wb counts ONLY SOLID forms: white/black with alpha (/N or /[..]) is the
# translucent idiom (glass/scrim/hairline over media or surface) — theme-independent
# by definition. Solid = real debt (should be a semantic token).
DIMS[color-wb]='(bg|text|border|ring|from|via|to|fill|stroke)-(white|black)([^a-z0-9/[-]|$)'
FILT[color-wb]='cat'
DIMS[color-named]='(bg|text|border|ring|from|via|to|fill|stroke)-(red|green|blue|emerald|amber|yellow|orange|indigo|purple|violet|rose|sky|cyan|teal|pink|lime|fuchsia)-[0-9]{2,3}'
FILT[color-named]='cat'
DIMS[color-hex]='#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b|rgba?\([0-9]'
# NEUTRAL alphas rgba(0,0,0,x)/rgba(255,255,255,x) = shadow/scrim/glass idiom
# (theme-independent) — GENERIC CSS heuristic, not brand-specific.
FILT[color-hex]='grep -viE "rgba?\\(\\s*0\\s*,\\s*0\\s*,\\s*0|rgba?\\(\\s*255\\s*,\\s*255\\s*,\\s*255|rgb\\(\\s*0\\s+0\\s+0|rgb\\(\\s*255\\s+255\\s+255"'
DIMS[typography-px]='text-\[[0-9.]+px\]'
FILT[typography-px]='cat'
DIMS[spacing-rhythm]='(gap|space-x|space-y|p|px|py|pl|pr|pt|pb|m|mx|my|mt|mb|ml|mr)-\[[0-9][^]]*(px|rem)\]'
FILT[spacing-rhythm]='cat'
DIMS[radius-shadow]='(rounded(-[a-z]+)?-\[|shadow-\[|border(-[a-z]+)?-\[[0-9]|ring-\[[0-9])'
FILT[radius-shadow]='grep -v "var(--"'
DIMS[zindex]='z-\[[0-9]+\]|(^|[^a-z-])z-[0-9]{2,}'
FILT[zindex]='grep -vE "z-\(--z-"'
DIMS[motion]='(duration|ease)-\['
FILT[motion]='grep -v "var(--"'

ORDER=(color-gray color-wb color-named color-hex typography-px spacing-rhythm radius-shadow zindex motion)

# ---- baseline I/O ------------------------------------------------------------
declare -A BASE
if [[ -f "$BASELINE" ]]; then
  while IFS='=' read -r k v; do [[ -n "$k" ]] && BASE[$k]="$v"; done < "$BASELINE"
fi

printf '%-16s %8s %10s   %s\n' "DIMENSION" "CURRENT" "BASELINE" "STATUS"
printf '%s\n' "------------------------------------------------------------"
FAIL=0; TOTAL=0
declare -A NOW
for d in "${ORDER[@]}"; do
  n=$(count "${DIMS[$d]}" "${FILT[$d]}")
  NOW[$d]=$n; TOTAL=$((TOTAL+n))
  b="${BASE[$d]:-}"
  if [[ "$MODE" == "--report" || -z "$b" ]]; then
    printf '%-16s %8s %10s   %s\n' "$d" "$n" "${b:-—}" "report"
  elif (( n > b )); then
    printf '%-16s %8s %10s   ✗ INCREASED (+%d)\n' "$d" "$n" "$b" "$((n-b))"; FAIL=1
  elif (( n < b )); then
    printf '%-16s %8s %10s   ✓ improved (-%d)\n' "$d" "$n" "$b" "$((b-n))"
  else
    printf '%-16s %8s %10s   ✓ ok\n' "$d" "$n" "$b"
  fi
done
printf '%s\n' "------------------------------------------------------------"
printf '%-16s %8s\n' "TOTAL" "$TOTAL"
echo "(0 across all = 100% tokenized. Ratchet: baseline only shrinks. No baseline = report-only, never fails.)"

if [[ "$MODE" == "--update-baseline" ]]; then
  : > "$BASELINE"
  for d in "${ORDER[@]}"; do echo "$d=${NOW[$d]}" >> "$BASELINE"; done
  echo ">> baseline updated in $TARGET_DIR/$BASELINE"
  exit 0
fi
[[ "$MODE" == "--report" ]] && exit 0
exit $FAIL
