#!/usr/bin/env bash
# dev-doctor — snapshot GENÉRICO de saúde da stack dev + reap de leaks de
# tooling de agente. Uso: .harness/hooks/dev-doctor.sh [status|reap]
#   status : portas HARNESS_DEV_*_PORT abertas + containers com prefixo
#            HARNESS_DEV_CONTAINER_PREFIX rodando (se docker existir) + WARN
#            de processo runaway. Informativo, exit 0 sempre (SessionStart
#            nunca deve falhar por stack incompleta).
#   reap   : mata tooling de agente órfão (PPID 1: serena/mcp/playwright-mcp)
#            e chromium HEADLESS vazado (órfão OU vida > cap configurável);
#            WARN de runaway (nunca mata — pode ser servidor ativo).
#
# MATERIALIZAÇÃO (F9-fixes): versão genérica mínima do dev-doctor do
# harness-doador de referência — a versão do doador conhecia a stack dele
# (compose file, containers nominais, healthchecks de MCP/API específicos);
# esta conhece SÓ o que a config central declara: portas, prefixo de
# container e os 3 caps de reap/runaway (HARNESS_REAP_CHROMIUM_MAX_AGE_SECONDS,
# HARNESS_RUNAWAY_CPU_PCT, HARNESS_RUNAWAY_MIN_AGE_SECONDS — antes
# variáveis-fachada com 0 consumidores). Modo `up` do original NÃO portado:
# subir a stack exige conhecer os comandos do projeto (compose file, dev
# server) — é conteúdo que o projeto-alvo adiciona por cima, não o framework.
# Fail-open total: sem docker → pula containers; sem python3/conf → defaults.
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
    '($2+0)>cpu && ($3+0)>age {printf "  WARN runaway: pid %s  %.0f%% CPU  %.1fh  %s (checar; nao reapado)\n",$1,$2,$3/3600,$4}'
}

status() {
  echo "dev-doctor status ($(date +%H:%M:%S)):"
  # 1. portas declaradas na config central (0/vazio = não aplicável, pula)
  local key label port
  for key in HARNESS_DEV_API_PORT:API HARNESS_DEV_WEB_PORT:Web HARNESS_DEV_COLLAB_PORT:Collab HARNESS_DEV_DB_PORT:DB HARNESS_DEV_REDIS_PORT:Redis; do
    port="$(_conf_int "${key%%:*}" 0)"; label="${key##*:}"
    [ "$port" -gt 0 ] || continue
    if command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | grep -q ":$port "; then
      echo "  OK   $label :$port (porta aberta)"
    elif (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then
      # fd aberto só dentro do subshell — fecha sozinho ao sair dele
      echo "  OK   $label :$port (porta aberta)"
    else
      echo "  DOWN $label :$port"
    fi
  done
  # 2. containers com o prefixo do projeto (se docker existir; senão pula)
  local prefix
  prefix="$(_conf_get HARNESS_DEV_CONTAINER_PREFIX "")"
  if [ -n "$prefix" ] && command -v docker >/dev/null 2>&1; then
    local names
    names="$(docker ps --filter "name=$prefix" --format '{{.Names}}\t{{.Status}}' 2>/dev/null || true)"
    if [ -n "$names" ]; then
      printf '%s\n' "$names" | sed 's/^/  OK   container /'
    else
      echo "  INFO nenhum container com prefixo '$prefix' rodando"
    fi
  fi
  # 3. runaway (só WARN)
  _warn_runaway
  exit 0  # status é informativo — SessionStart nunca falha por stack incompleta
}

reap() {
  # Reap de leaks de tooling de agente. NUNCA servidores dev ATIVOS.
  echo "dev-doctor reap:"
  local n=0 pid ppid etimes cmd
  # (a) tooling de agente órfão (PPID 1): serena/mcp/playwright-mcp.
  while read -r pid cmd; do
    ppid=$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ')
    [ "$ppid" = "1" ] || continue
    echo "  órfão tooling $pid: $(cut -c1-70 <<<"$cmd")"
    kill "$pid" 2>/dev/null; n=$((n+1))
  done < <(pgrep -af 'serena|mcp-server|chrome-devtools-mcp|playwright.*mcp' 2>/dev/null || true)
  # (b) chromium HEADLESS vazado (chromium.launch() sem teardown). Casa SÓ
  #     headless (`--headless` nos args, path ms-playwright, comm headless_shell)
  #     — browser REAL do dev nunca roda assim. Mata órfão (PPID 1) OU vida >
  #     HARNESS_REAP_CHROMIUM_MAX_AGE_SECONDS (render honesto dura bem menos).
  while read -r pid ppid etimes; do
    { [ "$ppid" = "1" ] || [ "${etimes:-0}" -gt "$REAP_CHROMIUM_MAX_AGE" ]; } || continue
    echo "  chromium headless leaked $pid (${etimes}s)"
    kill -9 "$pid" 2>/dev/null; n=$((n+1))
  done < <(ps -eo pid=,ppid=,etimes=,args= 2>/dev/null | awk 'index($0,"--headless")>0 || tolower($0) ~ /ms-playwright|headless_shell/ {print $1,$2,$3}')
  echo "  $n processo(s) reapados"
  # (c) WARN de runaway (NÃO mata — pode ser serviço ativo, ex. dev server com reload).
  _warn_runaway
  exit 0
}

case "${1:-status}" in
  status) status ;;
  reap) reap ;;
  *) echo "uso: $0 [status|reap]" >&2; exit 64 ;;
esac
