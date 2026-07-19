#!/usr/bin/env bash
# test_check_platform.sh — regressão do M3 (auditoria adversarial H4):
# "portátil" era um adjetivo não-declarado em lugar nenhum -- os hooks
# dependem de Bash>=4, GNU coreutils (stat -c, date +%s%N), flock e python3;
# em macOS/containers mínimos parte dos gates falha ou vira no-op silencioso.
#
# Prova aqui: (a) `.harness/lib/check-platform.sh` existe no render (dir
# neutro, incondicional -- mesmo grupo de scan_project.py/merge_docs.py);
# (b) rodando com o PATH real (todas as deps presentes neste CI/dev-box),
# sai 0; (c) rodando com uma dependência REALMENTE ausente simulada (PATH
# minimalista sem `flock`), detecta e reporta "FALTA flock" e sai != 0 --
# não é um relatório cosmético, o preflight de fato PEGA a ausência.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"

FAIL=0
assert() {
  if eval "$2"; then echo "PASS: $1"; else echo "FAIL: $1"; FAIL=1; fi
}

SCRIPT="$REPO_ROOT/templates/.harness/lib/check-platform.sh"
assert "check-platform.sh existe na árvore de templates (dir neutro)" '[ -f "$SCRIPT" ]'
assert "check-platform.sh é executável ou pelo menos legível por bash" '[ -r "$SCRIPT" ]'

# --- (b) ambiente real (todas as deps presentes) -> exit 0 ---
REAL_OUT="$(bash "$SCRIPT" 2>&1)"
REAL_EXIT=$?
assert "com PATH real (todas as deps), check-platform.sh sai 0" '[ "$REAL_EXIT" -eq 0 ]'
assert "com PATH real, reporta OK para flock" 'echo "$REAL_OUT" | grep -q "OK.*flock"'

# --- (c) simula dependência REALMENTE ausente: PATH minimalista sem flock ---
FAKEBIN="$(mktemp -d /tmp/check-platform-fakebin.XXXXXX)"
trap 'rm -rf "$FAKEBIN"' EXIT
for b in bash cat sed awk mkdir rm mktemp uname date stat python3 grep; do
  real="$(command -v "$b" 2>/dev/null || true)"
  [ -n "$real" ] && ln -sf "$real" "$FAKEBIN/$b"
done
# flock e timeout DELIBERADAMENTE ausentes deste PATH minimalista

FAKE_OUT="$(PATH="$FAKEBIN" bash "$SCRIPT" 2>&1)"
FAKE_EXIT=$?
assert "com flock ausente do PATH, check-platform.sh detecta e reporta 'FALTA flock'" \
  'echo "$FAKE_OUT" | grep -q "FALTA.*flock"'
assert "com dependência obrigatória ausente, exit code != 0 (não passa por verde)" \
  '[ "$FAKE_EXIT" -ne 0 ]'
assert "aviso de timeout ausente também aparece (dependência soft)" \
  'echo "$FAKE_OUT" | grep -q "AVISO.*timeout"'

echo
echo "=== resumo ==="
if [ "$FAIL" -eq 0 ]; then
  echo "M3 (preflight de plataforma) PROVADO — detecta dependência real ausente, não é cosmético."
else
  echo "AINDA HÁ GAP ABERTO — ver FAILs acima."
fi
exit $FAIL
