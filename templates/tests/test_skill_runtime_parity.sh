#!/usr/bin/env bash
# test_skill_runtime_parity.sh — regression for the SYMMETRIC gap (H4
# adversarial audit, HIGH severity): council + adversarial-review only
# existed in `.agents/skills/`, WITHOUT any runtime conditional — a
# `use_claude=true use_codex=false` install did NOT have
# `{{ project_name }}-delivery-council` nor `adversarial-review` in
# `.claude/skills` (Claude Code does not scan `.agents/skills`, the same
# H3/A1 finding that motivated the skills-shared mechanism for the other 6
# skills). It is the exact mirror of the gap H3 closed for Codex — here it was
# the Claude-only install left without the council and without the adversarial reviewer.
#
# Fix: the 2 skills migrated to the same skills-shared mechanism
# (.harness/skills-shared/{delivery-council,adversarial-review}/) with
# 1-line wrappers in .claude/skills/ (gated by use_claude) and
# .agents/skills/ (gated by use_codex).
#
# Also covers the secondary symmetric gap of the same finding: harness_runs_dir
# had an unconditional ".claude/runs" default — a codex-only project
# inherited a Claude-flavored path. Proves that HARNESS_RUNS_DIR resolves to
# the new neutral default ".harness/runs" in a 100% codex-only render.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"

FAIL=0
WORK="$(mktemp -d /tmp/skill-runtime-parity.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

assert() {
  if eval "$2"; then echo "PASS: $1"; else echo "FAIL: $1"; FAIL=1; fi
}

if ! command -v uvx >/dev/null 2>&1; then
  echo "SKIP: uvx unavailable — cannot prove the real copier flow" >&2
  exit 77
fi

PROJECT_NAME="skillparity"
COUNCIL_SKILL="${PROJECT_NAME}-delivery-council"

# =============================================================================
# 1. Real CLAUDE-ONLY render
# =============================================================================
CLAUDE_ONLY="$WORK/claude-only"
if ! uvx copier copy "$REPO_ROOT" "$CLAUDE_ONLY" --vcs-ref HEAD \
    --data project_name="$PROJECT_NAME" --data owner_name=Tester \
    --data use_claude=true --data use_codex=false --data harness_language=pt \
    --defaults --trust -q > "$WORK/copy-claude.log" 2>&1; then
  echo "FAIL: copier copy --vcs-ref HEAD (claude-only) failed -- $(tail -20 "$WORK/copy-claude.log")"
  exit 1
fi

assert "(symmetric gate) claude-only: .claude/skills/$COUNCIL_SKILL/SKILL.md exists" \
  '[ -f "$CLAUDE_ONLY/.claude/skills/$COUNCIL_SKILL/SKILL.md" ]'
assert "(symmetric gate) claude-only: .claude/skills/adversarial-review/SKILL.md exists" \
  '[ -f "$CLAUDE_ONLY/.claude/skills/adversarial-review/SKILL.md" ]'
assert "claude-only: .agents/skills does NOT have the council or adversarial-review (use_codex=false; .agents/skills itself may exist empty -- same preexisting asymmetry as the other 6 skills-shared, out of scope for this gap)" \
  '[ ! -e "$CLAUDE_ONLY/.agents/skills/$COUNCIL_SKILL" ] && [ ! -e "$CLAUDE_ONLY/.agents/skills/adversarial-review" ]'
assert "claude-only: CLAUDE.md cites the council skill" \
  'grep -q "$COUNCIL_SKILL" "$CLAUDE_ONLY/.claude/CLAUDE.md"'
assert "PT adversarial-review keeps heading and prose on separate lines" \
  '! grep -q "Adversarial ReviewRevisor" "$CLAUDE_ONLY/.claude/skills/adversarial-review/SKILL.md"'
assert "PT council keeps prose and arguments heading separated" \
  '! grep -q "sessao.## Argumentos" "$CLAUDE_ONLY/.claude/skills/$COUNCIL_SKILL/SKILL.md"'

# =============================================================================
# 2. Real CODEX-ONLY render
# =============================================================================
CODEX_ONLY="$WORK/codex-only"
if ! uvx copier copy "$REPO_ROOT" "$CODEX_ONLY" --vcs-ref HEAD \
    --data project_name="$PROJECT_NAME" --data owner_name=Tester \
    --data use_claude=false --data use_codex=true \
    --defaults --trust -q > "$WORK/copy-codex.log" 2>&1; then
  echo "FAIL: copier copy --vcs-ref HEAD (codex-only) failed -- $(tail -20 "$WORK/copy-codex.log")"
  exit 1
fi

assert "(symmetric gate) codex-only: .agents/skills/$COUNCIL_SKILL/SKILL.md exists" \
  '[ -f "$CODEX_ONLY/.agents/skills/$COUNCIL_SKILL/SKILL.md" ]'
assert "(symmetric gate) codex-only: .agents/skills/adversarial-review/SKILL.md exists" \
  '[ -f "$CODEX_ONLY/.agents/skills/adversarial-review/SKILL.md" ]'
assert "codex-only: .claude/ does NOT exist (use_claude=false)" \
  '[ ! -d "$CODEX_ONLY/.claude" ]'
assert "codex-only: the council's companion openai.yaml exists (.agents/skills/$COUNCIL_SKILL/agents/openai.yaml)" \
  '[ -f "$CODEX_ONLY/.agents/skills/$COUNCIL_SKILL/agents/openai.yaml" ]'
assert "EN adversarial-review keeps heading and prose on separate lines" \
  '! grep -q "Adversarial ReviewA reviewer" "$CODEX_ONLY/.agents/skills/adversarial-review/SKILL.md"'
assert "EN council keeps prose and arguments heading separated" \
  '! grep -q "session.## Input Arguments" "$CODEX_ONLY/.agents/skills/$COUNCIL_SKILL/SKILL.md"'

# --- neutral HARNESS_RUNS_DIR (harness_runs_dir default) ---
assert "codex-only: HARNESS_RUNS_DIR resolves to .harness/runs (neutral default, not .claude/runs)" \
  'grep -q "^HARNESS_RUNS_DIR=.harness/runs$" "$CODEX_ONLY/.harness/harness.conf"'
# grep on the functional CODE (SLOTS=... line), not on comments that cite
# ".claude/runs" as a historical note of the already-fixed bug (legitimate message).
assert "codex-only: subagent-throttle.sh uses \$RUNS_DIR on the SLOTS= line (not hardcoded)" \
  'grep -q "^SLOTS=\"\$ROOT/\$RUNS_DIR/.slots\"" "$CODEX_ONLY/.harness/hooks/subagent-throttle.sh"'
assert "codex-only: subagent-release.sh uses \$RUNS_DIR on the SLOTS= line (not hardcoded)" \
  'grep -q "^SLOTS=\"\$ROOT/\$RUNS_DIR/.slots\"" "$CODEX_ONLY/.harness/hooks/subagent-release.sh"'
assert "codex-only: no CODE line (outside a # comment) hardcodes .claude/runs" \
  '! grep -vE "^\s*#" "$CODEX_ONLY/.harness/hooks/subagent-throttle.sh" "$CODEX_ONLY/.harness/hooks/subagent-release.sh" | grep -q "\.claude/runs"'

# =============================================================================
# 3. Render with BOTH runtimes (default) -- BYTE-IDENTICAL content between
#    .claude/skills and .agents/skills, same single source
# =============================================================================
BOTH="$WORK/both"
if ! uvx copier copy "$REPO_ROOT" "$BOTH" --vcs-ref HEAD \
    --data project_name="$PROJECT_NAME" --data owner_name=Tester \
    --defaults --trust -q > "$WORK/copy-both.log" 2>&1; then
  echo "FAIL: copier copy --vcs-ref HEAD (both runtimes) failed -- $(tail -20 "$WORK/copy-both.log")"
  exit 1
fi

for name in "$COUNCIL_SKILL" "adversarial-review"; do
  A="$BOTH/.claude/skills/$name/SKILL.md"
  B="$BOTH/.agents/skills/$name/SKILL.md"
  if [ -f "$A" ] && [ -f "$B" ]; then
    assert "'$name': .claude and .agents render BYTE-IDENTICAL (single source skills-shared)" \
      'diff -q "$A" "$B" >/dev/null'
  else
    echo "FAIL: '$name' missing in some runtime (.claude=$([ -f "$A" ] && echo ok || echo MISSING), .agents=$([ -f "$B" ] && echo ok || echo MISSING))"
    FAIL=1
  fi
done

# --- real content (not just an empty file/stub) ---
assert "rendered council has the real sentinels (not an empty stub)" \
  'grep -q "PLAN-ADVERSARIAL-VERIFICATION: SATISFEITO | REPLANEJAR | SABATINAR | BLOQUEADO" "$BOTH/.claude/skills/$COUNCIL_SKILL/SKILL.md"'
assert "rendered adversarial-review has the real protocol (not an empty stub)" \
  'grep -q "ADVERSARIAL-VERIFICATION" "$BOTH/.claude/skills/adversarial-review/SKILL.md"'
assert "core skills do not hardcode donor apps/api or apps/web topology" \
  '! grep -Eq "apps/(api|web)" "$BOTH/.claude/skills/$COUNCIL_SKILL/SKILL.md" "$BOTH/.claude/skills/adversarial-review/SKILL.md"'

# =============================================================================
# grep of donor/other-owner-project terms = 0 (path-neutral required)
# =============================================================================
DONOR_HITS="$(grep -rlEi 'learnhouse|quero|makershub|agent-harness' "$WORK" 2>/dev/null | wc -l)"
assert "grep learnhouse|quero|makershub|agent-harness in the 3 renders = 0" '[ "$DONOR_HITS" -eq 0 ]'

echo
echo "=== summary ==="
if [ "$FAIL" -eq 0 ]; then
  echo "SYMMETRIC GAP (council+adversarial-review Claude-only) CLOSED."
else
  echo "THERE IS STILL AN OPEN GAP — see FAILs above."
fi
exit $FAIL
