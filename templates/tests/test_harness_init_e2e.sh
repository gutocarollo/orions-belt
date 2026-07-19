#!/usr/bin/env bash
# test_harness_init_e2e.sh — prova de ponta-a-ponta do fluxo real do harness-init
# (F5, gate de docs/planning/00-plano-consolidado.md §6-F5): renderiza o template
# INTEIRO via copier de verdade para um scratch dir, aplica o merge não-destrutivo
# num CLAUDE.md pré-existente com 2-3 linhas REAIS, e confirma via diff que o
# conteúdo original sobreviveu intocado (append, não replace).
#
# Requer `uvx` (baixa/cacheia copier na primeira vez). Roda fora do harness-wiki
# (fixtures em $TMPDIR), nunca escreve dentro do próprio repo.
#
# Mora em templates/tests/ (excluído do copy via copier.yml `/tests`, mesma
# razão do test_council_merge.py irmão: testa a árvore de templates COMO UM
# TODO via `uvx copier copy` real — não é reusável uma vez materializado num
# projeto-alvo, ao contrário de .harness/lib/tests/{test_scan_project,
# test_merge_docs}.py, que são portáveis e SHIPPAM para o projeto-alvo.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATES_ROOT="$(cd "$HERE/.." && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
LIB="$TEMPLATES_ROOT/.harness/lib"

FAIL=0
WORK="$(mktemp -d /tmp/harness-init-e2e.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

TARGET="$WORK/target-project"
SCRATCH="$WORK/scratch-render"
mkdir -p "$TARGET"

assert() {
  # $1 = descrição, $2 = expressão shell (0=pass)
  if eval "$2"; then
    echo "PASS: $1"
  else
    echo "FAIL: $1"
    FAIL=1
  fi
}

# --- 1. Fixture: repo-alvo com CLAUDE.md PRÉ-EXISTENTE (2-3 linhas reais) ---
cd "$TARGET"
git init -q
git config user.email "test@example.com"
git config user.name "Test"
mkdir -p .claude
cat > .claude/CLAUDE.md <<'EOF'
# Regras do meu projeto real

- Nunca commitar direto na main.
- Rodar `make test` antes de qualquer PR.
EOF
git add -A && git commit -qm "init fixture com CLAUDE.md real" >/dev/null

ORIGINAL_MD5=$(md5sum .claude/CLAUDE.md | cut -d' ' -f1)

# --- 2. Render completo via copier (o que harness-init faria na Fase A) ---
if ! command -v uvx >/dev/null 2>&1; then
  echo "SKIP: uvx indisponível neste ambiente — não é possível provar o fluxo real do copier"
  exit 77  # convencao SKIP (README.md #H4): nao e PASS
fi

RENDER_LOG="$WORK/copier.log"
if ! uvx copier copy "$REPO_ROOT" "$SCRATCH" \
    --data project_name=e2e-fixture --data owner_name=Tester \
    --defaults --trust -q > "$RENDER_LOG" 2>&1; then
  echo "FAIL: copier copy falhou -- $(tail -5 "$RENDER_LOG")"
  exit 1
fi
assert "scratch render produziu .claude/CLAUDE.md" '[ -f "$SCRATCH/.claude/CLAUDE.md" ]'

# --- 3. Merge não-destrutivo (o que harness-init faria na Fase C) ---
python3 "$LIB/merge_docs.py" markdown \
  --existing "$TARGET/.claude/CLAUDE.md" \
  --new "$SCRATCH/.claude/CLAUDE.md" \
  --label "e2e-test" > "$WORK/merge-result.json"

ACTION=$(python3 -c "import json;print(json.load(open('$WORK/merge-result.json'))['action'])")
assert "merge reportou action=appended (não overwrite)" '[ "$ACTION" = "appended" ]'

# --- 4. Provas de não-destrutividade (o literal do gate) ---
assert "linha 'Nunca commitar direto na main' sobrevive verbatim" \
  'grep -q "Nunca commitar direto na main" "$TARGET/.claude/CLAUDE.md"'
assert "linha 'Rodar \`make test\`' sobrevive verbatim" \
  'grep -q "Rodar \`make test\` antes de qualquer PR" "$TARGET/.claude/CLAUDE.md"'
assert "conteúdo do harness (LEI ZERO) foi ANEXADO" \
  'grep -q "LEI ZERO" "$TARGET/.claude/CLAUDE.md"'
assert "conteúdo original aparece ANTES do bloco do harness (prova de append, não prepend/replace)" \
  '[ "$(grep -n "Nunca commitar" "$TARGET/.claude/CLAUDE.md" | cut -d: -f1)" -lt "$(grep -n "harness-wiki:begin" "$TARGET/.claude/CLAUDE.md" | cut -d: -f1)" ]'

# diff explícito: linhas do arquivo original devem estar TODAS presentes (subset), nada removido
MISSING=0
while IFS= read -r line; do
  [ -z "$line" ] && continue
  grep -qF -- "$line" "$TARGET/.claude/CLAUDE.md" || MISSING=$((MISSING+1))
done < <(git show HEAD:.claude/CLAUDE.md)
assert "diff: 0 linhas do CLAUDE.md original foram removidas/alteradas" '[ "$MISSING" -eq 0 ]'

# --- 5. Idempotência: rodar de novo NÃO duplica o bloco ---
python3 "$LIB/merge_docs.py" markdown \
  --existing "$TARGET/.claude/CLAUDE.md" \
  --new "$SCRATCH/.claude/CLAUDE.md" \
  --label "e2e-test-v2" > /dev/null
COUNT_MARKERS=$(grep -c "harness-wiki:begin" "$TARGET/.claude/CLAUDE.md")
assert "2ª rodada não duplica o marcador (1 bloco só)" '[ "$COUNT_MARKERS" -eq 1 ]'

# --- 6. settings.json: repo-alvo SEM settings.json (caso "criar do zero") ---
python3 "$LIB/merge_docs.py" settings-json \
  --existing "$TARGET/.claude/settings.json" \
  --new "$SCRATCH/.claude/settings.json" > "$WORK/settings-result.json"
ACTION2=$(python3 -c "import json;print(json.load(open('$WORK/settings-result.json'))['action'])")
assert "settings.json ausente -> action=created" '[ "$ACTION2" = "created" ]'
assert "settings.json criado tem chave hooks" 'python3 -c "import json;d=json.load(open(\"$TARGET/.claude/settings.json\"));exit(0 if \"hooks\" in d else 1)"'

echo
if [ "$FAIL" -eq 0 ]; then
  echo "RESULTADO: TODOS OS CENÁRIOS PASSARAM (harness-init merge e2e)"
else
  echo "RESULTADO: FALHAS DETECTADAS"
fi
exit "$FAIL"
