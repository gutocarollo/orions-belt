#!/usr/bin/env bash
# marathon-reinject — SessionStart (resume|compact). Reinjects the RUN.md of the
# active marathon into the context (SessionStart stdout becomes the model's context).
#
# MATERIALIZATION (F9-fixes): the runs directory comes from HARNESS_RUNS_DIR
# (default .harness/runs) via .harness/lib/_tooling_conf.py — it used to be hardcoded.
#
# CROSS-REPO (measured 2026-08-01): located via marathon-locate.sh, same
# mechanism as marathon-stop-gate.sh. This is the more expensive half of the
# defect — after a compaction, RUN.md is the ONLY thing that survives, and a
# reinject that silently finds nothing hands the next turn to an agent with
# no checklist, which then stops, exactly as reported from the field.
set -uo pipefail
ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}"

CONF_PY="$ROOT/.harness/lib/_tooling_conf.py"
RUNS_DIR=".harness/runs"
if command -v python3 >/dev/null 2>&1 && [ -f "$CONF_PY" ]; then
  v="$(HARNESS_PROJECT_ROOT="$ROOT" python3 "$CONF_PY" get HARNESS_RUNS_DIR .harness/runs 2>/dev/null)"
  [ -n "$v" ] && RUNS_DIR="$v"
fi

. "$(dirname "${BASH_SOURCE[0]}")/marathon-locate.sh"
marathon_locate "$ROOT" "$RUNS_DIR" || exit 0
echo "<marathon-run-state slug=\"$MARATHON_SLUG\" dir=\"$MARATHON_RUN_DIR\">"
echo "Marathon ACTIVE. Durable state below (source of truth — marathon skill §3: execute the \"Próxima ação\", do not re-plan):"
head -150 "$MARATHON_RUN_MD"
echo "</marathon-run-state>"
exit 0
