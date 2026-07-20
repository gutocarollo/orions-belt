#!/usr/bin/env bash
# provision-push — one-shot (run BY HAND, it is INTERACTIVE). Provisions a
# redundant push path via the gh CLI, in addition to the SSH that already works.
# Re-run it only on a machine migration. It is NOT an automatic hook (it needs
# gh's device-flow, does not run on any Claude/Codex event) — it lives in
# .harness/hooks/ by the same physical convention as the other harness infra
# scripts, but it is not registered in settings.json/hooks.json. Cited as
# "step 2" by the git-delivery skill.
set -uo pipefail

echo "== 1. gh CLI installed?"
if ! command -v gh >/dev/null 2>&1; then
  echo "   installing gh (official GitHub apt)..."
  sudo mkdir -p -m 755 /etc/apt/keyrings
  wget -qO- https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    | sudo tee /etc/apt/keyrings/githubcli-archive-keyring.gpg >/dev/null
  sudo chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    | sudo tee /etc/apt/sources.list.d/github-cli.list >/dev/null
  sudo apt update && sudo apt install -y gh
else
  echo "   already installed: $(gh --version | head -1)"
fi

echo "== 2. login (device flow — INTERACTIVE, ~2 min):"
if gh auth status >/dev/null 2>&1; then
  echo "   already authenticated:"; gh auth status 2>&1 | grep -i 'logged in' | head -1
else
  gh auth login -h github.com -p https -w
fi

echo "== 3. gh as git credential helper:"
gh auth setup-git && echo "   ok"

echo "== 4. validation (dry, pushes nothing):"
timeout 8 ssh -T -o BatchMode=yes git@github.com 2>&1 | head -1 || true
gh auth status 2>&1 | grep -i 'logged in' | head -1 || echo "   gh not logged in"
echo "== done. Push now has 2 paths: SSH (step 1) and gh/HTTPS (step 2)."
