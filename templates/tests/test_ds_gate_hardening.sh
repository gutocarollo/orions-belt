#!/usr/bin/env bash
# test_ds_gate_hardening.sh — regressão de A6.2 e A6.3 (auditoria adversarial
# pós-v1.0.0, H2 hardening):
#   A6.2 — `.ds-baseline.txt` nunca era gerada em nenhum passo de instalação,
#     então o ratchet ds-gate.sh ficava permanentemente em modo --report
#     (nunca falha, mesmo com hardcode óbvio). Fix: `harness-install.sh`
#     gera a baseline automaticamente na 1ª instalação quando use_ds_gate
#     estava ativo.
#   A6.3 — `.ds-allowlist` prometia globs mas casava por substring literal
#     (`grep -vF`) — um padrão como `legacy/**` nunca casava nenhum path
#     real. Fix: `.harness/lib/ds_allowlist_filter.py` (fnmatch real).
#
# Requer `uvx`. Roda fora do orions-belt (fixture em $TMPDIR).
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
INSTALLER="$REPO_ROOT/harness-install.sh"

FAIL=0
WORK="$(mktemp -d /tmp/ds-gate-hardening.XXXXXX)"
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

# =============================================================================
# A6.2 — harness-install.sh gera .ds-baseline.txt automaticamente
# =============================================================================
TARGET="$WORK/target-project"
mkdir -p "$TARGET/components"
cd "$TARGET"
git init -q
git config user.email "test@example.com"
git config user.name "Test"
# 1 violação REAL já presente ANTES da instalação -- a baseline deve capturar
# essa contagem (não zero), provando que ela reflete o estado ATUAL do
# projeto-alvo, não um valor chutado.
cat > components/legacy.tsx <<'EOF'
export const Legacy = () => <div className="text-gray-600" />
EOF
git add -A && git commit -qm "fixture pré-existente com 1 hardcode real" >/dev/null

INSTALL_LOG="$WORK/install.log"
if ! "$INSTALLER" "$TARGET" --vcs-ref HEAD \
    --data project_name=dsgate-fixture --data owner_name=Tester \
    --data use_ds_gate=true --data harness_web_app_dir=. \
    --defaults > "$INSTALL_LOG" 2>&1; then
  echo "FAIL: harness-install.sh falhou -- $(tail -20 "$INSTALL_LOG")"
  cat "$INSTALL_LOG"
  exit 1
fi

assert "harness-install.sh materializou .harness/lib/ds-gate.sh" '[ -f "$TARGET/.harness/lib/ds-gate.sh" ]'
assert "harness-install.sh materializou o hook ds-gate-posttool.sh (use_ds_gate=true)" \
  '[ -f "$TARGET/.harness/hooks/ds-gate-posttool.sh" ]'
assert "A6.2: .ds-baseline.txt foi GERADA automaticamente pela 1ª instalação" \
  '[ -f "$TARGET/.ds-baseline.txt" ]'
assert "A6.2: baseline reflete a violação REAL pré-existente (color-gray=1), não zero chutado" \
  'grep -q "^color-gray=1$" "$TARGET/.ds-baseline.txt"'

# prova que o ratchet agora ENFORCE de verdade: nova violação DEPOIS da
# baseline deve fazer o gate FALHAR (antes desta correção, sem baseline,
# `check` nunca falhava -- sempre report-only).
cat > "$TARGET/components/new-hardcode.tsx" <<'EOF'
export const New = () => <div className="text-gray-700 bg-red-500" />
EOF
if HARNESS_PROJECT_ROOT="$TARGET" bash "$TARGET/.harness/lib/ds-gate.sh" --dir . check \
   > "$WORK/ds-gate-check.out" 2>&1; then
  DS_GATE_EXIT=0
else
  DS_GATE_EXIT=$?
fi
assert "A6.2: com baseline existente, novo hardcode FAZ o ratchet falhar (exit != 0)" \
  '[ "$DS_GATE_EXIT" -ne 0 ]'
assert "A6.2: mensagem reporta SUBIU para a dimensão violada" \
  'grep -q "SUBIU" "$WORK/ds-gate-check.out"'

# =============================================================================
# A6.3 — .ds-allowlist casa por GLOB real (fnmatch), não substring literal
# =============================================================================
GLOB_DIR="$WORK/glob-fixture"
mkdir -p "$GLOB_DIR/legacy" "$GLOB_DIR/fresh"
cat > "$GLOB_DIR/legacy/old.tsx" <<'EOF'
export const X = () => <div className="text-gray-500" />
EOF
cat > "$GLOB_DIR/fresh/new.tsx" <<'EOF'
export const Y = () => <div className="text-gray-600" />
EOF
cat > "$GLOB_DIR/.ds-allowlist" <<'EOF'
legacy/**
EOF
OUT_GLOB=$(HARNESS_PROJECT_ROOT="$GLOB_DIR" bash "$TARGET/.harness/lib/ds-gate.sh" --dir . --report 2>&1)
assert "A6.3: com allowlist 'legacy/**', só fresh/new.tsx conta (color-gray=1, não 2)" \
  'echo "$OUT_GLOB" | grep -qE "^color-gray +1 "'

rm "$GLOB_DIR/.ds-allowlist"
OUT_NOGLOB=$(HARNESS_PROJECT_ROOT="$GLOB_DIR" bash "$TARGET/.harness/lib/ds-gate.sh" --dir . --report 2>&1)
assert "A6.3 (controle): sem allowlist, os dois arquivos contam (color-gray=2)" \
  'echo "$OUT_NOGLOB" | grep -qE "^color-gray +2 "'

echo
echo "=== resumo ==="
if [ "$FAIL" -eq 0 ]; then
  echo "A6.2 (baseline auto-gerada) e A6.3 (glob real) FECHADOS."
else
  echo "AINDA HÁ GAP — ver FAILs acima."
fi
exit $FAIL
