#!/usr/bin/env bash
# subagent-throttle — PreToolUse (Task|Agent). CONFIGURABLE cap on concurrent
# subagents.
#
# MATERIALIZATION (F3, orions-belt): an adapted copy of
# engine/hooks/subagent-throttle.sh (the authoring/testing source inside the
# orions-belt repo) for the target project — Claude Code hooks run as a local
# shell command (`$CLAUDE_PROJECT_DIR/.claude/hooks/...`), and there is no way
# to reference a path outside the repo portably across machines. The ONLY
# functional difference from the source: `CONF_PY` points at
# `$ROOT/.harness/lib/_tooling_conf.py` (also materialized via Copier —
# see that file) instead of a path relative to `engine/`, which no longer
# exists once installed in the target project.
#
# PARAMETERIZED version of the original hook from the reference donor harness
# (CAP=6 hardcoded at the source). Here the cap and the stale-slot TTL
# come from HARNESS_SUBAGENT_MAX_CONCURRENT /
# HARNESS_SUBAGENT_SLOT_STALE_MINUTES in .harness/harness.conf, read via
# .harness/lib/_tooling_conf.py — the framework's SINGLE parser (it does not
# duplicate a parallel bash parser).
#
# Fail-open: if python3 or _tooling_conf.py are unavailable, or the project
# has no .harness/harness.conf, it falls back to the original defaults
# (CAP=6 / STALE=45min) — the behavior never regresses to "no throttle".
#
# Slots = files in $HARNESS_RUNS_DIR/.slots (default ".harness/runs" —
# M-HIGH/H4, adversarial audit: it was hardcoded ".claude/runs" even though this
# hook also runs on Codex via .codex/hooks.json (H3/A1), which would
# instruct a codex-only project to create a ".claude" folder that makes no
# sense there. It now reads HARNESS_RUNS_DIR just as CAP/STALE_MIN already did.
set -uo pipefail
ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}"
[ -n "$ROOT" ] || exit 0

CONF_PY="$ROOT/.harness/lib/_tooling_conf.py"

_conf_int() {
  # $1=key $2=default
  local val
  if command -v python3 >/dev/null 2>&1 && [ -f "$CONF_PY" ]; then
    val="$(HARNESS_PROJECT_ROOT="$ROOT" python3 "$CONF_PY" getint "$1" "$2" 2>/dev/null)"
    if [[ "$val" =~ ^-?[0-9]+$ ]]; then
      echo "$val"
      return 0
    fi
  fi
  echo "$2"
}

_conf_get() {
  # $1=key $2=default
  local val
  if command -v python3 >/dev/null 2>&1 && [ -f "$CONF_PY" ]; then
    val="$(HARNESS_PROJECT_ROOT="$ROOT" python3 "$CONF_PY" get "$1" "$2" 2>/dev/null)"
    [ -n "$val" ] && { echo "$val"; return 0; }
  fi
  echo "$2"
}

CAP="$(_conf_int HARNESS_SUBAGENT_MAX_CONCURRENT 6)"
STALE_MIN="$(_conf_int HARNESS_SUBAGENT_SLOT_STALE_MINUTES 45)"
RUNS_DIR="$(_conf_get HARNESS_RUNS_DIR .harness/runs)"

SLOTS="$ROOT/$RUNS_DIR/.slots"; mkdir -p "$SLOTS"
exec 9>>"$SLOTS.lock"
flock 9
find "$SLOTS" -type f -name '*.slot' -mmin "+$STALE_MIN" -delete 2>/dev/null
COUNT=$(find "$SLOTS" -type f -name '*.slot' | wc -l)
if [ "$COUNT" -ge "$CAP" ]; then
  cat >&2 <<EOF
THROTTLE: $COUNT/$CAP subagents already in flight — do not launch more right now (cap configured via HARNESS_SUBAGENT_MAX_CONCURRENT in .harness/harness.conf).
Wait for the active ones to finish (completions arrive as notifications) and relaunch in batches of up to $CAP. If a subagent died without releasing its slot, it expires on its own in ${STALE_MIN}min.
EOF
  exit 2
fi
touch "$SLOTS/$(date +%s%N).slot"
exit 0
