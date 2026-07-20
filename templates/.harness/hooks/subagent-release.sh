#!/usr/bin/env bash
# subagent-release — PostToolUse/PostToolUseFailure (Task|Agent). Releases 1
# throttle slot and records 1 line in the tasks journal.
#
# MATERIALIZATION (M-HIGH/H4, adversarial audit): $HARNESS_RUNS_DIR
# (default ".harness/runs") instead of hardcoded ".claude/runs" — it must
# point at the SAME directory that subagent-throttle.sh uses (the
# throttle/release pair shares the slots), and this hook also runs on Codex
# via .codex/hooks.json.
set -uo pipefail
ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}"
[ -n "$ROOT" ] || exit 0

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
