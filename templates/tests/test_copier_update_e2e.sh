#!/usr/bin/env bash
# test_copier_update_e2e.sh — prova de ponta-a-ponta do merge 3-vias NATIVO
# do Copier (F8, gate de docs/planning/00-plano-consolidado.md §6-F8).
#
# Diferente de test_harness_init_e2e.sh (F5, que testa merge_docs.py — o
# merge PRÓPRIO do harness só para os 3 arquivos sensíveis): este teste
# exercita `copier update` de verdade, provando (a) mudança upstream nova
# chega no arquivo renderizado, (b) customização local sobrevive intocada
# quando não há conflito real, (c) conflito real gera marcadores
# `<<<<<<< before updating` / `=======` / `>>>>>>> after updating` em vez de
# descartar silenciosamente um dos dois lados.
#
# Usa as tags v0.1.0/v0.2.0/v0.3.0 do PRÓPRIO orions-belt como fixture —
# são checkpoints reais da história deste repo (criados na sessão F8):
#   v0.1.0 = baseline (copier.yml na raiz + _subdirectory + answers-file fix)
#   v0.2.0 = mudança upstream ORTOGONAL (mensagem de reap-leaks.sh)
#   v0.3.0 = mudança upstream que CONFLITA com a customização de teste
#            (comentário na linha HARNESS_DEV_API_PORT de harness.conf.jinja)
# Não cria tags novas a cada rodada — determinístico, sem efeito colateral
# no repo fonte. Roda inteiramente em tempdir fora do orions-belt.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"

FAIL=0
WORK="$(mktemp -d /tmp/copier-update-e2e.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT
FIXTURE="$WORK/fixture"
mkdir -p "$FIXTURE"

assert() {
  if eval "$2"; then echo "PASS: $1"; else echo "FAIL: $1"; FAIL=1; fi
}

if ! command -v uvx >/dev/null 2>&1; then
  echo "SKIP: uvx indisponível — não é possível provar o mecanismo real do copier update"
  exit 77  # convencao SKIP (README.md #H4): nao e PASS
fi
for tag in v0.1.0 v0.2.0 v0.3.0; do
  if ! git -C "$REPO_ROOT" rev-parse "$tag" >/dev/null 2>&1; then
    echo "SKIP: tag $tag não existe em $REPO_ROOT — fixture do teste depende dela (ver cabeçalho deste script)"
    exit 77  # convencao SKIP (README.md #H4): nao e PASS
  fi
done

cd "$FIXTURE"
git init -q
git config user.email "test@example.com"
git config user.name "Test"

# --- 1. copy pinned to v0.1.0 ---
if ! timeout 90 uvx copier copy --trust --defaults \
    -d project_name=e2eupdate -d owner_name=T --vcs-ref v0.1.0 \
    "$REPO_ROOT" . > "$WORK/copy.log" 2>&1; then
  echo "FAIL: copier copy v0.1.0 falhou -- $(tail -10 "$WORK/copy.log")"
  exit 1
fi
git add -A && git commit -qm "bootstrap v0.1.0" >/dev/null
assert "answers.yml existe e aponta pra v0.1.0" \
  'grep -q "_commit: v0.1.0" .harness/answers.yml'

# --- 2. customização local real: linha de CLAUDE.md + porta de harness.conf ---
cat >> .claude/CLAUDE.md <<'EOF'

## Regra específica deste projeto (customização local do usuário)

- Nunca usar a porta 8000 em produção, este time reservou 9100 para a API.
EOF
sed -i 's/^HARNESS_DEV_API_PORT=8000.*/HARNESS_DEV_API_PORT=9100/' .harness/harness.conf
grep -q "HARNESS_DEV_API_PORT=9100" .harness/harness.conf || {
  echo "FAIL: setup — não conseguiu customizar HARNESS_DEV_API_PORT (formato mudou no template?)"
  exit 1
}
git add -A && git commit -qm "customizacao local" >/dev/null

# --- 3. update para v0.2.0 (mudança ORTOGONAL — reap-leaks.sh) ---
# --vcs-ref explícito é OBRIGATÓRIO aqui: achado real (F8) — `copier update`
# sem --vcs-ref pula direto pra tag MAIS RECENTE (v0.3.0), não incrementa
# 1-por-1; sem o pin, este passo intermediário nunca existiria de verdade.
if ! timeout 90 uvx copier update --trust --defaults --vcs-ref v0.2.0 \
    --answers-file .harness/answers.yml > "$WORK/update1.log" 2>&1; then
  echo "FAIL: copier update v0.2.0 falhou -- $(tail -15 "$WORK/update1.log")"
  FAIL=1
fi
assert "update1: chegou na versão v0.2.0" 'grep -q "_commit: v0.2.0" .harness/answers.yml'
assert "update1: mudança upstream (reap-leaks.sh) chegou" \
  'grep -q "reap-leaks: \$n processo" .harness/hooks/reap-leaks.sh'
assert "update1: customização de CLAUDE.md sobreviveu intocada" \
  'grep -q "reservou 9100 para a API" .claude/CLAUDE.md'
assert "update1: customização de harness.conf sobreviveu intocada" \
  'grep -q "HARNESS_DEV_API_PORT=9100" .harness/harness.conf'
assert "update1: NENHUM marcador de conflito (merge limpo, sem colisão real)" \
  '! grep -q "<<<<<<< before updating" .harness/harness.conf'
git add -A && git commit -qm "update to v0.2.0" >/dev/null

# --- 4. update para v0.3.0 (mudança que CONFLITA com a customização) ---
timeout 90 uvx copier update --trust --defaults --vcs-ref v0.3.0 \
  --answers-file .harness/answers.yml > "$WORK/update2.log" 2>&1
assert "update2: chegou na versão v0.3.0" 'grep -q "_commit: v0.3.0" .harness/answers.yml'
assert "update2: CONFLITO real gera marcadores (não descarta silenciosamente)" \
  'grep -q "<<<<<<< before updating" .harness/harness.conf'
assert "update2: lado 'mine' preserva o valor local (9100)" \
  'sed -n "/<<<<<<< before updating/,/=======/p" .harness/harness.conf | grep -q "9100"'
assert "update2: lado 'theirs' traz a mudança upstream (comentário novo)" \
  'sed -n "/=======/,/>>>>>>> after updating/p" .harness/harness.conf | grep -q "porta padrão do backend"'
assert "update2: git marca o arquivo como unmerged (UU)" \
  'git status --short .harness/harness.conf | grep -q "^UU"'
assert "update2: CLAUDE.md (fora do arquivo em conflito) continua intocado" \
  'grep -q "reservou 9100 para a API" .claude/CLAUDE.md'

echo
if [ "$FAIL" -eq 0 ]; then
  echo "RESULTADO: TODOS OS CENÁRIOS PASSARAM (copier update e2e — merge 3-vias nativo)"
else
  echo "RESULTADO: FALHAS DETECTADAS"
fi
exit "$FAIL"
