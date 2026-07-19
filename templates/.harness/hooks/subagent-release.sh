#!/usr/bin/env bash
# subagent-release — PostToolUse/PostToolUseFailure (Task|Agent). Libera 1 slot
# do throttle e registra 1 linha no journal de tasks.
#
# MATERIALIZAÇÃO (M-ALTA/H4, auditoria adversarial): $HARNESS_RUNS_DIR
# (default ".harness/runs") em vez de ".claude/runs" hardcoded — precisa
# apontar para o MESMO diretório que subagent-throttle.sh usa (o par
# throttle/release compartilha os slots), e esse hook também roda no Codex
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
echo "$(date +%FT%T) task-done slots_em_voo=$N" >> "$ROOT/$RUNS_DIR/task-journal.log"
exit 0
