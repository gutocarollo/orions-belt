#!/usr/bin/env bash
# provision-push — one-shot (rodar À MÃO, é INTERATIVO). Provisiona um caminho
# redundante de push via gh CLI, além do SSH que já funciona. Reexecutar só em
# migração de máquina. NÃO é um hook automático (precisa do device-flow do gh,
# não roda em nenhum evento do Claude/Codex) — vive em .harness/hooks/ pela
# mesma convenção física dos outros scripts de infra do harness, mas não está
# registrado em settings.json/hooks.json. Citado como "degrau 2" pela skill
# git-delivery.
set -uo pipefail

echo "== 1. gh CLI instalado?"
if ! command -v gh >/dev/null 2>&1; then
  echo "   instalando gh (apt oficial GitHub)..."
  sudo mkdir -p -m 755 /etc/apt/keyrings
  wget -qO- https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    | sudo tee /etc/apt/keyrings/githubcli-archive-keyring.gpg >/dev/null
  sudo chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    | sudo tee /etc/apt/sources.list.d/github-cli.list >/dev/null
  sudo apt update && sudo apt install -y gh
else
  echo "   já instalado: $(gh --version | head -1)"
fi

echo "== 2. login (device flow — INTERATIVO, ~2 min):"
if gh auth status >/dev/null 2>&1; then
  echo "   já autenticado:"; gh auth status 2>&1 | grep -i 'logged in' | head -1
else
  gh auth login -h github.com -p https -w
fi

echo "== 3. gh como credential helper do git:"
gh auth setup-git && echo "   ok"

echo "== 4. validação (dry, não empurra nada):"
timeout 8 ssh -T -o BatchMode=yes git@github.com 2>&1 | head -1 || true
gh auth status 2>&1 | grep -i 'logged in' | head -1 || echo "   gh não logado"
echo "== pronto. Push agora tem 2 caminhos: SSH (degrau 1) e gh/HTTPS (degrau 2)."
