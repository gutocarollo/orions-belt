#!/usr/bin/env bash
# test_harness_install_brownfield_e2e.sh — prova de ponta-a-ponta do bootstrap
# BROWNFIELD-SAFE (B3, gap BLOQUEANTE da revisão adversarial pós-v1.0.0).
#
# Diferente de test_harness_init_e2e.sh (que copia pra um SCRATCH VAZIO e só
# chama merge_docs.py isolado — não reproduz o problema real): este teste
# roda `./harness-install.sh` DE VERDADE contra um projeto-alvo BROWNFIELD —
# repo git já existente com AGENTS.md, .claude/CLAUDE.md, .claude/
# settings.json (com 1 hook do usuário) e `.husky/` com core.hooksPath já
# apontando pra lá. É exatamente o cenário que fazia `copier copy` direto
# falhar (sem --overwrite) ou destruir (com --overwrite) — ver o comentário
# no topo de harness-install.sh.
#
# Cobre os 3 gates do H1 (auditoria):
#   (a) AGENTS.md / .claude/CLAUDE.md / .claude/settings.json preservados —
#       conteúdo original intacto, bloco do harness ANEXADO (não substituído).
#   (b) core.hooksPath continua `.husky` (nunca sobrescrito).
#   (c) hook do usuário em settings.json sobrevive E os hooks do harness são
#       adicionados.
#
# Requer `uvx` (baixa/cacheia copier na 1ª vez). Roda fora do orions-belt
# (fixture em $TMPDIR), nunca escreve dentro do próprio repo.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
INSTALLER="$REPO_ROOT/harness-install.sh"

FAIL=0
WORK="$(mktemp -d /tmp/harness-install-brownfield-e2e.XXXXXX)"
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
  echo "SKIP: uvx indisponível neste ambiente — não é possível provar o fluxo real do harness-install.sh"
  exit 77  # convencao SKIP (README.md #H4): nao e PASS
fi

# --- 1. Fixture brownfield: repo git com os 4 arquivos sensíveis PRÉ-EXISTENTES + Husky ---
TARGET="$WORK/target-project"
mkdir -p "$TARGET/.claude" "$TARGET/.husky"
cd "$TARGET"
git init -q
git config user.email "test@example.com"
git config user.name "Test"

cat > AGENTS.md <<'EOF'
# Meu projeto real
Regra do usuario: nunca commitar segredo em claro.
EOF

cat > .claude/CLAUDE.md <<'EOF'
# CLAUDE.md do meu projeto
Regra do usuario: rodar `make test` antes de qualquer PR.
EOF

cat > .claude/settings.json <<'EOF'
{
  "permissions": { "allow": ["Bash(npm test)"] },
  "hooks": {
    "Stop": [
      { "hooks": [ { "type": "command", "command": "npm run meu-check-custom" } ] }
    ]
  }
}
EOF

cat > .gitignore <<'EOF'
node_modules/
.env
EOF

cat > .husky/pre-commit <<'EOF'
#!/usr/bin/env sh
echo "husky: rodando lint-staged"
npx lint-staged
EOF
chmod +x .husky/pre-commit

git add -A
git commit -qm "fixture brownfield: AGENTS.md + CLAUDE.md + settings.json + gitignore + husky" >/dev/null
git config core.hooksPath .husky

HUSKY_MD5_BEFORE=$(md5sum .husky/pre-commit | cut -d' ' -f1)

# --- 2. Roda o bootstrap real contra o fixture (HEAD do próprio repo) ---
INSTALL_LOG="$WORK/install.log"
if ! "$INSTALLER" "$TARGET" --vcs-ref HEAD \
    --data project_name=brownfield-e2e-fixture --data owner_name=Tester \
    --defaults > "$INSTALL_LOG" 2>&1; then
  echo "FAIL: harness-install.sh falhou -- $(tail -15 "$INSTALL_LOG")"
  exit 1
fi

# --- 3. Gate (a): conteúdo original preservado + append, não replace ---
assert "AGENTS.md: linha original sobrevive verbatim" \
  'grep -q "Regra do usuario: nunca commitar segredo em claro." "$TARGET/AGENTS.md"'
assert "AGENTS.md: conteúdo do harness foi ANEXADO (marcador presente)" \
  'grep -q "orions-belt:begin" "$TARGET/AGENTS.md"'
assert "AGENTS.md: original aparece ANTES do bloco do harness (append, não prepend/replace)" \
  '[ "$(grep -n "Regra do usuario: nunca commitar" "$TARGET/AGENTS.md" | cut -d: -f1)" -lt "$(grep -n "orions-belt:begin" "$TARGET/AGENTS.md" | cut -d: -f1)" ]'

assert ".claude/CLAUDE.md: linha original sobrevive verbatim" \
  'grep -q "Regra do usuario: rodar \`make test\` antes de qualquer PR." "$TARGET/.claude/CLAUDE.md"'
assert ".claude/CLAUDE.md: conteúdo do harness foi ANEXADO" \
  'grep -q "orions-belt:begin" "$TARGET/.claude/CLAUDE.md"'

assert ".gitignore: padrão original sobrevive verbatim" \
  'grep -q "node_modules/" "$TARGET/.gitignore" && grep -q "\.env" "$TARGET/.gitignore"'
assert ".gitignore: conteúdo do harness foi ANEXADO" \
  'grep -q "orions-belt:begin" "$TARGET/.gitignore"'

# --- 4. Gate (b): core.hooksPath NÃO trocado de .husky ---
assert "core.hooksPath continua .husky (nunca sobrescrito)" \
  '[ "$(git -C "$TARGET" config --get core.hooksPath)" = ".husky" ]'
assert ".husky/pre-commit não foi tocado (md5 idêntico)" \
  '[ "$(md5sum "$TARGET/.husky/pre-commit" | cut -d\  -f1)" = "$HUSKY_MD5_BEFORE" ]'

# --- 5. Gate (c): hook do usuário sobrevive + hooks do harness entram ---
python3 - "$TARGET/.claude/settings.json" > "$WORK/settings-check.json" <<'PYEOF'
import json, sys
d = json.load(open(sys.argv[1]))
stop_cmds = [h["command"] for grp in d["hooks"].get("Stop", []) for h in grp["hooks"]]
out = {
    "user_hook_present": "npm run meu-check-custom" in stop_cmds,
    "harness_hook_present": any(".harness/hooks/" in c for c in stop_cmds),
    "permissions_preserved": d.get("permissions", {}).get("allow") == ["Bash(npm test)"],
    "total_events": sorted(d["hooks"].keys()),
}
json.dump(out, sys.stdout)
PYEOF
assert "settings.json: hook do usuário sobrevive" \
  'python3 -c "import json;d=json.load(open(\"$WORK/settings-check.json\"));exit(0 if d[\"user_hook_present\"] else 1)"'
assert "settings.json: hooks do harness foram adicionados" \
  'python3 -c "import json;d=json.load(open(\"$WORK/settings-check.json\"));exit(0 if d[\"harness_hook_present\"] else 1)"'
assert "settings.json: chave permissions preservada verbatim" \
  'python3 -c "import json;d=json.load(open(\"$WORK/settings-check.json\"));exit(0 if d[\"permissions_preserved\"] else 1)"'

# --- 6. .harness/answers.yml gravado (pré-requisito de copier update futuro) ---
assert ".harness/answers.yml gravado no projeto-alvo" '[ -f "$TARGET/.harness/answers.yml" ]'

# --- 7. Idempotência: rodar de novo não duplica blocos nem hooks ---
if ! "$INSTALLER" "$TARGET" --vcs-ref HEAD \
    --data project_name=brownfield-e2e-fixture --data owner_name=Tester \
    --defaults >> "$INSTALL_LOG" 2>&1; then
  echo "FAIL: 2ª rodada de harness-install.sh falhou"
  FAIL=1
fi
assert "2ª rodada: AGENTS.md não duplica o marcador" \
  '[ "$(grep -c "orions-belt:begin" "$TARGET/AGENTS.md")" -eq 1 ]'
assert "2ª rodada: core.hooksPath ainda .husky" \
  '[ "$(git -C "$TARGET" config --get core.hooksPath)" = ".husky" ]'

echo
if [ "$FAIL" -eq 0 ]; then
  echo "RESULTADO: TODOS OS GATES BROWNFIELD PASSARAM (harness-install.sh e2e)"
else
  echo "RESULTADO: FALHAS DETECTADAS"
fi
exit "$FAIL"
