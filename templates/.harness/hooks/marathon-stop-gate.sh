#!/usr/bin/env bash
# marathon-stop-gate — Stop hook. Inert when no marathon is active.
# With the marathon located + open items in RUN.md: blocks the stop and
# returns the "Próxima ação". Anti-lockup: N consecutive blocks WITHOUT RUN.md
# changing → releases with a warning (real progress resets the strikes).
# Inert as well while the run is PAUSED; an expired pause also releases the stop
# and reports the expiry instead of resuming (see the PAUSE section of
# marathon-locate.sh).
#
# MATERIALIZATION (F9-fixes): the runs directory (HARNESS_RUNS_DIR, default
# .harness/runs), the strike cap (HARNESS_MARATHON_MAX_BLOCKS_WITHOUT_PROGRESS,
# default 3) and the registry staleness cutoff (HARNESS_MARATHON_STALE_DAYS,
# default 7) come from .harness/harness.conf via .harness/lib/_tooling_conf.py —
# they used to be hardcoded (the 2 keys existed in the schema since F0 with no consumer).
# The default of HARNESS_RUNS_DIR changed from ".claude/runs" to ".harness/runs"
# in M-ALTA/H4 (post-H3 adversarial audit, symmetric gap) — the old value
# carried "claude" even in codex-only projects; ".harness/" is already
# the neutral/runtime-agnostic directory of the rest of the framework
# (harness.conf, answers.yml, hooks, lib). Projects ALREADY installed keep the
# value recorded in their own answers.yml (Copier does not rewrite an answer
# already given — only the default for NEW installs changes).
#
# CROSS-REPO (measured 2026-08-01, field report from a downstream install):
# this gate used to look ONLY at "$ROOT/$RUNS_DIR/ACTIVE" — a marathon whose
# run directory lived in a different working directory than the session's
# CLAUDE_PROJECT_DIR was invisible, and the gate degraded to a silent no-op:
# no block, no `.stop-strikes`, ever. Location now goes through
# marathon-locate.sh (ACTIVE local — slug or absolute path — then the
# $HOME/.harness/marathon-active registry, pruning stale/dead entries).
#
# Two sibling defects fixed alongside: `^- \[ \]` ignored every indented
# sub-item (a RUN.md with 6 real open items under a parent bullet counted as
# 1), and the strike counter measured mtime, which has 1-second granularity
# (two real edits inside the same second read as "no progress") and reset on
# a bare `touch`. Both replaced below: any indentation of `[ ]`/`[~]` counts,
# and progress is a checksum of RUN.md's content.
set -uo pipefail
IN=$(cat)
command -v python3 >/dev/null 2>&1 || {
  echo "marathon-stop-gate: WARN python3 unavailable; gate inactive" >&2
  exit 0
}
STOP_ACTIVE="$(python3 -c 'import json,sys
try: print(str(bool(json.load(sys.stdin).get("stop_hook_active", False))).lower())
except Exception: print("false")' <<<"$IN")"
[ "$STOP_ACTIVE" = "true" ] && exit 0
ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}"

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
export HARNESS_MARATHON_STALE_DAYS="$(_conf_int HARNESS_MARATHON_STALE_DAYS 7)"

. "$(dirname "${BASH_SOURCE[0]}")/marathon-locate.sh"
marathon_locate "$ROOT" "$RUNS_DIR" || exit 0
SLUG="$MARATHON_SLUG"
RUN="$MARATHON_RUN_MD"
TEARDOWN="$(marathon_teardown_hint)"

# Open = "[ ]" (todo) or "[~]" (in progress), at ANY indentation. The old
# anchor was '^- \[ \]', which silently ignored every NESTED item — a RUN.md
# whose remaining work sat under a parent bullet counted zero open and the
# gate released the stop with real work still pending.
#
# Counted BEFORE the pause branch on purpose: a finished run that was left
# paused has nothing to decide, so it must stay silent instead of nagging about
# an expired window forever.
OPEN=$(grep -c '^[[:space:]]*- \[[ ~]\]' "$RUN" || true)
[ "$OPEN" -eq 0 ] && exit 0   # checklist empty — legitimate stop

# PAUSE (2026-08-12). A paused marathon must never force the turn to continue:
# the owner suspended THIS run on purpose and is working on something else. The
# gate going inert is what makes the pause real — the checklist still has open
# items, so without this branch the gate would keep pushing the agent back into
# a run that is supposed to be asleep.
#
# `expired` is deliberately NOT treated as "resume". Re-arming the gate on
# expiry would put the agent straight back to executing on its own, which is
# precisely the behaviour this mechanism exists to prevent. Instead the stop is
# released and the owner is TOLD the window closed; the decision to resume,
# postpone or end is a human one (the reinject hook asks it explicitly at the
# next session start).
marathon_pause_state
case "$MARATHON_PAUSE_STATUS" in
  paused)
    exit 0 ;;
  expired)
    MP_SLUG="$SLUG" MP_UNTIL="$MARATHON_PAUSE_UNTIL" MP_DIR="$MARATHON_RUN_DIR" \
    MP_TEARDOWN="$TEARDOWN" MP_HOOKS="$(dirname "${BASH_SOURCE[0]}")" python3 -c '
import json, os
msg = ("marathon %s: the pause window ended (%s) and NOTHING was resumed automatically. "
       "Decide before any work on this run — resume: bash %s/marathon-locate.sh resume | "
       "postpone: bash %s/marathon-locate.sh pause <YYYY-MM-DD|+Nd> <reason> | end it: %s"
       ) % (os.environ["MP_SLUG"], os.environ["MP_UNTIL"], os.environ["MP_HOOKS"],
            os.environ["MP_HOOKS"], os.environ["MP_TEARDOWN"])
print(json.dumps({"systemMessage": msg}))'
    exit 0 ;;
esac

# WAITING/AGUARDANDO (user decision) = legitimate stop.
# Bilingual: the marathon skill emits "## Next action" (en) or "## Próxima ação" (pt),
# and "WAITING:" (en) or "AGUARDANDO:" (pt) — match both so the gate works in either mode.
NEXT=$(awk '/^## (Next action|Próxima ação)/{getline; while($0 ~ /^\s*$/) getline; print; exit}' "$RUN")
case "$NEXT" in WAITING:*|AGUARDANDO:*) exit 0 ;; esac

# N strikes without progress → release.
#
# Progress is measured by the CONTENT of RUN.md, not its mtime. mtime was
# wrong in both directions: 1-second granularity means two real edits inside
# the same second read as "no progress", and a bare `touch` alone reset the
# counter, so a spinning agent could keep the gate armed without changing
# anything. The checksum answers the only question the counter asks — did
# the durable state actually move?
STRIKES="$MARATHON_RUN_DIR/.stop-strikes"
STAMP=$( (cksum < "$RUN") 2>/dev/null | awk '{print $1"-"$2}' )
[ -n "$STAMP" ] || STAMP=0
read -r COUNT LAST < <(cat "$STRIKES" 2>/dev/null || echo "0 0")
[ "$STAMP" != "$LAST" ] && COUNT=0   # RUN.md content changed = progress
if [ "$COUNT" -ge "$MAX_STRIKES" ]; then
  rm -f "$STRIKES"
  echo '{"systemMessage":"marathon-stop-gate: '"$MAX_STRIKES"' blocks without progress in RUN.md — releasing the stop. Marathon still ACTIVE ('"$SLUG"'); resume with the marathon skill or end it with: '"$TEARDOWN"'"}'
  exit 0
fi
echo "$((COUNT + 1)) $STAMP" > "$STRIKES"

cat >&2 <<EOF
MARATHON ACTIVE ($SLUG): $OPEN open item(s) in the checklist — the stop was blocked.
Run directory: $MARATHON_RUN_DIR (located via: $MARATHON_SOURCE_KIND)
Recorded next action: ${NEXT:-"(empty — update RUN.md)"}
Keep executing (marathon skill §2: close item → mark [x] → update the "Next action" section).
If you are genuinely blocked on a user decision: write "WAITING: <question>" in the "Next action" section and stop.
End the marathon for good: $TEARDOWN
EOF
exit 2
