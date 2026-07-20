#!/usr/bin/env bash
# test_set_hooks_path_precommit.sh — regression for the pre-commit-framework gap
# found by the WhatsApp_Agent brownfield eval (2026-07-20): a repo using the
# pre-commit framework (.pre-commit-config.yaml) leaves core.hooksPath empty, so
# set_hooks_path.sh used to set it to .githooks and silently bypass the user's
# hooks in .git/hooks/pre-commit. The fixed behavior: DETECT it, do NOT set
# core.hooksPath, and warn with the idiomatic integration.
#
# Runs set_hooks_path.sh directly (no copier needed) against a throwaway git repo.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
SHP="$REPO_ROOT/templates/.harness/lib/set_hooks_path.sh"
FAIL=0
assert() { if eval "$2"; then echo "PASS: $1"; else echo "FAIL: $1"; FAIL=1; fi; }

WORK="$(mktemp -d "${TMPDIR:-/tmp}/shp-precommit.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

# --- Case 1: pre-commit framework present -> must NOT set core.hooksPath, must warn ---
PC="$WORK/precommit"; mkdir -p "$PC/.githooks"; git -C "$PC" init -q
printf 'repos: []\n' > "$PC/.pre-commit-config.yaml"
ERR="$(bash "$SHP" "$PC" 2>&1 >/dev/null)"
assert "pre-commit repo: core.hooksPath NOT set" \
  '[ -z "$(git -C "$PC" config --get core.hooksPath)" ]'
assert "pre-commit repo: warning names the framework" \
  'printf "%s" "$ERR" | grep -qi "pre-commit framework detected"'

# --- Case 2: opt-in by hand still works (user set it themselves) ---
git -C "$PC" config core.hooksPath .githooks
bash "$SHP" "$PC" >/dev/null 2>&1
assert "pre-commit repo: an explicit user hooksPath is respected (idempotent)" \
  '[ "$(git -C "$PC" config --get core.hooksPath)" = ".githooks" ]'

# --- Case 3: plain repo (no manager) -> core.hooksPath IS set (no regression) ---
PL="$WORK/plain"; mkdir -p "$PL/.githooks"; git -C "$PL" init -q
bash "$SHP" "$PL" >/dev/null 2>&1
assert "plain repo: core.hooksPath -> .githooks (unchanged behavior)" \
  '[ "$(git -C "$PL" config --get core.hooksPath)" = ".githooks" ]'

echo
if [ "$FAIL" -eq 0 ]; then echo "RESULT: pre-commit hook-manager detection PASSED"; else echo "RESULT: FAILURES"; fi
exit "$FAIL"
