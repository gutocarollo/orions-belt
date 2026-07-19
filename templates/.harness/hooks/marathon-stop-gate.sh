#!/usr/bin/env bash
# marathon-stop-gate — Stop hook. Inerte sem maratona ativa.
# Com $RUNS_DIR/ACTIVE + itens abertos no RUN.md: bloqueia a parada e
# devolve a "Próxima ação". Anti-prisão: N bloqueios consecutivos SEM o RUN.md
# mudar → libera com aviso (progresso real zera os strikes).
#
# MATERIALIZAÇÃO (F9-fixes): diretório de runs (HARNESS_RUNS_DIR, default
# .harness/runs) e o cap de strikes (HARNESS_MARATHON_MAX_BLOCKS_WITHOUT_PROGRESS,
# default 3) vêm de .harness/harness.conf via .harness/lib/_tooling_conf.py —
# eram hardcoded (as 2 chaves existiam no schema desde F0 sem nenhum consumidor).
# Default de HARNESS_RUNS_DIR mudou de ".claude/runs" para ".harness/runs"
# em M-ALTA/H4 (auditoria adversarial pós-H3, gap simétrico) — o valor
# antigo carregava "claude" mesmo em projetos codex-only; ".harness/" já é
# o diretório neutro/runtime-agnóstico do resto do framework
# (harness.conf, answers.yml, hooks, lib). Projetos JÁ instalados mantêm o
# valor gravado no answers.yml deles (Copier não reescreve resposta já
# dada — só o default para instalações NOVAS muda).
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
[ "$OPEN" -eq 0 ] && exit 0   # checklist zerado — parada legítima

# AGUARDANDO decisão do usuário = parada legítima
NEXT=$(awk '/^## Próxima ação/{getline; while($0 ~ /^\s*$/) getline; print; exit}' "$RUN")
case "$NEXT" in AGUARDANDO:*) exit 0 ;; esac

# N strikes sem progresso → libera
STRIKES="$ROOT/$RUNS_DIR/$SLUG/.stop-strikes"
MTIME=$(stat -c %Y "$RUN" 2>/dev/null || echo 0)
read -r COUNT LAST < <(cat "$STRIKES" 2>/dev/null || echo "0 0")
[ "$MTIME" != "$LAST" ] && COUNT=0   # RUN.md mudou desde o último strike = progresso
if [ "$COUNT" -ge "$MAX_STRIKES" ]; then
  rm -f "$STRIKES"
  echo '{"systemMessage":"marathon-stop-gate: '"$MAX_STRIKES"' bloqueios sem progresso no RUN.md — liberando a parada. Maratona segue ATIVA ('"$SLUG"'); retome com a skill marathon ou encerre com rm '"$RUNS_DIR"'/ACTIVE."}'
  exit 0
fi
echo "$((COUNT + 1)) $MTIME" > "$STRIKES"

cat >&2 <<EOF
MARATHON ATIVA ($SLUG): $OPEN item(ns) abertos no checklist — a parada foi bloqueada.
Próxima ação registrada: ${NEXT:-"(vazia — atualize o RUN.md)"}
Continue executando (skill marathon §2: fechar item → marcar [x] → atualizar Próxima ação).
Se está genuinamente bloqueado em decisão do usuário: escreva "AGUARDANDO: <pergunta>" na seção Próxima ação e pare.
Encerrar a maratona de vez: rm $RUNS_DIR/ACTIVE
EOF
exit 2
