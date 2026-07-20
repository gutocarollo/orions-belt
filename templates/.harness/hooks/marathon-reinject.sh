#!/usr/bin/env bash
# marathon-reinject — SessionStart (resume|compact). Reinjects the RUN.md of the
# active marathon into the context (SessionStart stdout becomes the model's context).
#
# MATERIALIZATION (F9-fixes): the runs directory comes from HARNESS_RUNS_DIR
# (default .harness/runs) via .harness/lib/_tooling_conf.py — it used to be hardcoded.
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
[ -f "$RUN" ] || exit 0
echo "<marathon-run-state slug=\"$SLUG\">"
echo "Marathon ACTIVE. Durable state below (source of truth — marathon skill §3: execute the \"Próxima ação\", do not re-plan):"
head -150 "$RUN"
echo "</marathon-run-state>"
exit 0
