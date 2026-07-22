#!/usr/bin/env bash
# dev-doctor — GENERIC health snapshot of the dev stack + reaping of agent
# tooling leaks. Usage: .harness/hooks/dev-doctor.sh [status|reap]
#   status : open HARNESS_DEV_*_PORT ports + containers with the
#            HARNESS_DEV_CONTAINER_PREFIX prefix running (if docker exists) + WARN
#            for a runaway process. Informative, always exit 0 (SessionStart
#            must never fail because of an incomplete stack).
#   reap   : terminates only agent-tooling PIDs explicitly registered by this
#            project and whose live cwd/start-time still prove ownership;
#            WARN for unowned/invalid entries and runaway processes.
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
PID_REGISTRY_DIR="$(_conf_get HARNESS_PID_REGISTRY_DIR .harness/pids)"

_pid_start_token() {
  local stat_value rest started
  if [ -r "/proc/$1/stat" ]; then
    stat_value="$(<"/proc/$1/stat")"
    rest="${stat_value##*) }"
    awk '{print $20}' <<<"$rest"
    return
  fi
  started="$(LC_ALL=C ps -p "$1" -o lstart= 2>/dev/null | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
  [ -n "$started" ] || return 1
  printf '%s\n' "$started" | cksum | awk '{print $1}'
}

_pid_cwd() {
  local pid="$1"
  if [ -e "/proc/$pid/cwd" ]; then
    readlink -f "/proc/$pid/cwd" 2>/dev/null
  elif command -v lsof >/dev/null 2>&1; then
    lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p'
  fi
}

_pid_command() {
  local pid="$1"
  if [ -r "/proc/$pid/cmdline" ]; then
    tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null
  else
    LC_ALL=C ps -ww -p "$pid" -o command= 2>/dev/null
  fi
}

_warn_runaway() {
  ps -eo pid=,pcpu=,etime=,comm= 2>/dev/null | awk -v cpu="$RUNAWAY_CPU_PCT" -v min_age="$RUNAWAY_MIN_AGE" '
    function seconds(value, days, fields, parts, split_day) {
      days = 0
      if (index(value, "-") > 0) {
        split(value, split_day, "-")
        days = split_day[1] + 0
        value = split_day[2]
      }
      fields = split(value, parts, ":")
      if (fields == 3) return days * 86400 + parts[1] * 3600 + parts[2] * 60 + parts[3]
      if (fields == 2) return days * 86400 + parts[1] * 60 + parts[2]
      return days * 86400 + parts[1]
    }
    { elapsed = seconds($3) }
    ($2+0)>cpu && elapsed>min_age {
      printf "  WARN runaway: pid %s  %.0f%% CPU  %.1fh  %s (check; not reaped)\n",$1,$2,elapsed/3600,$4
    }'
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
  # Ownership contract: launchers that want automatic cleanup create one
  # `$PID_REGISTRY_DIR/<name>.pid` containing
  # `<pid> <start_token> <reap_after_epoch>`, where start_token is the numeric
  # token printed by `dev-doctor.sh pid-token <pid>` (Linux: /proc start ticks;
  # macOS: checksum of the ps start time). The explicit lease is also required:
  # registration
  # proves ownership, not abandonment, so a still-valid lease must survive a
  # Stop hook. A PID alone is insufficient because of reuse/cross-project risk.
  echo "dev-doctor reap:"
  local n=0 pid recorded_start reap_after now actual_start proc_cwd cmd registry_real root_real
  root_real="$(cd "$ROOT" 2>/dev/null && pwd -P)" || {
    echo "  WARN project root is not resolvable; no process reaped"
    echo "  0 process(es) reaped"
    exit 0
  }
  case "$PID_REGISTRY_DIR" in
    /*) registry_real="$PID_REGISTRY_DIR" ;;
    *) registry_real="$root_real/$PID_REGISTRY_DIR" ;;
  esac
  if [ ! -d "$registry_real" ]; then
    echo "  WARN no project PID registry at $PID_REGISTRY_DIR; no process reaped"
    echo "  0 process(es) reaped"
    _warn_runaway
    exit 0
  fi
  registry_real="$(cd "$registry_real" 2>/dev/null && pwd -P)" || registry_real=""
  case "$registry_real/" in
    "$root_real/"*) ;;
    *)
      echo "  WARN PID registry resolves outside the project; no process reaped"
      echo "  0 process(es) reaped"
      _warn_runaway
      exit 0
      ;;
  esac

  shopt -s nullglob
  local entries=("$registry_real"/*.pid)
  if [ "${#entries[@]}" -eq 0 ]; then
    echo "  WARN PID registry is empty; no process reaped"
  fi
  local entry
  for entry in "${entries[@]}"; do
    if [ ! -f "$entry" ] || [ -L "$entry" ]; then
      echo "  WARN unsafe PID registry entry: ${entry##*/}"
      continue
    fi
    read -r pid recorded_start reap_after _ < "$entry" || true
    if ! [[ "${pid:-}" =~ ^[0-9]+$ && "${recorded_start:-}" =~ ^[0-9]+$ && "${reap_after:-}" =~ ^[0-9]+$ ]]; then
      echo "  WARN invalid PID registry entry: ${entry##*/}"
      continue
    fi
    now="$(date +%s)"
    if [ "$now" -lt "$reap_after" ]; then
      echo "  WARN PID $pid ownership lease is still active; no process reaped"
      continue
    fi
    kill -0 "$pid" 2>/dev/null || { echo "  WARN stale PID registry entry: ${entry##*/}"; continue; }
    actual_start="$(_pid_start_token "$pid" || true)"
    [ -n "$actual_start" ] || { echo "  WARN cannot read PID start time for $pid; no process reaped"; continue; }
    if [ "$actual_start" != "$recorded_start" ]; then
      echo "  WARN PID start-time mismatch for $pid; no process reaped"
      continue
    fi
    proc_cwd="$(_pid_cwd "$pid" || true)"
    case "$proc_cwd/" in
      "$root_real/"*) ;;
      *) echo "  WARN PID $pid cwd is outside the project; no process reaped"; continue ;;
    esac
    cmd="$(_pid_command "$pid" || true)"
    if ! grep -Eiq 'serena|mcp-server|chrome-devtools-mcp|playwright.*mcp|--headless|ms-playwright|headless_shell' <<<"$cmd"; then
      echo "  WARN PID $pid is not recognized agent tooling; no process reaped"
      continue
    fi
    if kill "$pid" 2>/dev/null; then
      echo "  owned tooling $pid reaped: $(cut -c1-70 <<<"$cmd")"
      unlink -- "$entry" 2>/dev/null || true
      n=$((n+1))
    else
      echo "  WARN failed to terminate owned PID $pid"
    fi
  done
  echo "  $n process(es) reaped"
  # Runaway WARN does NOT kill — it may be an active service/dev server.
  _warn_runaway
  exit 0
}

case "${1:-status}" in
  status) status ;;
  reap) reap ;;
  pid-token)
    [[ "${2:-}" =~ ^[0-9]+$ ]] || { echo "usage: $0 pid-token <pid>" >&2; exit 64; }
    _pid_start_token "$2" || exit 1
    ;;
  *) echo "usage: $0 [status|reap|pid-token <pid>]" >&2; exit 64 ;;
esac
