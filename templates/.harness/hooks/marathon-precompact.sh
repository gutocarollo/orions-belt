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
IN=$(cat)
ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}"

LOCATOR="$(dirname "${BASH_SOURCE[0]}")/marathon-locate.sh"
if [ ! -r "$LOCATOR" ]; then
  echo "marathon-precompact: required dependency missing: $LOCATOR" >&2
  exit 1
fi
if ! . "$LOCATOR" || ! declare -F marathon_locate >/dev/null 2>&1; then
  echo "marathon-precompact: required dependency invalid: $LOCATOR" >&2
  exit 1
fi

CONF_PY="$ROOT/.harness/lib/_tooling_conf.py"
RUNS_DIR=".harness/runs"
if command -v python3 >/dev/null 2>&1 && [ -f "$CONF_PY" ]; then
  v="$(HARNESS_PROJECT_ROOT="$ROOT" python3 "$CONF_PY" get HARNESS_RUNS_DIR .harness/runs 2>/dev/null)"
  [ -n "$v" ] && RUNS_DIR="$v"
fi

HOOK_SESSION_ID="$(python3 -c 'import json,sys
try: print(str(json.load(sys.stdin).get("session_id", "")))
except Exception: print("")' <<<"$IN" 2>/dev/null || true)"
SESSION_ID="$(marathon_session_id "$HOOK_SESSION_ID")" || SESSION_ID=""
[ -n "$SESSION_ID" ] || {
  echo "marathon-precompact: missing valid session_id; refusing to select a global marathon" >&2
  exit 1
}
marathon_locate_for_session "$ROOT" "$RUNS_DIR" "$SESSION_ID"
LOCATE_RC=$?
[ "$LOCATE_RC" -eq 1 ] && exit 0
[ "$LOCATE_RC" -eq 0 ] || exit 1
[ -n "$SESSION_ID" ] && marathon_session_is_ignored "$SESSION_ID" "$MARATHON_RUN_DIR" && exit 0
# The pause state is stamped too: reading the journal later, "compacted while
# paused" is the difference between a run that stalled and one that was parked
# on purpose.
marathon_pause_state
case "$MARATHON_PAUSE_STATUS" in
  paused)  NOTE="context compaction (state preserved here; run PAUSED until $MARATHON_PAUSE_UNTIL)" ;;
  expired) NOTE="context compaction (state preserved here; pause EXPIRED at $MARATHON_PAUSE_UNTIL, awaiting the owner's decision)" ;;
  *)       NOTE="context compaction (state preserved here)" ;;
esac
echo "- $(date +%H:%M) $NOTE" >> "$MARATHON_RUN_MD"
exit 0
