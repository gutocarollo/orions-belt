#!/usr/bin/env bash
# test_harness_init_e2e.sh — end-to-end proof of the real harness-init flow
# (F5, gate of docs/planning/00-plano-consolidado.md §6-F5): renders the WHOLE
# template via a real copier into a scratch dir, applies the non-destructive merge
# onto a preexisting CLAUDE.md with 2-3 REAL lines, and confirms via diff that the
# original content survived untouched (append, not replace).
#
# Requires `uvx` (downloads/caches copier on the first run). Runs outside orions-belt
# (fixtures in $TMPDIR), never writes inside the repo itself.
#
# Lives in templates/tests/ (excluded from the copy via copier.yml `/tests`, same
# reason as the sibling test_council_merge.py: it tests the templates tree AS A
# WHOLE via a real `uvx copier copy` — it is not reusable once materialized into a
# target project, unlike .harness/lib/tests/{test_scan_project,
# test_merge_docs}.py, which are portable and SHIP to the target project.
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
  # $1 = label, $2 = shell expression (0=pass)
  if eval "$2"; then
    echo "PASS: $1"
  else
    echo "FAIL: $1"
    FAIL=1
  fi
}

# --- 1. Fixture: target repo with a PREEXISTING CLAUDE.md (2-3 real lines) ---
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

# --- 2. Full render via copier (what harness-init would do in Phase A) ---
if ! command -v uvx >/dev/null 2>&1; then
  echo "SKIP: uvx unavailable in this environment — cannot prove the real copier flow"
  exit 77  # SKIP convention (README.md #H4): not a PASS
fi

RENDER_LOG="$WORK/copier.log"
if ! uvx copier copy "$REPO_ROOT" "$SCRATCH" \
    --data project_name=e2e-fixture --data owner_name=Tester \
    --defaults --trust -q > "$RENDER_LOG" 2>&1; then
  echo "FAIL: copier copy failed -- $(tail -5 "$RENDER_LOG")"
  exit 1
fi
assert "scratch render produced .claude/CLAUDE.md" '[ -f "$SCRATCH/.claude/CLAUDE.md" ]'

# --- 3. Non-destructive merge (what harness-init would do in Phase C) ---
python3 "$LIB/merge_docs.py" markdown \
  --existing "$TARGET/.claude/CLAUDE.md" \
  --new "$SCRATCH/.claude/CLAUDE.md" \
  --label "e2e-test" > "$WORK/merge-result.json"

ACTION=$(python3 -c "import json;print(json.load(open('$WORK/merge-result.json'))['action'])")
assert "merge reported action=appended (not overwrite)" '[ "$ACTION" = "appended" ]'

# --- 4. Non-destructiveness proofs (the literal gate) ---
assert "line 'Nunca commitar direto na main' survives verbatim" \
  'grep -q "Nunca commitar direto na main" "$TARGET/.claude/CLAUDE.md"'
assert "line 'Rodar \`make test\`' survives verbatim" \
  'grep -q "Rodar \`make test\` antes de qualquer PR" "$TARGET/.claude/CLAUDE.md"'
assert "harness contract content was appended (language-independent sentinel present)" \
  'grep -q "PROVA-DE-CONCLUSAO" "$TARGET/.claude/CLAUDE.md"'
assert "original content appears BEFORE the harness block (proof of append, not prepend/replace)" \
  '[ "$(grep -n "Nunca commitar" "$TARGET/.claude/CLAUDE.md" | cut -d: -f1)" -lt "$(grep -n "orions-belt:begin" "$TARGET/.claude/CLAUDE.md" | cut -d: -f1)" ]'

# explicit diff: ALL lines of the original file must be present (subset), nothing removed
MISSING=0
while IFS= read -r line; do
  [ -z "$line" ] && continue
  grep -qF -- "$line" "$TARGET/.claude/CLAUDE.md" || MISSING=$((MISSING+1))
done < <(git show HEAD:.claude/CLAUDE.md)
assert "diff: 0 lines of the original CLAUDE.md were removed/changed" '[ "$MISSING" -eq 0 ]'

# --- 5. Idempotency: running again does NOT duplicate the block ---
python3 "$LIB/merge_docs.py" markdown \
  --existing "$TARGET/.claude/CLAUDE.md" \
  --new "$SCRATCH/.claude/CLAUDE.md" \
  --label "e2e-test-v2" > /dev/null
COUNT_MARKERS=$(grep -c "orions-belt:begin" "$TARGET/.claude/CLAUDE.md")
assert "2nd run does not duplicate the marker (only 1 block)" '[ "$COUNT_MARKERS" -eq 1 ]'

# --- 6. settings.json: target repo WITHOUT settings.json (the "create from scratch" case) ---
python3 "$LIB/merge_docs.py" settings-json \
  --existing "$TARGET/.claude/settings.json" \
  --new "$SCRATCH/.claude/settings.json" > "$WORK/settings-result.json"
ACTION2=$(python3 -c "import json;print(json.load(open('$WORK/settings-result.json'))['action'])")
assert "settings.json absent -> action=created" '[ "$ACTION2" = "created" ]'
assert "created settings.json has the hooks key" 'python3 -c "import json;d=json.load(open(\"$TARGET/.claude/settings.json\"));exit(0 if \"hooks\" in d else 1)"'

echo
if [ "$FAIL" -eq 0 ]; then
  echo "RESULT: ALL SCENARIOS PASSED (harness-init merge e2e)"
else
  echo "RESULT: FAILURES DETECTED"
fi
exit "$FAIL"
