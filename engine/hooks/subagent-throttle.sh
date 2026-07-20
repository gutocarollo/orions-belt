#!/usr/bin/env bash
# subagent-throttle — PreToolUse (Task|Agent). CONFIGURABLE cap on concurrent
# subagents.
#
# PARAMETERIZED version of the original learnhouse hook
# (/home/augusto/code/learnhouse/.claude/hooks/subagent-throttle.sh —
# CAP=6 hardcoded at Line 11; Augusto's rule 2026-06-22: "my tokens
# expired when you launched 17 at once. please launch 6 at
# most"). Here the cap and the stale-slot TTL come from
# HARNESS_SUBAGENT_MAX_CONCURRENT / HARNESS_SUBAGENT_SLOT_STALE_MINUTES in
# .harness/harness.conf, read via engine/_tooling_conf.py — the framework's
# SINGLE parser (docs/planning/research/01-guto-wiki.md §b: the guto-wiki
# reimplemented the same load_config() 3x without extracting it; this hook
# does not repeat the mistake by calling a parallel bash parser).
#
# Fail-open: if python3 or _tooling_conf.py are unavailable, or the
# target project has no .harness/harness.conf, it falls back to the original
# defaults (CAP=6 / STALE=45min) — the behavior never regresses to "no throttle".
#
# Slots = files in $HARNESS_RUNS_DIR/.slots (default ".harness/runs" —
# M-ALTA/H4, adversarial audit: it was hardcoded ".claude/runs" even though this
# hook also runs on Codex via .codex/hooks.json (H3/A1), which
# would instruct a codex-only project to create a ".claude" folder that makes
# no sense for it. It now reads HARNESS_RUNS_DIR just as CAP/STALE_MIN already did.
set -uo pipefail
ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}"
[ -n "$ROOT" ] || exit 0

ENGINE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONF_PY="$ENGINE_DIR/_tooling_conf.py"

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
THROTTLE: $COUNT/$CAP subagents already in flight — do not launch more now (cap configured via HARNESS_SUBAGENT_MAX_CONCURRENT in .harness/harness.conf; rule origin: 2026-06-22, 17 in parallel blew the account's token limit).
Aguarde os ativos terminarem (as conclusões chegam como notificação) e relance em lotes de até $CAP. Se um subagent morreu sem liberar slot, ele expira sozinho em ${STALE_MIN}min.
EOF
  exit 2
fi
touch "$SLOTS/$(date +%s%N).slot"
exit 0
