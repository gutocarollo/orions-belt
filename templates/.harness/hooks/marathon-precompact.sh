#!/usr/bin/env bash
# marathon-precompact — PreCompact. Marca a compactação no Journal do RUN.md
# (o reinject na volta é quem restaura o estado).
#
# MATERIALIZAÇÃO (F9-fixes): diretório de runs vem de HARNESS_RUNS_DIR
# (default .harness/runs) via .harness/lib/_tooling_conf.py — era hardcoded.
set -uo pipefail
ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}"
[ -n "$ROOT" ] || exit 0

CONF_PY="$ROOT/.harness/lib/_tooling_conf.py"
RUNS_DIR=".harness/runs"
if command -v python3 >/dev/null 2>&1 && [ -f "$CONF_PY" ]; then
  v="$(HARNESS_PROJECT_ROOT="$ROOT" python3 "$CONF_PY" get HARNESS_RUNS_DIR .harness/runs 2>/dev/null)"
  [ -n "$v" ] && RUNS_DIR="$v"
fi

ACTIVE="$ROOT/$RUNS_DIR/ACTIVE"
[ -f "$ACTIVE" ] || exit 0
SLUG=$(head -1 "$ACTIVE" | tr -d '[:space:]')
RUN="$ROOT/$RUNS_DIR/$SLUG/RUN.md"
[ -f "$RUN" ] && echo "- $(date +%H:%M) compactação de contexto (estado preservado aqui)" >> "$RUN"
exit 0
