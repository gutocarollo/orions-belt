#!/usr/bin/env bash
# test_harness_install_brownfield_e2e.sh — end-to-end proof of the
# BROWNFIELD-SAFE bootstrap (B3, BLOCKING gap from the post-v1.0.0 adversarial review).
#
# Unlike test_harness_init_e2e.sh (which copies into an EMPTY SCRATCH and only
# calls merge_docs.py in isolation — it does not reproduce the real problem): this test
# runs `./harness-install.sh` FOR REAL against a BROWNFIELD target project —
# an already-existing git repo with AGENTS.md, .claude/CLAUDE.md, .claude/
# settings.json (with 1 user hook) and `.husky/` with core.hooksPath already
# pointing there. It is exactly the scenario that made a direct `copier copy`
# fail (without --overwrite) or destroy (with --overwrite) — see the comment
# at the top of harness-install.sh.
#
# Covers the 3 gates of H1 (audit):
#   (a) AGENTS.md / .claude/CLAUDE.md / .claude/settings.json preserved —
#       original content intact, harness block APPENDED (not replaced).
#   (b) core.hooksPath stays `.husky` (never overwritten).
#   (c) the user hook in settings.json survives AND the harness hooks are
#       added.
#
# Requires `uvx` (downloads/caches copier on the 1st run). Runs outside orions-belt
# (fixture in $TMPDIR), never writes inside the repo itself.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
INSTALLER="$REPO_ROOT/harness-install.sh"

FAIL=0
WORK="$(mktemp -d /tmp/harness-install-brownfield-e2e.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

assert() {
  # $1 = label, $2 = shell expression (0=pass)
  if eval "$2"; then
    echo "PASS: $1"
  else
    echo "FAIL: $1"
    FAIL=1
  fi
}

if ! command -v uvx >/dev/null 2>&1; then
  echo "SKIP: uvx unavailable in this environment — cannot prove the real harness-install.sh flow"
  exit 77  # SKIP convention (README.md #H4): not a PASS
fi

# --- 1. Brownfield fixture: git repo with the 4 sensitive files PREEXISTING + Husky ---
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

# --- 2. Run the real bootstrap against the fixture (HEAD of the repo itself) ---
INSTALL_LOG="$WORK/install.log"
if ! "$INSTALLER" "$TARGET" --vcs-ref HEAD \
    --data project_name=brownfield-e2e-fixture --data owner_name=Tester \
    --defaults > "$INSTALL_LOG" 2>&1; then
  echo "FAIL: harness-install.sh failed -- $(tail -15 "$INSTALL_LOG")"
  exit 1
fi

# --- 3. Gate (a): original content preserved + append, not replace ---
assert "AGENTS.md: original line survives verbatim" \
  'grep -q "Regra do usuario: nunca commitar segredo em claro." "$TARGET/AGENTS.md"'
assert "AGENTS.md: harness content was APPENDED (marker present)" \
  'grep -q "orions-belt:begin" "$TARGET/AGENTS.md"'
assert "AGENTS.md: original appears BEFORE the harness block (append, not prepend/replace)" \
  '[ "$(grep -n "Regra do usuario: nunca commitar" "$TARGET/AGENTS.md" | cut -d: -f1)" -lt "$(grep -n "orions-belt:begin" "$TARGET/AGENTS.md" | cut -d: -f1)" ]'

assert ".claude/CLAUDE.md: original line survives verbatim" \
  'grep -q "Regra do usuario: rodar \`make test\` antes de qualquer PR." "$TARGET/.claude/CLAUDE.md"'
assert ".claude/CLAUDE.md: harness content was APPENDED" \
  'grep -q "orions-belt:begin" "$TARGET/.claude/CLAUDE.md"'

assert ".gitignore: original pattern survives verbatim" \
  'grep -q "node_modules/" "$TARGET/.gitignore" && grep -q "\.env" "$TARGET/.gitignore"'
assert ".gitignore: harness content was APPENDED" \
  'grep -q "orions-belt:begin" "$TARGET/.gitignore"'

# --- 4. Gate (b): core.hooksPath NOT switched away from .husky ---
assert "core.hooksPath stays .husky (never overwritten)" \
  '[ "$(git -C "$TARGET" config --get core.hooksPath)" = ".husky" ]'
assert ".husky/pre-commit was not touched (md5 identical)" \
  '[ "$(md5sum "$TARGET/.husky/pre-commit" | cut -d\  -f1)" = "$HUSKY_MD5_BEFORE" ]'

# --- 5. Gate (c): user hook survives + harness hooks come in ---
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
assert "settings.json: user hook survives" \
  'python3 -c "import json;d=json.load(open(\"$WORK/settings-check.json\"));exit(0 if d[\"user_hook_present\"] else 1)"'
assert "settings.json: harness hooks were added" \
  'python3 -c "import json;d=json.load(open(\"$WORK/settings-check.json\"));exit(0 if d[\"harness_hook_present\"] else 1)"'
assert "settings.json: permissions key preserved verbatim" \
  'python3 -c "import json;d=json.load(open(\"$WORK/settings-check.json\"));exit(0 if d[\"permissions_preserved\"] else 1)"'

# --- 6. .harness/answers.yml written (prerequisite for a future copier update) ---
assert ".harness/answers.yml written in the target project" '[ -f "$TARGET/.harness/answers.yml" ]'

# --- 7. Idempotency: running again does not duplicate blocks or hooks ---
if ! "$INSTALLER" "$TARGET" --vcs-ref HEAD \
    --data project_name=brownfield-e2e-fixture --data owner_name=Tester \
    --defaults >> "$INSTALL_LOG" 2>&1; then
  echo "FAIL: 2nd run of harness-install.sh failed"
  FAIL=1
fi
assert "2nd run: AGENTS.md does not duplicate the marker" \
  '[ "$(grep -c "orions-belt:begin" "$TARGET/AGENTS.md")" -eq 1 ]'
assert "2nd run: core.hooksPath still .husky" \
  '[ "$(git -C "$TARGET" config --get core.hooksPath)" = ".husky" ]'

# --- 8. G1 regression: install-time plan/stdout artifacts must NEVER be
#         installed into the target (they used to land inside SCRATCH, which
#         source_files() rglobs as the render, so a 0-byte install-plan.stdout.json
#         became an owned file at the target root). ---
assert "G1: no install-plan* artifact leaks into the target tree" \
  '[ "$(find "$TARGET" -name "install-plan*" | wc -l)" -eq 0 ]'
assert "G1: the ownership manifest records no install-plan* path" \
  '! grep -q "install-plan" "$TARGET/.harness/install-manifest.json"'

echo
if [ "$FAIL" -eq 0 ]; then
  echo "RESULT: ALL BROWNFIELD GATES PASSED (harness-install.sh e2e)"
else
  echo "RESULT: FAILURES DETECTED"
fi
exit "$FAIL"
