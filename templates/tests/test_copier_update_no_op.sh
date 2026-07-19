#!/usr/bin/env bash
# test_copier_update_no_op.sh — regressão do M1 (auditoria adversarial H4):
# `copier update` na MESMA versão/tag (zero mudança de template) tem que ser
# um NO-OP real em `.harness/answers.yml`, não só em arquivos renderizados.
#
# Bug real encontrado e corrigido nesta rodada: `harness_codex_max_threads`,
# `harness_codex_max_depth`, `harness_codex_project_doc_max_bytes`,
# `harness_codex_agents_dir`, `harness_codex_config_path` e
# `harness_mcp_db_prod_port` tinham `when` referenciando `use_codex`/
# `has_prod_stack`, mas essas duas variáveis eram declaradas MAIS ABAIXO no
# copier.yml. O Copier resolve `when` na ORDEM DE DECLARAÇÃO do questionário
# (confirmado via Context7 /copier-org/copier docs/configuring.md — "the
# question is skipped and its answer is not recorded" quando `when` é
# false): na 1ª `copier copy`, a variável referenciada ainda não existe no
# namespace (undefined = falsy) quando a pergunta dependente é avaliada, a
# pergunta é pulada e a resposta não é gravada em answers.yml. No `copier
# update` seguinte, o answers.yml já carrega a variável desde o início, o
# `when` passa a avaliar true, e a chave "aparece" como diff mesmo sem
# nenhuma mudança real de versão/template — um update que deveria ser
# no-op não era. Fix: `use_claude`/`use_codex` movidos para logo após a
# seção de identidade; `harness_mcp_db_prod_port` movido para dentro do
# bloco `prod_*` (depois de `has_prod_stack`).
#
# Usa o SHA atual de HEAD (não uma tag antiga) de propósito — precisa
# exercitar o copier.yml ATUAL deste working tree, não um checkpoint
# histórico. Requer commit prévio das mudanças em avaliação (o alvo é o
# commit, não o working tree sujo).
#
# GOTCHA NOVO descoberto nesta rodada (documentado também em
# docs/manual/14-instalacao-e-update.md): `--vcs-ref HEAD` (a STRING
# literal "HEAD") funciona para `copier copy`, mas QUEBRA em `copier
# update` -- Copier grava `_commit` em answers.yml como um `git describe`
# composto (ex. "v1.0.0-12-g346ea08"), e ao rodar `update` de novo com
# `--vcs-ref HEAD`, ele tenta fazer `git checkout -f` desse texto composto
# como se fosse um ref válido -- não é (describe != revspec), e a
# atualização morre com "pathspec did not match any file(s)". Usar o SHA
# RESOLVIDO (`git rev-parse HEAD`) em vez da string "HEAD" evita o bug
# (reproduzido e confirmado nesta sessão, 2 repros isolados) -- é o mesmo
# commit, só não passa pela resolução textual "HEAD" que dispara o path
# quebrado. Este teste usa o SHA para as chamadas de `copy` E `update`.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
HEAD_SHA="$(git -C "$REPO_ROOT" rev-parse HEAD)"

FAIL=0
WORK="$(mktemp -d /tmp/copier-update-noop.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

assert() {
  if eval "$2"; then echo "PASS: $1"; else echo "FAIL: $1"; FAIL=1; fi
}

if ! command -v uvx >/dev/null 2>&1; then
  echo "SKIP: uvx indisponível — não é possível provar o mecanismo real do copier update" >&2
  exit 77
fi

FIXTURE="$WORK/fixture"
mkdir -p "$FIXTURE"
cd "$FIXTURE"
git init -q
git config user.email "test@example.com"
git config user.name "Test"

# --- 1. copy pinned a HEAD (use_codex=true default -- é o caso que expõe o bug) ---
if ! timeout 90 uvx copier copy --trust --defaults \
    -d project_name=noopupdate -d owner_name=T --vcs-ref "$HEAD_SHA" \
    "$REPO_ROOT" . > "$WORK/copy.log" 2>&1; then
  echo "FAIL: copier copy --vcs-ref $HEAD_SHA falhou -- $(tail -20 "$WORK/copy.log")"
  exit 1
fi
git add -A && git commit -qm "bootstrap HEAD" >/dev/null

assert "answers.yml existe" '[ -f .harness/answers.yml ]'
assert "answers.yml JÁ traz harness_codex_max_threads na 1a copy (a variável use_codex precede a pergunta)" \
  'grep -q "^harness_codex_max_threads:" .harness/answers.yml'
assert "answers.yml JÁ traz harness_codex_agents_dir na 1a copy" \
  'grep -q "^harness_codex_agents_dir:" .harness/answers.yml'
assert "answers.yml JÁ traz harness_mcp_db_prod_port only quando has_prod_stack -- default false, chave ausente é esperado" \
  '! grep -q "^harness_mcp_db_prod_port:" .harness/answers.yml'

cp .harness/answers.yml "$WORK/answers-before.yml"

# --- 2. update na MESMA ref (HEAD) -- zero mudança de template, tem que ser no-op ---
if ! timeout 90 uvx copier update --trust --defaults --vcs-ref "$HEAD_SHA" \
    --answers-file .harness/answers.yml > "$WORK/update.log" 2>&1; then
  echo "FAIL: copier update --vcs-ref $HEAD_SHA (mesma ref) falhou -- $(tail -20 "$WORK/update.log")"
  FAIL=1
fi

assert "update na MESMA ref é NO-OP real em answers.yml (diff vazio)" \
  'diff -q "$WORK/answers-before.yml" .harness/answers.yml >/dev/null'
assert "update na MESMA ref não suja o working tree (git status --short vazio, exceto trailing newline)" \
  '[ -z "$(git status --short)" ]'

# --- 3. com has_prod_stack=true explícito, harness_mcp_db_prod_port tem que
#     aparecer JÁ na 1a copy (não só depois de um update) ---
FIXTURE2="$WORK/fixture-prod"
mkdir -p "$FIXTURE2"
cd "$FIXTURE2"
git init -q
git config user.email "test@example.com"
git config user.name "Test"
if ! timeout 90 uvx copier copy --trust --defaults \
    -d project_name=noopupdateprod -d owner_name=T -d has_prod_stack=true \
    -d prod_stack_prefix=noop -d prod_registry_url=registry.local \
    -d prod_public_web_url=https://noop.local --vcs-ref "$HEAD_SHA" \
    "$REPO_ROOT" . > "$WORK/copy-prod.log" 2>&1; then
  echo "FAIL: copier copy --vcs-ref $HEAD_SHA (has_prod_stack=true) falhou -- $(tail -20 "$WORK/copy-prod.log")"
  FAIL=1
else
  assert "com has_prod_stack=true, harness_mcp_db_prod_port JÁ aparece na 1a copy" \
    'grep -q "^harness_mcp_db_prod_port:" .harness/answers.yml'
fi

echo
echo "=== resumo ==="
if [ "$FAIL" -eq 0 ]; then
  echo "M1 (no-op não-idempotente) CORRIGIDO — copier update na mesma ref não muda answers.yml."
else
  echo "AINDA HÁ GAP ABERTO — ver FAILs acima."
fi
exit $FAIL
