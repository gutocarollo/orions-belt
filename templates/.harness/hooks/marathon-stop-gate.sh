#!/usr/bin/env bash
# marathon-stop-gate — Stop hook. Inert when no marathon is active.
# With $RUNS_DIR/ACTIVE + open items in RUN.md: blocks the stop and
# returns the "Próxima ação". Anti-lockup: N consecutive blocks WITHOUT RUN.md
# changing → releases with a warning (real progress resets the strikes).
#
# MATERIALIZATION (F9-fixes): the runs directory (HARNESS_RUNS_DIR, default
# .harness/runs) and the strike cap (HARNESS_MARATHON_MAX_BLOCKS_WITHOUT_PROGRESS,
# default 3) come from .harness/harness.conf via .harness/lib/_tooling_conf.py —
# they used to be hardcoded (the 2 keys existed in the schema since F0 with no consumer).
# The default of HARNESS_RUNS_DIR changed from ".claude/runs" to ".harness/runs"
# in M-ALTA/H4 (post-H3 adversarial audit, symmetric gap) — the old value
# carried "claude" even in codex-only projects; ".harness/" is already
# the neutral/runtime-agnostic directory of the rest of the framework
# (harness.conf, answers.yml, hooks, lib). Projects ALREADY installed keep the
# value recorded in their own answers.yml (Copier does not rewrite an answer
# already given — only the default for NEW installs changes).
set -uo pipefail
IN=$(cat)
command -v jq >/dev/null 2>&1 || exit 0
[ "$(jq -r '.stop_hook_active // false' <<<"$IN")" = "true" ] && exit 0
ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}"
[ -n "$ROOT" ] || exit 0

CONF_PY="$ROOT/.harness/lib/_tooling_conf.py"
_conf_get() {
  local val
  if command -v python3 >/dev/null 2>&1 && [ -f "$CONF_PY" ]; then
    val="$(HARNESS_PROJECT_ROOT="$ROOT" python3 "$CONF_PY" get "$1" "$2" 2>/dev/null)"
    [ -n "$val" ] && { echo "$val"; return 0; }
  fi
  echo "$2"
}
_conf_int() {
  local val
  if command -v python3 >/dev/null 2>&1 && [ -f "$CONF_PY" ]; then
    val="$(HARNESS_PROJECT_ROOT="$ROOT" python3 "$CONF_PY" getint "$1" "$2" 2>/dev/null)"
    [[ "$val" =~ ^-?[0-9]+$ ]] && { echo "$val"; return 0; }
  fi
  echo "$2"
}
RUNS_DIR="$(_conf_get HARNESS_RUNS_DIR .harness/runs)"
MAX_STRIKES="$(_conf_int HARNESS_MARATHON_MAX_BLOCKS_WITHOUT_PROGRESS 3)"

ACTIVE="$ROOT/$RUNS_DIR/ACTIVE"
[ -f "$ACTIVE" ] || exit 0
SLUG=$(head -1 "$ACTIVE" | tr -d '[:space:]')
RUN="$ROOT/$RUNS_DIR/$SLUG/RUN.md"
[ -f "$RUN" ] || exit 0

OPEN=$(grep -c '^- \[ \]' "$RUN" || true)
[ "$OPEN" -eq 0 ] && exit 0   # checklist empty — legitimate stop

# WAITING/AGUARDANDO (user decision) = legitimate stop.
# Bilingual: the marathon skill emits "## Next action" (en) or "## Próxima ação" (pt),
# and "WAITING:" (en) or "AGUARDANDO:" (pt) — match both so the gate works in either mode.
NEXT=$(awk '/^## (Next action|Próxima ação)/{getline; while($0 ~ /^\s*$/) getline; print; exit}' "$RUN")
case "$NEXT" in WAITING:*|AGUARDANDO:*) exit 0 ;; esac

# N strikes without progress → release
STRIKES="$ROOT/$RUNS_DIR/$SLUG/.stop-strikes"
MTIME=$(stat -c %Y "$RUN" 2>/dev/null || echo 0)
read -r COUNT LAST < <(cat "$STRIKES" 2>/dev/null || echo "0 0")
[ "$MTIME" != "$LAST" ] && COUNT=0   # RUN.md changed since the last strike = progress
if [ "$COUNT" -ge "$MAX_STRIKES" ]; then
  rm -f "$STRIKES"
  echo '{"systemMessage":"marathon-stop-gate: '"$MAX_STRIKES"' blocks without progress in RUN.md — releasing the stop. Marathon still ACTIVE ('"$SLUG"'); resume with the marathon skill or end it with rm '"$RUNS_DIR"'/ACTIVE."}'
  exit 0
fi
echo "$((COUNT + 1)) $MTIME" > "$STRIKES"

cat >&2 <<EOF
MARATHON ACTIVE ($SLUG): $OPEN open item(s) in the checklist — the stop was blocked.
Recorded next action: ${NEXT:-"(empty — update RUN.md)"}
Keep executing (marathon skill §2: close item → mark [x] → update the "Next action" section).
If you are genuinely blocked on a user decision: write "WAITING: <question>" in the "Next action" section and stop.
End the marathon for good: rm $RUNS_DIR/ACTIVE
EOF
exit 2
