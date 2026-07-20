#!/usr/bin/env bash
# dev-doctor — GENERIC health snapshot of the dev stack + reaping of agent
# tooling leaks. Usage: .harness/hooks/dev-doctor.sh [status|reap]
#   status : open HARNESS_DEV_*_PORT ports + containers with the
#            HARNESS_DEV_CONTAINER_PREFIX prefix running (if docker exists) + WARN
#            for a runaway process. Informative, always exit 0 (SessionStart
#            must never fail because of an incomplete stack).
#   reap   : kills orphaned agent tooling (PPID 1: serena/mcp/playwright-mcp)
#            and leaked HEADLESS chromium (orphan OR lifetime > configurable cap);
#            WARN for runaway (never kills — it may be an active server).
#
# MATERIALIZATION (F9-fixes): minimal generic version of the dev-doctor from
# the reference donor harness — the donor's version knew its own stack
# (compose file, named containers, specific MCP/API healthchecks);
# this one knows ONLY what the central config declares: ports, container
# prefix and the 3 reap/runaway caps (HARNESS_REAP_CHROMIUM_MAX_AGE_SECONDS,
# HARNESS_RUNAWAY_CPU_PCT, HARNESS_RUNAWAY_MIN_AGE_SECONDS — previously
# facade variables with 0 consumers). The original `up` mode is NOT ported:
# bringing the stack up requires knowing the project's commands (compose file, dev
# server) — that is content the target project adds on top, not the framework.
# Fully fail-open: no docker → skips containers; no python3/conf → defaults.
set -uo pipefail
ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}"
[ -n "$ROOT" ] || ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

CONF_PY="$ROOT/.harness/lib/_tooling_conf.py"
_conf_get() {
  local val
  if command -v python3 >/dev/null 2>&1 && [ -f "$CONF_PY" ]; then
    val="$(HARNESS_PROJECT_ROOT="$ROOT" python3 "$CONF_PY" get "$1" "${2:-}" 2>/dev/null)"
    [ -n "$val" ] && { echo "$val"; return 0; }
  fi
  echo "${2:-}"
}
_conf_int() {
  local val
  if command -v python3 >/dev/null 2>&1 && [ -f "$CONF_PY" ]; then
    val="$(HARNESS_PROJECT_ROOT="$ROOT" python3 "$CONF_PY" getint "$1" "$2" 2>/dev/null)"
    [[ "$val" =~ ^-?[0-9]+$ ]] && { echo "$val"; return 0; }
  fi
  echo "$2"
}

REAP_CHROMIUM_MAX_AGE="$(_conf_int HARNESS_REAP_CHROMIUM_MAX_AGE_SECONDS 300)"
RUNAWAY_CPU_PCT="$(_conf_int HARNESS_RUNAWAY_CPU_PCT 50)"
RUNAWAY_MIN_AGE="$(_conf_int HARNESS_RUNAWAY_MIN_AGE_SECONDS 3600)"

_warn_runaway() {
  ps -eo pid=,pcpu=,etimes=,comm= 2>/dev/null | awk -v cpu="$RUNAWAY_CPU_PCT" -v age="$RUNAWAY_MIN_AGE" \
    '($2+0)>cpu && ($3+0)>age {printf "  WARN runaway: pid %s  %.0f%% CPU  %.1fh  %s (check; not reaped)\n",$1,$2,$3/3600,$4}'
}

status() {
  echo "dev-doctor status ($(date +%H:%M:%S)):"
  # 1. ports declared in the central config (0/empty = not applicable, skip)
  local key label port
  for key in HARNESS_DEV_API_PORT:API HARNESS_DEV_WEB_PORT:Web HARNESS_DEV_COLLAB_PORT:Collab HARNESS_DEV_DB_PORT:DB HARNESS_DEV_REDIS_PORT:Redis; do
    port="$(_conf_int "${key%%:*}" 0)"; label="${key##*:}"
    [ "$port" -gt 0 ] || continue
    if command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | grep -q ":$port "; then
      echo "  OK   $label :$port (port open)"
    elif (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then
      # fd open only inside the subshell — closes itself on exiting it
      echo "  OK   $label :$port (port open)"
    else
      echo "  DOWN $label :$port"
    fi
  done
  # 2. containers with the project prefix (if docker exists; otherwise skip)
  local prefix
  prefix="$(_conf_get HARNESS_DEV_CONTAINER_PREFIX "")"
  if [ -n "$prefix" ] && command -v docker >/dev/null 2>&1; then
    local names
    names="$(docker ps --filter "name=$prefix" --format '{{.Names}}\t{{.Status}}' 2>/dev/null || true)"
    if [ -n "$names" ]; then
      printf '%s\n' "$names" | sed 's/^/  OK   container /'
    else
      echo "  INFO no container with prefix '$prefix' running"
    fi
  fi
  # 3. runaway (WARN only)
  _warn_runaway
  exit 0  # status is informative — SessionStart never fails because of an incomplete stack
}

reap() {
  # Reap agent tooling leaks. NEVER ACTIVE dev servers.
  echo "dev-doctor reap:"
  local n=0 pid ppid etimes cmd
  # (a) orphaned agent tooling (PPID 1): serena/mcp/playwright-mcp.
  while read -r pid cmd; do
    ppid=$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ')
    [ "$ppid" = "1" ] || continue
    echo "  orphan tooling $pid: $(cut -c1-70 <<<"$cmd")"
    kill "$pid" 2>/dev/null; n=$((n+1))
  done < <(pgrep -af 'serena|mcp-server|chrome-devtools-mcp|playwright.*mcp' 2>/dev/null || true)
  # (b) leaked HEADLESS chromium (chromium.launch() without teardown). Matches ONLY
  #     headless (`--headless` in the args, ms-playwright path, headless_shell comm)
  #     — the dev's REAL browser never runs this way. Kills orphan (PPID 1) OR lifetime >
  #     HARNESS_REAP_CHROMIUM_MAX_AGE_SECONDS (an honest render lasts far less).
  while read -r pid ppid etimes; do
    { [ "$ppid" = "1" ] || [ "${etimes:-0}" -gt "$REAP_CHROMIUM_MAX_AGE" ]; } || continue
    echo "  chromium headless leaked $pid (${etimes}s)"
    kill -9 "$pid" 2>/dev/null; n=$((n+1))
  done < <(ps -eo pid=,ppid=,etimes=,args= 2>/dev/null | awk 'index($0,"--headless")>0 || tolower($0) ~ /ms-playwright|headless_shell/ {print $1,$2,$3}')
  echo "  $n process(es) reaped"
  # (c) runaway WARN (does NOT kill — it may be an active service, e.g. dev server with reload).
  _warn_runaway
  exit 0
}

case "${1:-status}" in
  status) status ;;
  reap) reap ;;
  *) echo "usage: $0 [status|reap]" >&2; exit 64 ;;
esac
