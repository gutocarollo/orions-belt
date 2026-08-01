#!/usr/bin/env bash
# marathon-precompact — PreCompact. Records the compaction in the RUN.md Journal
# (the reinject on the way back is what restores the state).
#
# MATERIALIZATION (F9-fixes): the runs directory comes from HARNESS_RUNS_DIR
# (default .harness/runs) via .harness/lib/_tooling_conf.py — it used to be hardcoded.
#
# CROSS-REPO (measured 2026-08-01): located via marathon-locate.sh, same
# mechanism as marathon-stop-gate.sh — see that file for the field failure
# this fixes.
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
echo "- $(date +%H:%M) context compaction (state preserved here)" >> "$MARATHON_RUN_MD"
exit 0
