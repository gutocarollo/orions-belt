#!/usr/bin/env bash
# test_clarification_gate.sh — prova da INVERSÃO do gate de clarificação.
#
# O DEFEITO QUE ISTO FIXA (medido 2026-08-02). O gate só conferia o bloco D[n]
# DEPOIS de reconhecer uma pergunta: `if not is_choice and not is_handoff:
# return 0` vinha ANTES da validação. Isso deixava passar o caso mais comum de
# todos — apresentar decisão de forma DECLARATIVA, sem "?" e sem as palavras
# exatas de handoff.
#
# Duas passagens reais foram medidas no histórico do dono:
#   1. um turno com "### D3", rótulos "**Bom aplicado:**"/"**Ruim aplicado:**" e
#      recomendação inline em itálico — bloco INCOMPLETO, exit 0;
#   2. o turno seguinte entregou DUAS decisões abertas sem bloco algum, exit 0.
#
# O gate era bom validando e cego detectando. Agora: bloco presente é SEMPRE
# conferido, e a detecção decide apenas o caso "não há bloco nenhum".
#
# Uso: bash engine/hooks/tests/test_clarification_gate.sh
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
GATE="$REPO/templates/.harness/hooks/{% if use_clarification_gate %}clarification-stop-gate.py{% endif %}.jinja"
[ -f "$GATE" ] || { echo "FAIL: fonte do gate não encontrada"; exit 1; }
FAIL=0

# $1 desc, $2 exit esperado, $3 texto
verifica() {
  local desc="$1" want="$2" texto="$3" got
  got=$(python3 -c '
import json,subprocess,sys
p=subprocess.run(["python3",sys.argv[1]],input=json.dumps({"last_assistant_message":sys.argv[2]}),
                 capture_output=True,text=True)
sys.stderr.write(p.stderr)
print(p.returncode)' "$GATE" "$texto" 2>/dev/null)
  if [ "$got" = "$want" ]; then echo "PASS: $desc (exit=$got)"; else echo "FAIL: $desc (queria $want, veio $got)"; FAIL=1; fi
}

echo "=== BLOQUEIA: decisão entregue de forma declarativa, sem bloco ==="
verifica "handoff 'se voce me disser'" 2 'Bloqueado em voce: D3 estado na chave ou var sob escopo. Se voce me disser a D3, eu sigo.'
verifica "handoff 'seu ato por contrato'" 2 'ACCEPTED e seu ato por contrato. A decisao D2 continua aberta.'
verifica "handoff 'depende da sua escolha'" 2 'A migracao depende da sua escolha entre as opcoes A e B da decisao D4.'

echo
echo "=== BLOQUEIA: bloco D[n] existe mas está incompleto (a inversão) ==="
verifica "bloco sem recomendacao" 2 '### D9 — qual caminho

**Canon:** SILENTE.
**Opcao A — x**
- **Comportamento:** faz x.
- **Bom aplicado:** no arquivo a.jsx vira y.
- **Ruim aplicado:** quebra z.
- **Quando escolher:** se prioridade e x.'

echo
echo "=== PASSA: nada de decisão em jogo ==="
verifica "relatorio puro" 0 'Suite 342 testes, 341 pass. Commitei em ac38154.'
verifica "decisao JA fechada, narrada" 0 'D1 foi decidido pelo dono: classe curta sob --color-*.'
verifica "opcao citada em retrospectiva" 0 'A Opcao A que eu propus estava errada; troquei e segui.'
verifica "pergunta retorica respondida" 0 'Por que falhou? Porque o export avaliava na carga do modulo.'

echo
echo "=== PASSA: bloco D[n] completo (rótulos invertidos aceitos) ==="
verifica "bloco completo" 0 '### D5 — onde o manifesto vive

**Canon:** SILENTE.
**Evidencia:** run root sem evidence-manifest.

**Opcao A — symlink**
- **Comportamento:** link no run root.
- **Bom aplicado:** os 376 pngPath resolvem.
- **Ruim aplicado:** link quebra se mover.
- **Quando escolher:** se a evidencia fica no alvo.

**Opcao B — copiar**
- **Comportamento:** copia com caminho reescrito.
- **Bom aplicado:** run root auto-contido.
- **Ruim aplicado:** duas copias divergem.
- **Quando escolher:** se o run root viaja sozinho.

**Minha recomendacao:** Opcao A, porque o pngPath e relativo ao manifesto de proposito.'

echo
if [ "$FAIL" -eq 0 ]; then echo "RESULT: ALL SCENARIOS PASSED"; exit 0; else echo "RESULT: THERE ARE FAILURES"; exit 1; fi
