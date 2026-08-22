#!/usr/bin/env bash
# marathon-reinject — SessionStart (ANY source). Reinjects the RUN.md of the
# active marathon into the context (SessionStart stdout becomes the model's context).
#
# WIRING (2026-08-12): this hook used to be registered with matcher
# "compact|resume" only. A brand-new session (source=startup) therefore began
# with ZERO knowledge of an active marathon — the durable state came back only
# after a compaction, so closing the terminal and reopening it lost the run
# until something happened to compact. The hook is inert when no marathon is
# located, so registering it for every SessionStart costs nothing in the common
# case and is also what gives the pause-expiry question a reliable place to be
# asked.
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
IN=$(cat)
ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}"

LOCATOR="$(dirname "${BASH_SOURCE[0]}")/marathon-locate.sh"
if [ ! -r "$LOCATOR" ]; then
  echo "marathon-reinject: required dependency missing: $LOCATOR" >&2
  exit 1
fi
if ! . "$LOCATOR" || ! declare -F marathon_locate >/dev/null 2>&1; then
  echo "marathon-reinject: required dependency invalid: $LOCATOR" >&2
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
  echo "marathon-reinject: missing valid session_id; refusing to select a global marathon" >&2
  exit 1
}
marathon_locate_for_session "$ROOT" "$RUNS_DIR" "$SESSION_ID"
LOCATE_RC=$?
[ "$LOCATE_RC" -eq 1 ] && exit 0
[ "$LOCATE_RC" -eq 0 ] || exit 1
[ -n "$SESSION_ID" ] && marathon_session_is_ignored "$SESSION_ID" "$MARATHON_RUN_DIR" && exit 0
HOOKS_DIR="$(dirname "${BASH_SOURCE[0]}")"
marathon_pause_state

# PAUSED (2026-08-12). Injecting the checklist IS what makes a model pick the
# work back up — so a paused run must NOT get its RUN.md injected. What goes in
# is the minimum needed for the agent to recognise the run exists, plus an
# explicit prohibition. Silence would be worse than a notice: the agent would
# find ACTIVE/PAUSED on disk with no framing and could well decide on its own
# that resuming is the helpful thing to do.
if [ "$MARATHON_PAUSE_STATUS" = "paused" ]; then
  cat <<EOF
<marathon-run-state run_id="$MARATHON_RUN_ID" slug="$MARATHON_SLUG" dir="$MARATHON_RUN_DIR" status="paused">
Marathon PAUSED until $MARATHON_PAUSE_UNTIL (paused at ${MARATHON_PAUSE_AT:-unknown}).
Reason: ${MARATHON_PAUSE_REASON:-(not given)}
DO NOT resume it, DO NOT execute its "Next action", DO NOT re-plan it and do not
mention it as pending work unless the owner brings it up. The checklist is
deliberately NOT injected while paused. Work on whatever the owner asks in this
session instead.
If the owner explicitly asks to resume early: bash $HOOKS_DIR/marathon-locate.sh resume
</marathon-run-state>
EOF
  exit 0
fi

# EXPIRED. The window closed, which is NOT the same as permission to resume:
# the requirement is that the agent ASKS. The state goes in (it is genuinely
# useful for the question to be concrete) with the execution ban stated first,
# so the instruction is read before the checklist that would otherwise read as
# a to-do list.
if [ "$MARATHON_PAUSE_STATUS" = "expired" ]; then
  cat <<EOF
<marathon-run-state run_id="$MARATHON_RUN_ID" slug="$MARATHON_SLUG" dir="$MARATHON_RUN_DIR" status="pause-expired">
Marathon PAUSE EXPIRED — the window ran to $MARATHON_PAUSE_UNTIL and this run is
still ACTIVE with open items. Reason it was paused: ${MARATHON_PAUSE_REASON:-(not given)}

MANDATORY, BEFORE ANY WORK ON THIS RUN: ask the owner whether to resume it,
postpone it to a new date, or end it. Do NOT execute the "Next action" and do
NOT start closing checklist items on the strength of this injection alone.
  resume:   bash $HOOKS_DIR/marathon-locate.sh resume
  postpone: bash $HOOKS_DIR/marathon-locate.sh pause <YYYY-MM-DD|+Nd> <reason>
  end:      $(marathon_teardown_hint)
State below is context for that question only:
EOF
  head -150 "$MARATHON_RUN_MD"
  echo "</marathon-run-state>"
  exit 0
fi

echo "<marathon-run-state run_id=\"$MARATHON_RUN_ID\" slug=\"$MARATHON_SLUG\" dir=\"$MARATHON_RUN_DIR\">"
echo "Marathon ACTIVE. Durable state below (source of truth — marathon skill §3: execute the \"Próxima ação\", do not re-plan):"
head -150 "$MARATHON_RUN_MD"
echo "</marathon-run-state>"
exit 0
