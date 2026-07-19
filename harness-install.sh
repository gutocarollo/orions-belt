#!/usr/bin/env bash
# harness-install.sh — bootstrap BROWNFIELD-SAFE de instalação/atualização do
# harness-wiki num projeto-alvo (B3, gap BLOQUEANTE da revisão adversarial
# pós-v1.0.0).
#
# O PROBLEMA QUE ISTO RESOLVE: `copier copy <harness-wiki> <projeto-alvo>
# --trust` rodado DIRETO contra um repo que já existe (o caso comum — você
# quase sempre está adotando o harness num projeto vivo, não criando um do
# zero) é circular e destrutivo:
#   - sem `--overwrite`: qualquer colisão de nome (AGENTS.md, .claude/
#     CLAUDE.md, .claude/settings.json, .gitignore) faz o Copier abortar com
#     exit 1 e o projeto fica com instalação PARCIAL.
#   - com `--overwrite`: os 4 arquivos acima (que quase sempre já têm
#     conteúdo do usuário) são SOBRESCRITOS por inteiro.
#   - com `--skip`: nada do harness entra nesses 4 arquivos — instalação
#     manca (settings.json sem os hooks do harness, por exemplo).
# `copier update` NÃO resolve isso: ele assume que o projeto-alvo NASCEU de
# um `copier copy` anterior do MESMO template (precisa de `.harness/
# answers.yml` já existente e de um histórico coerente) — não serve para
# "adotar" um repo que já tinha vida própria antes do harness. Por isso este
# bootstrap existe como uma 3ª via, específica para a PRIMEIRA adoção
# brownfield (updates subsequentes usam `copier update` normalmente — ver
# docs/manual/14-instalacao-e-update.md).
#
# O FLUXO (nunca escreve no projeto-alvo via `copier copy` direto):
#   1. Renderiza o framework INTEIRO num diretório SCRATCH temporário via
#      `copier copy` (a raiz deste repo — nunca o projeto-alvo).
#   2. Aplica no projeto-alvo, arquivo por arquivo:
#        - não existe no alvo            -> copia direto.
#        - é um dos 4 arquivos SENSÍVEIS (AGENTS.md, .claude/CLAUDE.md,
#          .claude/settings.json, .gitignore) E já existe no alvo -> merge
#          ADITIVO via `.harness/lib/merge_docs.py` (o binário RENDERIZADO no
#          scratch — a versão certa da tag/HEAD que está sendo instalada,
#          não a do checkout local deste script).
#        - qualquer outro arquivo framework-owned que já existe (reinstalação
#          /update manual) -> overwrite direto (é dono do harness, não do
#          usuário; ver Gap conhecido na skill harness-init).
#   3. `.harness/answers.yml` chega ao projeto-alvo pelo passo 2 (é só mais
#      um arquivo "que não existe" na 1ª instalação) — pré-requisito de
#      `copier update --answers-file .harness/answers.yml` no futuro.
#   4. Ativa `core.hooksPath` (A2) chamando `.harness/lib/set_hooks_path.sh`
#      EXPLICITAMENTE contra o TARGET. O `_task` equivalente do copier.yml
#      roda dentro do SCRATCH neste fluxo (cwd = scratch durante o `copier
#      copy` do passo 1, que nem é repo git) — não configura nada no
#      projeto-alvo sozinho, por isso o passo 4 é necessário aqui. O script
#      nunca sobrescreve um hooksPath já customizado (Husky/lefthook/etc.) —
#      mesma fonte única usada pelo `_task`, ver comentário em set_hooks_path.sh.
#
# Uso:
#   ./harness-install.sh <target-dir> [-- ] [args do copier copy...]
#
# Exemplos:
#   ./harness-install.sh ../meu-projeto \
#     --data project_name=meu-projeto --data owner_name=Fulano --defaults
#   ./harness-install.sh ../meu-projeto --vcs-ref v1.0.0 \
#     --data project_name=meu-projeto --data owner_name=Fulano --defaults
#
# `--trust` é sempre adicionado por este script (mesma exigência de qualquer
# `copier copy`/`update` deste repo — ver README.md). Args extras são
# repassados verbatim para `copier copy` (ex.: `--data`, `--vcs-ref`,
# `--defaults`).
set -euo pipefail

usage() {
  cat <<'EOF'
uso: harness-install.sh <target-dir> [args do copier copy...]

Instala/adota o harness-wiki num projeto-alvo (greenfield OU brownfield) sem
sobrescrever AGENTS.md / .claude/CLAUDE.md / .claude/settings.json /
.gitignore pré-existentes e sem clobber de core.hooksPath já customizado.
Ver comentário no topo deste arquivo para o fluxo completo (B3).

exemplos:
  ./harness-install.sh ../meu-projeto \
    --data project_name=meu-projeto --data owner_name=Fulano --defaults
  ./harness-install.sh ../meu-projeto --vcs-ref v1.0.0 \
    --data project_name=meu-projeto --data owner_name=Fulano --defaults

'--trust' e adicionado automaticamente. Demais args sao repassados verbatim
para 'copier copy' (--data, --vcs-ref, --defaults, etc.).
EOF
}

if [ $# -lt 1 ] || [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
  usage >&2
  exit 1
fi

TARGET_ARG="$1"; shift
COPIER_ARGS=("$@")

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$HERE"

if ! command -v uvx >/dev/null 2>&1; then
  echo "harness-install.sh: 'uvx' nao encontrado no PATH -- instale uv (https://docs.astral.sh/uv/) para rodar o copier." >&2
  exit 1
fi

# M3/H4 (auditoria adversarial): preflight de PLATAFORMA -- "portátil" não
# era declarado em lugar nenhum, e os hooks/scripts (.harness/hooks|lib/)
# exigem Bash>=4 + GNU coreutils + flock + python3 (ver check-platform.sh
# para o detalhe de CADA dependência e o comando de fix). Roda ANTES do
# render para avisar CEDO, mas nunca bloqueia sozinho o `copier copy` em si
# (que é agnóstico de plataforma) -- só o comportamento dos hooks depois de
# instalado é que degrada. Se check-platform.sh não existir ainda neste
# checkout (versão antiga do repo antes de M3), segue sem preflight
# (fail-open -- não é um requisito NOVO bloquear instalações antigas).
if [ -f "$REPO_ROOT/templates/.harness/lib/check-platform.sh" ]; then
  echo "harness-install.sh: preflight de plataforma (.harness/lib/check-platform.sh) ..." >&2
  if ! bash "$REPO_ROOT/templates/.harness/lib/check-platform.sh"; then
    echo "harness-install.sh: AVISO -- este ambiente não atende a todas as dependências obrigatórias dos hooks (ver acima). A instalação PROSSEGUE, mas hooks podem falhar/virar no-op depois -- ver docs/manual/15-limitacoes-conhecidas.md." >&2
  fi
  echo >&2
fi

mkdir -p "$TARGET_ARG"
TARGET="$(cd "$TARGET_ARG" && pwd)"

SCRATCH="$(mktemp -d "${TMPDIR:-/tmp}/harness-install.XXXXXX")"
cleanup() { rm -rf "$SCRATCH"; }
trap cleanup EXIT

echo "harness-install.sh: renderizando $REPO_ROOT -> scratch $SCRATCH ..." >&2
uvx copier copy "$REPO_ROOT" "$SCRATCH" "${COPIER_ARGS[@]}" --trust -q

LIB="$SCRATCH/.harness/lib"
if [ ! -f "$LIB/merge_docs.py" ]; then
  echo "harness-install.sh: render nao produziu .harness/lib/merge_docs.py -- template quebrado ou --data incompleto (veja stderr acima)." >&2
  exit 1
fi

# Os 4 arquivos SENSÍVEIS (B3): podem ter conteúdo do usuário, NUNCA overwrite
# direto se já existirem no alvo.
SENSITIVE_PATHS=(
  "AGENTS.md"
  ".claude/CLAUDE.md"
  ".claude/settings.json"
  ".gitignore"
)

is_sensitive() {
  local rel="$1" s
  for s in "${SENSITIVE_PATHS[@]}"; do
    [ "$rel" = "$s" ] && return 0
  done
  return 1
}

N_CREATED=0
N_OVERWRITTEN=0
N_MERGED=0

while IFS= read -r -d '' f; do
  rel="${f#"$SCRATCH"/}"
  dest="$TARGET/$rel"

  if is_sensitive "$rel"; then
    if [ -f "$dest" ]; then
      case "$rel" in
        AGENTS.md|.claude/CLAUDE.md)
          RESULT="$(python3 "$LIB/merge_docs.py" markdown --existing "$dest" --new "$f" --label harness-install)"
          ;;
        .claude/settings.json)
          RESULT="$(python3 "$LIB/merge_docs.py" settings-json --existing "$dest" --new "$f")"
          ;;
        .gitignore)
          RESULT="$(python3 "$LIB/merge_docs.py" gitignore --existing "$dest" --new "$f" --label harness-install)"
          ;;
      esac
      N_MERGED=$((N_MERGED + 1))
      echo "merge  $rel"
      echo "$RESULT" | sed 's/^/         /'
    else
      mkdir -p "$(dirname "$dest")"
      cp "$f" "$dest"
      N_CREATED=$((N_CREATED + 1))
      echo "create $rel"
    fi
  else
    if [ -f "$dest" ]; then
      N_OVERWRITTEN=$((N_OVERWRITTEN + 1))
    else
      N_CREATED=$((N_CREATED + 1))
    fi
    mkdir -p "$(dirname "$dest")"
    cp "$f" "$dest"
  fi
done < <(find "$SCRATCH" -type f -print0)

# A2: ativa core.hooksPath sem clobber, explicitamente contra o TARGET (ver
# nota no cabeçalho — o _task do copier.yml não alcança o projeto-alvo neste
# fluxo porque rodou dentro do SCRATCH no passo 1).
if [ -f "$LIB/set_hooks_path.sh" ]; then
  bash "$LIB/set_hooks_path.sh" "$TARGET"
fi

# H2/A6.2 (auditoria adversarial pós-v1.0.0): ds-gate.sh é um RATCHET —
# `MODE=check` sem `.ds-baseline.txt` roda sempre em report-only (nunca
# falha; ver comentário no topo de ds-gate.sh) porque não existe um número
# contra o qual comparar. Nenhum passo de instalação anterior gerava essa
# baseline — o gate ficava permanentemente inerte em TODO projeto instalado
# via harness-install.sh, mesmo com `ds-gate-posttool` ativo (use_ds_gate).
# Fix: 1ª instalação gera `.ds-baseline.txt` automaticamente (contagem ATUAL
# do projeto-alvo vira o piso do ratchet — só piora daqui pra frente).
# Sinal de "use_ds_gate estava ativo": presença do hook materializado
# `.harness/hooks/ds-gate-posttool.sh` (é gated-no-nome-do-arquivo pelo
# Jinja; ds-gate.sh em si é sempre shipado incondicionalmente, então não
# serve de sinal sozinho). Não roda de novo se a baseline já existir
# (reinstalação/update não deve resetar um ratchet já em andamento) —
# regenerar é ação explícita do usuário: `bash .harness/lib/ds-gate.sh
# --update-baseline` (documentado em docs/manual/05-hooks-posttooluse.md).
if [ -f "$TARGET/.harness/hooks/ds-gate-posttool.sh" ] && [ -f "$TARGET/.harness/lib/ds-gate.sh" ]; then
  DS_WEB_APP_DIR="."
  if command -v python3 >/dev/null 2>&1 && [ -f "$TARGET/.harness/lib/_tooling_conf.py" ]; then
    DS_WEB_APP_DIR="$(HARNESS_PROJECT_ROOT="$TARGET" python3 "$TARGET/.harness/lib/_tooling_conf.py" get HARNESS_WEB_APP_DIR . 2>/dev/null || echo .)"
  fi
  DS_WEB_APP_DIR="${DS_WEB_APP_DIR%/}"
  [ -z "$DS_WEB_APP_DIR" ] && DS_WEB_APP_DIR="."
  DS_BASELINE_DIR="$TARGET"
  [ "$DS_WEB_APP_DIR" != "." ] && DS_BASELINE_DIR="$TARGET/$DS_WEB_APP_DIR"
  if [ -d "$DS_BASELINE_DIR" ] && [ ! -f "$DS_BASELINE_DIR/.ds-baseline.txt" ]; then
    echo
    echo "harness-install.sh: gerando .ds-baseline.txt inicial do ds-gate (ratchet anti-hardcode)..."
    if HARNESS_PROJECT_ROOT="$TARGET" bash "$TARGET/.harness/lib/ds-gate.sh" --update-baseline >/dev/null; then
      echo "  baseline gravada em $DS_BASELINE_DIR/.ds-baseline.txt -- commite este arquivo."
    else
      echo "  aviso: ds-gate.sh --update-baseline falhou (nao bloqueante) -- rode manualmente depois: bash .harness/lib/ds-gate.sh --update-baseline" >&2
    fi
  fi
fi

echo
echo "harness-install.sh: concluido."
echo "  arquivos novos criados:            $N_CREATED"
echo "  framework-owned sobrescritos:       $N_OVERWRITTEN"
echo "  arquivos sensiveis merged (aditivo): $N_MERGED"
echo "  .harness/answers.yml gravado em:    $TARGET/.harness/answers.yml (necessario p/ 'copier update' futuro)"
