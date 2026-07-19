#!/usr/bin/env bash
# Stop hook — reapa leaks de tooling de agente ao fim de cada turno, para não
# acumular (chromium headless vazado de scripts Playwright raw sem teardown,
# MCP servers órfãos etc.). Delega para o modo `reap` do dev-doctor genérico.
#
# NÃO-BLOQUEANTE (exit 0 sempre) e SILENCIOSO quando não há nada a reapar — só
# fala se matou algo. Não toca em servidores dev ATIVOS.
#
# MATERIALIZAÇÃO (F9-fixes): apontava para `scripts/dev-doctor.sh` (script que
# o framework nunca instalou — referência morta em todo projeto-alvo); agora
# aponta para `.harness/hooks/dev-doctor.sh`, o dev-doctor genérico que SHIPPA
# junto (caps de reap vêm de HARNESS_REAP_CHROMIUM_MAX_AGE_SECONDS etc. na
# config central).
set -uo pipefail
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
out="$(bash "$ROOT/.harness/hooks/dev-doctor.sh" reap 2>/dev/null || true)"
n=$(printf '%s\n' "$out" | sed -n 's/.* \([0-9]\{1,\}\) processo(s) reapados/\1/p')
# Fala SÓ quando reapou algo (n>0). O WARN de runaway (processo persistente)
# sai no SessionStart (dev-doctor status), 1x/sessão — não spamma todo turno.
if [ "${n:-0}" -gt 0 ]; then
  echo "reap-leaks: $n processo(s) reapado(s) neste turno"
  printf '%s\n' "$out" | grep -E 'leaked|órfão tooling|reapados' | sed 's/^/  /'
fi
exit 0
