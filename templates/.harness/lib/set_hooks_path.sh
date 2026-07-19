#!/usr/bin/env bash
# set_hooks_path.sh — ativa core.hooksPath=.githooks SEM clobber (A2, gap real
# da auditoria adversarial pós-v1.0.0: o `_task` do copier.yml rodava
# `git config core.hooksPath .githooks` INCONDICIONAL — em brownfield com
# Husky (ou qualquer outro hooksPath já configurado) isso desativava o hook
# manager do usuário silenciosamente).
#
# Fonte única: chamado tanto pelo `_task` do copier.yml (roda dentro do dst
# ao fim de `copier copy`/`update`, cwd = raiz do projeto renderizado) quanto
# por `harness-install.sh` (chama explicitamente contra o TARGET depois do
# merge, porque em brownfield o `_task` roda só dentro do SCRATCH — ver
# comentário no topo de harness-install.sh).
#
# Uso: set_hooks_path.sh [target-dir]   (default: cwd)
# Fail-open: nunca retorna != 0 (nunca deve derrubar a instalação/task do Copier).
set -uo pipefail

TARGET="${1:-.}"
cd "$TARGET" 2>/dev/null || { echo "harness-wiki: set_hooks_path.sh: diretório '$TARGET' inexistente -- nada a fazer" >&2; exit 0; }

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "harness-wiki: '$TARGET' ainda nao e repo git -- rode 'git init && git config core.hooksPath .githooks' manualmente para ativar o pre-commit de ref-integrity" >&2
  exit 0
fi

CURRENT_HP="$(git config --get core.hooksPath 2>/dev/null || true)"

if [ -z "$CURRENT_HP" ]; then
  git config core.hooksPath .githooks
  echo "harness-wiki: core.hooksPath -> .githooks"
elif [ "$CURRENT_HP" = ".githooks" ]; then
  echo "harness-wiki: core.hooksPath ja e .githooks (idempotente, nada a fazer)"
else
  # GATE A2: nunca sobrescrever um hooksPath já customizado (Husky, lefthook,
  # husky.sh, qualquer outro gerenciador). Avisa e ensina o encadeamento
  # compatível em vez de clobber silencioso.
  echo "harness-wiki: core.hooksPath ja aponta para '$CURRENT_HP' (ex.: Husky/outro hook manager) -- NAO sobrescrito (A2, anti-clobber). Para ativar o ref-integrity do harness sem substituir seu hook manager, encadeie manualmente: adicione ao final do seu hook em '$CURRENT_HP/pre-commit' uma chamada a 'bash \"\$(git rev-parse --show-toplevel)/.githooks/pre-commit\"' deste projeto. Se preferir substituir por completo em vez de encadear, rode 'git config core.hooksPath .githooks' você mesmo. Ver docs/manual/14-instalacao-e-update.md." >&2
fi

exit 0
