#!/usr/bin/env bash
# test_ds_pairs_oklch.sh — regressão de A6.1 (auditoria adversarial
# pós-v1.0.0, H2 hardening): um par de cores definido em OKLCH (o formato
# que o AGENTS.md deste repo recomenda via TweakCN) com contraste ~zero
# virava SKIP silencioso em ds-pairs-check.py e o resumo dizia "CONTRATO OK
# em todos os pares" mesmo assim. Prova, contra o script RENDERIZADO via
# `copier copy --vcs-ref HEAD` (nunca contra o arquivo em templates/ direto —
# aqui não há Jinja no arquivo, mas a convenção do repo é sempre testar o
# artefato instalável real):
#   1. um par OKLCH de contraste baixo é PEGO como VIOLA (não SKIP+OK).
#   2. um par OKLCH de contraste alto passa OK de verdade (conversão correta,
#      não só "não creditar falso positivo").
#   3. um formato REALMENTE não-resolvível (rgba translúcido) ainda reporta
#      "NAO AVALIADOS" no resumo -- nunca "OK em todos os pares" -- e sai
#      com código != 0 (nunca verde falso).
#
# Requer `uvx`. Roda fora do orions-belt (fixture em $TMPDIR).
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"

FAIL=0
WORK="$(mktemp -d /tmp/ds-pairs-oklch.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

assert() {
  if eval "$2"; then
    echo "PASS: $1"
  else
    echo "FAIL: $1"
    FAIL=1
  fi
}

if ! command -v uvx >/dev/null 2>&1; then
  echo "SKIP: uvx indisponível — não é possível provar o fluxo real do copier"
  exit 77  # convencao SKIP (README.md #H4): nao e PASS
fi

BASE="$WORK/base"
mkdir -p "$BASE"
RENDER_LOG="$WORK/copier.log"
if ! uvx copier copy "$REPO_ROOT" "$BASE" --vcs-ref HEAD \
    --data project_name=dspairs-fixture --data owner_name=Tester \
    --data use_ds_gate=true \
    --defaults --trust -q > "$RENDER_LOG" 2>&1; then
  echo "FAIL: copier copy --vcs-ref HEAD falhou -- $(tail -10 "$RENDER_LOG")"
  exit 1
fi
CHECK="$BASE/.harness/lib/ds-pairs-check.py"
assert "render produziu .harness/lib/ds-pairs-check.py" '[ -f "$CHECK" ]'

# --- 1. par OKLCH de contraste BAIXO -- deve VIOLAR, não SKIP+OK ---
LOW="$WORK/low-contrast"
mkdir -p "$LOW/styles"
cat > "$LOW/styles/globals.css" <<'EOF'
:root {
  --background: #ffffff;
  --primary: oklch(0.6 0.02 250);
  --primary-foreground: oklch(0.62 0.02 250);
}
.dark {
  --background: #000000;
}
EOF
OUT_LOW=$(HARNESS_PROJECT_ROOT="$LOW" HARNESS_WEB_APP_DIR=. python3 "$CHECK" 2>&1)
LOW_EXIT=$?
assert "OKLCH contraste baixo: exit != 0 (violação real, não SKIP)" '[ "$LOW_EXIT" -ne 0 ]'
assert "OKLCH contraste baixo: aparece como VIOLA (não SKIP) na saída" \
  'echo "$OUT_LOW" | grep -q "primary.*VIOLA\|VIOLA.*primary"'
assert "OKLCH contraste baixo: resumo NÃO diz 'OK em todos os pares'" \
  '! echo "$OUT_LOW" | grep -q "OK em todos os pares"'

# --- 2. par OKLCH de contraste ALTO (branco puro sobre tom saturado) -- OK real ---
HIGH="$WORK/high-contrast"
mkdir -p "$HIGH/styles"
cat > "$HIGH/styles/globals.css" <<'EOF'
:root {
  --background: #ffffff;
  --primary: oklch(0.5 0.2 25);
  --primary-foreground: oklch(1 0 0);
}
.dark {
  --background: #000000;
}
EOF
OUT_HIGH=$(HARNESS_PROJECT_ROOT="$HIGH" HARNESS_WEB_APP_DIR=. python3 "$CHECK" 2>&1)
HIGH_EXIT=$?
assert "OKLCH contraste alto (branco puro sobre tom saturado): exit 0" '[ "$HIGH_EXIT" -eq 0 ]'
assert "OKLCH contraste alto: resumo diz 'OK em todos os pares'" \
  'echo "$OUT_HIGH" | grep -q "OK em todos os pares"'
assert "oklch(1 0 0) resolveu para branco de verdade (#ffffff na linha do par)" \
  'echo "$OUT_HIGH" | grep -q "#ffffff"'

# --- 3. formato REALMENTE não-resolvível (rgba translúcido) -- SKIP honesto ---
SKIP="$WORK/real-skip"
mkdir -p "$SKIP/styles"
cat > "$SKIP/styles/globals.css" <<'EOF'
:root {
  --background: #ffffff;
  --primary: rgba(10, 20, 30, 0.4);
  --primary-foreground: #ffffff;
}
.dark {
  --background: #000000;
}
EOF
OUT_SKIP=$(HARNESS_PROJECT_ROOT="$SKIP" HARNESS_WEB_APP_DIR=. python3 "$CHECK" 2>&1)
SKIP_EXIT=$?
assert "rgba translúcido (real-não-resolvível): exit != 0 (nunca verde falso)" '[ "$SKIP_EXIT" -ne 0 ]'
assert "rgba translúcido: resumo reporta 'NAO AVALIADOS', nunca 'OK em todos os pares'" \
  'echo "$OUT_SKIP" | grep -qi "NAO AVALIADOS" && ! echo "$OUT_SKIP" | grep -q "OK em todos os pares"'

echo
echo "=== resumo ==="
if [ "$FAIL" -eq 0 ]; then
  echo "A6.1 (OKLCH) FECHADO: par de contraste baixo é pego, resumo nunca mente 'OK'."
else
  echo "AINDA HÁ GAP — ver FAILs acima."
fi
exit $FAIL
