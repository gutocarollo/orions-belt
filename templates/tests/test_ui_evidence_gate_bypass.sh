#!/usr/bin/env bash
# test_ui_evidence_gate_bypass.sh — regressão dos 4 bypasses de A5 (auditoria
# adversarial pós-v1.0.0, H2 hardening) contra o Stop hook ui-evidence-gate.sh
# e o motor scripts/ui-evidence.sh, RENDERIZADOS de verdade via `copier copy
# --vcs-ref HEAD` (nunca lógica reimplementada em prosa — mesmo princípio dos
# irmãos test_harness_install_brownfield_e2e.sh/test_copier_update_e2e.sh).
#
# Os 4 bypasses, cada um provado FECHADO (bloqueia/falha) nesta rodada:
#   1. Manifest FORJADO (`echo '{"captures":1}' > manifest.json`, zero PNGs
#      no disco) satisfazia o gate. Fix: exige "files" com N ".png" == captures
#      E cada PNG existindo no disco.
#   2. Deleção de arquivo de UI mascarava a mudança (NEWEST=0, gate saía
#      cedo). Fix: mtime do diretório-pai (POSIX: `rm` atualiza o mtime do
#      dir) como proxy do instante da deleção.
#   3. HTTP 500 virava "1 passed" + evidência válida. Coberto por
#      test_ui_evidence_spec_error_status.sh (irmão — precisa de Playwright
#      real, por isso está separado e é SKIP-safe).
#   4. Preflight de host indisponível produzia "000000" (bug de curl `-w` +
#      `|| echo 000` duplicando saída), nunca batia no branch de erro.
#
# Requer `uvx`. Roda fora do harness-wiki (fixture em $TMPDIR).
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"

FAIL=0
WORK="$(mktemp -d /tmp/ui-evidence-gate-bypass.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

assert() {
  # $1 = descrição, $2 = expressão shell (0=pass)
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

# --- 0. Render real do template (harness_web_app_dir=".", use_ui_evidence=true) ---
BASE="$WORK/base"
mkdir -p "$BASE"
RENDER_LOG="$WORK/copier.log"
if ! uvx copier copy "$REPO_ROOT" "$BASE" --vcs-ref HEAD \
    --data project_name=uiev-fixture --data owner_name=Tester \
    --data use_ui_evidence=true \
    --defaults --trust -q > "$RENDER_LOG" 2>&1; then
  echo "FAIL: copier copy --vcs-ref HEAD falhou -- $(tail -10 "$RENDER_LOG")"
  exit 1
fi
assert "render produziu .harness/hooks/ui-evidence-gate.sh" '[ -f "$BASE/.harness/hooks/ui-evidence-gate.sh" ]'
assert "render produziu scripts/ui-evidence.sh" '[ -f "$BASE/scripts/ui-evidence.sh" ]'
assert "render produziu tests/visual/evidence.spec.ts" '[ -f "$BASE/tests/visual/evidence.spec.ts" ]'

# --- 0.1 wiring mínimo (package.json com "ui:evidence" -- ENGINE_WIRED) + 1 componente ---
mkdir -p "$BASE/components"
cat > "$BASE/components/foo.tsx" <<'EOF'
export const Foo = () => <div>foo</div>
EOF
cat > "$BASE/package.json" <<'EOF'
{"name": "uiev-fixture", "scripts": {"ui:evidence": "bash scripts/ui-evidence.sh"}}
EOF

cd "$BASE"
git init -q
git config user.email "test@example.com"
git config user.name "Test"
git add -A && git commit -qm "base fixture (harness instalado + wiring + 1 componente)" >/dev/null

# =============================================================================
# BYPASS 1 — manifest forjado (zero PNGs reais)
# =============================================================================
B1="$WORK/bypass1"
cp -r "$BASE" "$B1"
cd "$B1"
echo 'export const Foo = () => <div>foo v2</div>' > components/foo.tsx  # UI change, não commitado

mkdir -p .claude/evidence/after
echo '{"captures":1}' > .claude/evidence/after/manifest.json  # FORJADO: zero PNGs no disco
touch -d '+1 hour' .claude/evidence/after/manifest.json 2>/dev/null || touch .claude/evidence/after/manifest.json

echo '{}' | HARNESS_PROJECT_ROOT="$B1" CLAUDE_PROJECT_DIR="$B1" bash "$B1/.harness/hooks/ui-evidence-gate.sh" \
  >"$WORK/b1.out" 2>"$WORK/b1.err"
B1_EXIT=$?
assert "bypass 1 (manifest forjado sem PNGs): gate BLOQUEIA (exit 2), não passa mais silenciosamente" \
  '[ "$B1_EXIT" -eq 2 ]'

# prova que evidência REAL (PNG existente + files/captures consistentes) ainda passa
printf '\x89PNG\r\n\x1a\nfake' > .claude/evidence/after/home__default__desktop.png
cat > .claude/evidence/after/manifest.json <<'EOF'
{"label": "after", "captures": 1, "files": {"home__default__desktop.png": "abc123"}}
EOF
touch .claude/evidence/after/manifest.json
echo '{}' | HARNESS_PROJECT_ROOT="$B1" CLAUDE_PROJECT_DIR="$B1" bash "$B1/.harness/hooks/ui-evidence-gate.sh" \
  >"$WORK/b1ok.out" 2>"$WORK/b1ok.err"
B1_OK_EXIT=$?
assert "bypass 1 (controle positivo): manifest com PNG real no disco passa (exit 0)" \
  '[ "$B1_OK_EXIT" -eq 0 ]'

# =============================================================================
# BYPASS 2 — deleção mascara a mudança de UI
# =============================================================================
B2="$WORK/bypass2"
cp -r "$BASE" "$B2"
cd "$B2"

# manifest ANTIGO (antes da deleção) -- não deve satisfazer o gate depois
mkdir -p .claude/evidence/before
echo '{"captures":1,"files":{"x.png":"aaa"}}' > .claude/evidence/before/manifest.json
printf 'x' > .claude/evidence/before/x.png
touch -d '-1 hour' .claude/evidence/before/manifest.json 2>/dev/null || true

rm components/foo.tsx  # deleção, não commitada -- o bypass original

echo '{}' | HARNESS_PROJECT_ROOT="$B2" CLAUDE_PROJECT_DIR="$B2" bash "$B2/.harness/hooks/ui-evidence-gate.sh" \
  >"$WORK/b2.out" 2>"$WORK/b2.err"
B2_EXIT=$?
assert "bypass 2 (deleção de .tsx): gate BLOQUEIA (exit 2), não sai cedo com NEWEST=0" \
  '[ "$B2_EXIT" -eq 2 ]'

# prova que evidência gerada DEPOIS da deleção (mtime do manifest >= mtime do
# diretório-pai no instante da deleção) passa
mkdir -p .claude/evidence/after2
printf '\x89PNG\r\n\x1a\nfake' > .claude/evidence/after2/home.png
echo '{"captures":1,"files":{"home.png":"bbb"}}' > .claude/evidence/after2/manifest.json
echo '{}' | HARNESS_PROJECT_ROOT="$B2" CLAUDE_PROJECT_DIR="$B2" bash "$B2/.harness/hooks/ui-evidence-gate.sh" \
  >"$WORK/b2ok.out" 2>"$WORK/b2ok.err"
B2_OK_EXIT=$?
assert "bypass 2 (controle positivo): evidência real gerada APÓS a deleção passa (exit 0)" \
  '[ "$B2_OK_EXIT" -eq 0 ]'

# =============================================================================
# BYPASS 4 — preflight de host indisponível (curl "000000" vs "000")
# =============================================================================
B4="$WORK/bypass4"
cp -r "$BASE" "$B4"
cd "$B4"
DEAD_PORT=39217  # assume-se fechado; preflight tem --max-time 5 de qualquer forma

PLAYWRIGHT_WEB_URL="http://127.0.0.1:$DEAD_PORT" bash scripts/ui-evidence.sh after \
  >"$WORK/b4.out" 2>"$WORK/b4.err"
B4_EXIT=$?
assert "bypass 4 (host indisponível): ui-evidence.sh sai com erro (exit 1), preflight pega o caso" \
  '[ "$B4_EXIT" -eq 1 ]'
assert "bypass 4: stderr reporta PREFLIGHT FALHOU (mensagem clara, não geração silenciosa)" \
  'grep -q "PREFLIGHT FALHOU" "$WORK/b4.err"'
assert "bypass 4: preflight NUNCA chega a invocar playwright (sem 'ui-evidence: label=' no stdout)" \
  '! grep -q "ui-evidence: label=" "$WORK/b4.out"'

echo
echo "=== resumo ==="
if [ "$FAIL" -eq 0 ]; then
  echo "TODOS OS BYPASSES A5 (1,2,4) FECHADOS."
else
  echo "AINDA HÁ BYPASS ABERTO — ver FAILs acima."
fi
exit $FAIL
