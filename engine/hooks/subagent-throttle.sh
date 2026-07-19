#!/usr/bin/env bash
# subagent-throttle — PreToolUse (Task|Agent). Cap CONFIGURÁVEL de subagents
# simultâneos.
#
# Versão PARAMETRIZADA do hook original do learnhouse
# (/home/augusto/code/learnhouse/.claude/hooks/subagent-throttle.sh —
# CAP=6 hardcoded na Linha 11; regra do Augusto 2026-06-22: "meus tokens
# expiraram quando vc lançou 17 ao mesmo tempo. por favor lance 6 no
# maximo"). Aqui o cap e o TTL de stale-slot vêm de
# HARNESS_SUBAGENT_MAX_CONCURRENT / HARNESS_SUBAGENT_SLOT_STALE_MINUTES em
# .harness/harness.conf, lidos via engine/_tooling_conf.py — o parser ÚNICO
# do framework (docs/planning/research/01-guto-wiki.md §b: o guto-wiki
# reimplementou o mesmo load_config() 3x sem extrair; este hook não repete
# o erro chamando um parser bash paralelo).
#
# Fail-open: se python3 ou _tooling_conf.py estiverem indisponíveis, ou o
# projeto-alvo não tiver .harness/harness.conf, cai nos defaults originais
# (CAP=6 / STALE=45min) — o comportamento nunca regride para "sem throttle".
#
# Slots = arquivos em $HARNESS_RUNS_DIR/.slots (default ".harness/runs" —
# M-ALTA/H4, auditoria adversarial: era hardcoded ".claude/runs" mesmo este
# hook rodando também no Codex via .codex/hooks.json (H3/A1), o que
# instruiria um projeto codex-only a criar uma pasta ".claude" que não faz
# sentido nele. Passou a ler HARNESS_RUNS_DIR como CAP/STALE_MIN já liam.
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
THROTTLE: $COUNT/$CAP subagents já em voo — não lance mais agora (cap configurado via HARNESS_SUBAGENT_MAX_CONCURRENT em .harness/harness.conf; origem da regra: Augusto 2026-06-22, 17 paralelos estouraram o limite de tokens da conta).
Aguarde os ativos terminarem (as conclusões chegam como notificação) e relance em lotes de até $CAP. Se um subagent morreu sem liberar slot, ele expira sozinho em ${STALE_MIN}min.
EOF
  exit 2
fi
touch "$SLOTS/$(date +%s%N).slot"
exit 0
