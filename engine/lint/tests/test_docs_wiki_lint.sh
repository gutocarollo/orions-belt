#!/usr/bin/env bash
# test_docs_wiki_lint.sh — prova F1 (Parte A): roda engine/lint/docs_wiki_lint.py
# em 3 cenários e confirma o exit code esperado em cada um.
#
# 1. Smoke real: contra o docs/ do PRÓPRIO agent-harness (HARNESS_PROJECT_ROOT
#    default = raiz git real) — deve dar OK (docs/log.md cobre planning/*).
# 2. Fixture limpa (clean-docs/): citação individual + coleção — deve dar OK.
# 3. Fixture quebrada (broken-docs/): orphan.md deliberadamente sem menção —
#    deve dar FAIL e citar exatamente esse arquivo.
#
# Uso: bash engine/lint/tests/test_docs_wiki_lint.sh
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LINT_DIR="$(cd "$HERE/.." && pwd)"
ENGINE_DIR="$(cd "$LINT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$ENGINE_DIR/.." && pwd)"
LINT="$LINT_DIR/docs_wiki_lint.py"
FAIL=0

assert_exit() {
  # $1 = descrição, $2 = exit obtido, $3 = exit esperado
  if [ "$2" -eq "$3" ]; then
    echo "PASS: $1 (exit=$2)"
  else
    echo "FAIL: $1 (esperado exit=$3, obtido exit=$2)"
    FAIL=1
  fi
}

echo "=== Cenário 1: smoke real contra docs/ do próprio agent-harness ==="
HARNESS_PROJECT_ROOT="$REPO_ROOT" python3 "$LINT" >/tmp/lint-out-$$ 2>&1
rc=$?
assert_exit "docs/ real do agent-harness deve passar (docs/log.md cobre planning/)" "$rc" 0
cat /tmp/lint-out-$$

echo
echo "=== Cenário 2: fixture limpa (clean-docs/) ==="
HARNESS_PROJECT_ROOT="$HERE/fixtures/clean-docs" python3 "$LINT" >/tmp/lint-out-$$ 2>&1
rc=$?
assert_exit "clean-docs deve passar (a.md citado, collection/ coberta)" "$rc" 0

echo
echo "=== Cenário 3: fixture quebrada (broken-docs/) — orphan.md proposital ==="
HARNESS_PROJECT_ROOT="$HERE/fixtures/broken-docs" python3 "$LINT" >/tmp/lint-out-$$ 2>&1
rc=$?
assert_exit "broken-docs deve FALHAR (orphan.md sem menção)" "$rc" 1
if grep -q "orphan.md" /tmp/lint-out-$$; then
  echo "PASS: saída cita orphan.md como órfão"
else
  echo "FAIL: saída não cita orphan.md — $(cat /tmp/lint-out-$$)"
  FAIL=1
fi

rm -f /tmp/lint-out-$$

echo
if [ "$FAIL" -eq 0 ]; then
  echo "RESULTADO: TODOS OS CENÁRIOS PASSARAM"
  exit 0
else
  echo "RESULTADO: HÁ FALHAS — ver linhas FAIL acima"
  exit 1
fi
