#!/usr/bin/env bash
# test_subagent_throttle.sh — prova de ponta-a-ponta do F0 (config central):
# roda engine/hooks/subagent-throttle.sh N vezes contra o fixture em
# fixture-project/.harness/harness.conf e confirma que ele respeita
# HARNESS_SUBAGENT_MAX_CONCURRENT do .conf, NÃO o CAP=6 hardcoded do hook
# original do learnhouse. Depois muda o .conf para 3 e prova que o hook
# passa a respeitar 3 — provando leitura DINÂMICA, não valor congelado no
# processo.
#
# Uso: bash engine/hooks/tests/test_subagent_throttle.sh
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOKS_DIR="$(cd "$HERE/.." && pwd)"
HOOK="$HOOKS_DIR/subagent-throttle.sh"
FIXTURE="$HERE/fixture-project"
CONF="$FIXTURE/.harness/harness.conf"
# M-ALTA/H4: HARNESS_RUNS_DIR default mudou de ".claude/runs" para
# ".harness/runs" (neutro) -- reset_slots() remove só o subdiretório
# runs/, NUNCA ".harness" inteiro (é onde harness.conf mora).
SLOTS_DIR="$FIXTURE/.harness/runs/.slots"

FAIL=0

reset_slots() {
  rm -rf "$FIXTURE/.harness/runs"
}

set_cap() {
  # $1 = novo valor de HARNESS_SUBAGENT_MAX_CONCURRENT
  cat > "$CONF" <<EOF
# fixture de teste — NÃO é config real de projeto, só prova F0.
PROJECT_NAME=fixture-project
HARNESS_SUBAGENT_MAX_CONCURRENT=$1
HARNESS_SUBAGENT_SLOT_STALE_MINUTES=45
EOF
}

run_hook() {
  CLAUDE_PROJECT_DIR="$FIXTURE" bash "$HOOK"
}

assert_exit() {
  # $1 = descrição, $2 = exit code obtido, $3 = exit code esperado
  if [ "$2" -eq "$3" ]; then
    echo "PASS: $1 (exit=$2)"
  else
    echo "FAIL: $1 (esperado exit=$3, obtido exit=$2)"
    FAIL=1
  fi
}

echo "=== Cenário 1: HARNESS_SUBAGENT_MAX_CONCURRENT=6 (valor original do fixture) ==="
set_cap 6
reset_slots
for i in 1 2 3 4 5 6; do
  run_hook >/tmp/throttle-out-$$ 2>&1
  rc=$?
  assert_exit "chamada $i/6 deve passar" "$rc" 0
done
run_hook >/tmp/throttle-out-$$ 2>&1
rc=$?
assert_exit "chamada 7 (acima do cap=6) deve ser bloqueada" "$rc" 2
grep -q "6/6" /tmp/throttle-out-$$ && echo "PASS: mensagem de throttle cita 6/6 (cap correto na mensagem)" || { echo "FAIL: mensagem de throttle não cita 6/6: $(cat /tmp/throttle-out-$$)"; FAIL=1; }

echo
echo "=== Cenário 2: muda .conf para HARNESS_SUBAGENT_MAX_CONCURRENT=3 (prova leitura dinâmica) ==="
set_cap 3
reset_slots
for i in 1 2 3; do
  run_hook >/tmp/throttle-out-$$ 2>&1
  rc=$?
  assert_exit "chamada $i/3 deve passar (cap agora é 3)" "$rc" 0
done
run_hook >/tmp/throttle-out-$$ 2>&1
rc=$?
assert_exit "chamada 4 (acima do cap=3) deve ser bloqueada" "$rc" 2
grep -q "3/3" /tmp/throttle-out-$$ && echo "PASS: mensagem de throttle cita 3/3 (cap novo refletido)" || { echo "FAIL: mensagem de throttle não cita 3/3: $(cat /tmp/throttle-out-$$)"; FAIL=1; }

echo
echo "=== Cenário 3: fail-open — sem .harness/harness.conf (renomeado), cai no default 6 ==="
mv "$CONF" "$CONF.bak"
reset_slots
for i in 1 2 3 4 5 6; do
  run_hook >/dev/null 2>&1
  rc=$?
  assert_exit "fail-open chamada $i/6 deve passar" "$rc" 0
done
run_hook >/tmp/throttle-out-$$ 2>&1
rc=$?
assert_exit "fail-open chamada 7 deve ser bloqueada no default 6" "$rc" 2
mv "$CONF.bak" "$CONF"

reset_slots
rm -f /tmp/throttle-out-$$
set_cap 6  # deixa o fixture como estava antes do teste

echo
if [ "$FAIL" -eq 0 ]; then
  echo "RESULTADO: TODOS OS CENÁRIOS PASSARAM"
  exit 0
else
  echo "RESULTADO: HÁ FALHAS — ver linhas FAIL acima"
  exit 1
fi
