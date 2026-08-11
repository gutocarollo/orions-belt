#!/usr/bin/env bash
# subagent-release — PostToolUse/PostToolUseFailure (Task|Agent) or
# SubagentStop (Codex). Records lightweight cost telemetry, releases 1 throttle
# slot and records 1 line in the tasks journal.
#
# Cost telemetry is deliberately fail-open and runs before the slot-directory
# early return, so completed agents remain observable even when throttling was
# inactive. No prompts/responses are persisted.
set -uo pipefail
ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}"
[ -n "$ROOT" ] || exit 0

PAYLOAD="$(cat 2>/dev/null || true)"
COST_LEDGER="$ROOT/.harness/hooks/subagent-cost-ledger.py"
if [ -n "$PAYLOAD" ] && command -v python3 >/dev/null 2>&1 && [ -f "$COST_LEDGER" ]; then
  printf '%s' "$PAYLOAD" | python3 "$COST_LEDGER" --runtime auto >/dev/null 2>&1 || true
fi

CONF_PY="$ROOT/.harness/lib/_tooling_conf.py"
_conf_get() {
  # $1=key $2=default
  local val
  if command -v python3 >/dev/null 2>&1 && [ -f "$CONF_PY" ]; then
    val="$(HARNESS_PROJECT_ROOT="$ROOT" python3 "$CONF_PY" get "$1" "$2" 2>/dev/null)"
    [ -n "$val" ] && { echo "$val"; return 0; }
  fi
  echo "$2"
}
RUNS_DIR="$(_conf_get HARNESS_RUNS_DIR .harness/runs)"

SLOTS="$ROOT/$RUNS_DIR/.slots"
[ -d "$SLOTS" ] || exit 0
exec 9>>"$SLOTS.lock"
flock 9
OLDEST=$(find "$SLOTS" -type f -name '*.slot' | sort | head -1)
[ -n "$OLDEST" ] && rm -f "$OLDEST"
N=$(find "$SLOTS" -type f -name '*.slot' | wc -l)
echo "$(date +%FT%T) task-done slots_in_flight=$N" >> "$ROOT/$RUNS_DIR/task-journal.log"
exit 0
