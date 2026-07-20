#!/usr/bin/env bash
# test_codex_parity.sh — regression for the 3 A1 sub-gaps (H3 hardening
# adversarial audit) against a real CODEX-ONLY render (`copier copy --vcs-ref HEAD
# -d use_codex=true -d use_claude=false`), never logic reimplemented in
# prose — same principle as the siblings test_harness_install_brownfield_e2e.sh /
# test_ui_evidence_gate_bypass.sh.
#
# The 3 sub-gaps, each proven CLOSED in this round:
#   1. Runtime-neutral skills (grill-me, prova-de-conclusao,
#      ui-evidence, marathon, repo-wiki-curator, verify) did not exist in
#      .agents/skills — Codex discovers project skills ONLY there (confirmed
#      via WebFetch learn.chatgpt.com/docs/build-skills), not in
#      .claude/skills. Fix: single source in .harness/skills-shared/, included
#      by the wrappers of both runtimes.
#   2. completion-gate.py ignored `last_assistant_message` (Codex payload),
#      only covered a Portuguese claim, and accepted a bare "N/M" sentinel without
#      "PASS"/"gaps:". Fix: prioritizes last_assistant_message when present,
#      PT+EN claim regex, the sentinel requires the full format.
#   3. subagent-throttle.sh registered on SubagentStart (an INJECTION event,
#      does not block — confirmed via WebFetch learn.chatgpt.com/docs/hooks)
#      instead of PreToolUse (where spawn_agent can actually be blocked).
#
# Requires `uvx`. Runs outside orions-belt (fixture in $TMPDIR).
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"

FAIL=0
WORK="$(mktemp -d /tmp/codex-parity.XXXXXX)"
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
  echo "SKIP: uvx unavailable — cannot prove the real copier flow"
  exit 77  # SKIP convention (README.md #H4): not a PASS
fi

# =============================================================================
# 0. Real CODEX-ONLY render
# =============================================================================
BASE="$WORK/codex-only"
RENDER_LOG="$WORK/copier.log"
if ! uvx copier copy "$REPO_ROOT" "$BASE" --vcs-ref HEAD \
    --data project_name=codexparity --data owner_name=Tester \
    --data use_codex=true --data use_claude=false \
    --defaults --trust -q > "$RENDER_LOG" 2>&1; then
  echo "FAIL: copier copy --vcs-ref HEAD (codex-only) failed -- $(tail -20 "$RENDER_LOG")"
  exit 1
fi

# --- (a) .claude absent ---
assert "(a) .claude/ does NOT exist in a codex-only install" '[ ! -d "$BASE/.claude" ]'
assert "(a) AGENTS.md exists (Codex instruction)" '[ -f "$BASE/AGENTS.md" ]'
assert "(a) .codex/ exists" '[ -d "$BASE/.codex" ]'
assert "(a) .agents/skills exists" '[ -d "$BASE/.agents/skills" ]'

# =============================================================================
# (b) sub-gap 1 — every skill cited in the rendered AGENTS.md exists in
#     .agents/skills, with valid YAML frontmatter (--- on the 1st line, without
#     a blank line before)
# =============================================================================
# language-neutral (i18n harness_language): captures skill refs in ANY phrasing —
# "skill `x`" (PT), "`x` skill" (EN) and "$x" (invocation, identical in both) — not just the PT phrase.
# Only refs adjacent to "skill"/"$" count (does not catch CSS/hook/token loose in backticks).
CITED="$(grep -oE 'skill `[a-z0-9-]+`|`[a-z0-9-]+` skill|\$[a-z][a-z0-9-]+' "$BASE/AGENTS.md" \
  | sed -E 's/^skill `//; s/` skill$//; s/`//g; s/^\$//' | sort -u)"
assert "(b) AGENTS.md cites at least 5 skills (sanity, language-neutral)" \
  '[ "$(echo "$CITED" | grep -c .)" -ge 5 ]'

for name in $CITED; do
  SKILL_FILE="$BASE/.agents/skills/$name/SKILL.md"
  assert "(b) skill '$name' cited in AGENTS.md exists in .agents/skills/$name/SKILL.md" \
    '[ -f "$SKILL_FILE" ]'
  if [ -f "$SKILL_FILE" ]; then
    assert "(b) skill '$name': frontmatter starts on the 1st line (no blank line before ---)" \
      '[ "$(head -1 "$SKILL_FILE")" = "---" ]'
    assert "(b) skill '$name': frontmatter declares name: $name" \
      "grep -q '^name: $name\$' '$SKILL_FILE'"
  fi
done
# repo-wiki-curator is cited without the "skill \`x\`" pattern (backtick only on the name) — check by name
assert "(b) skill 'repo-wiki-curator' cited explicitly exists in .agents/skills" \
  '[ -f "$BASE/.agents/skills/repo-wiki-curator/SKILL.md" ]'

# --- identical content between .claude and .agents for the same skill (single source) ---
BASE_CLAUDE="$WORK/claude-only"
if ! uvx copier copy "$REPO_ROOT" "$BASE_CLAUDE" --vcs-ref HEAD \
    --data project_name=codexparity --data owner_name=Tester \
    --data use_codex=false --data use_claude=true \
    --defaults --trust -q > "$WORK/copier-claude.log" 2>&1; then
  echo "FAIL: copier copy --vcs-ref HEAD (claude-only) failed -- $(tail -20 "$WORK/copier-claude.log")"
  FAIL=1
else
  for name in grill-me harness-init prova-de-conclusao marathon repo-wiki-curator ui-evidence verify; do
    A="$BASE/.agents/skills/$name/SKILL.md"
    C="$BASE_CLAUDE/.claude/skills/$name/SKILL.md"
    if [ -f "$A" ] && [ -f "$C" ]; then
      assert "(b) skill '$name': .agents and .claude render BYTE-IDENTICAL (single source)" \
        'diff -q "$A" "$C" >/dev/null'
    else
      echo "FAIL: skill '$name' missing in one of the two renders (.agents=$([ -f "$A" ] && echo ok || echo MISSING), .claude=$([ -f "$C" ] && echo ok || echo MISSING))"
      FAIL=1
    fi
  done
  assert "(b) marathon (Codex) does NOT hardcode .claude/runs (uses harness_runs_dir)" \
    '! grep -q "\.claude/runs" "$BASE/.agents/skills/marathon/SKILL.md" || grep -q "harness_runs_dir\|HARNESS_RUNS_DIR" "$REPO_ROOT/copier.yml"'
fi

# =============================================================================
# (c) sub-gap 2 — completion-gate.py with a real Codex payload
# =============================================================================
GATE="$BASE/.harness/hooks/completion-gate.py"
assert "(c) completion-gate.py exists in the render" '[ -f "$GATE" ]'

if [ -f "$GATE" ]; then
  OUT="$(echo '{"stop_hook_active": false, "transcript_path": null, "last_assistant_message": "All done, everything is fixed and 100% complete. Ready for production."}' | python3 "$GATE")"
  EXIT=$?
  assert "(c) Codex payload, EN claim, no sentinel -> exit 2 (blocks)" '[ "$EXIT" -eq 2 ]'

  echo '{"stop_hook_active": false, "transcript_path": null, "last_assistant_message": "Task complete. PROVA-DE-CONCLUSAO: 5/5 PASS, gaps: [nenhum]"}' | python3 "$GATE" >/dev/null 2>&1
  EXIT=$?
  assert "(c) Codex payload, EN claim, WITH full sentinel -> exit 0 (allows)" '[ "$EXIT" -eq 0 ]'

  echo '{"stop_hook_active": false, "transcript_path": null, "last_assistant_message": "All fixed. PROVA-DE-CONCLUSAO: 0/999"}' | python3 "$GATE" >/dev/null 2>&1
  EXIT=$?
  assert "(c) Codex payload, BARE sentinel 0/999 (no PASS/gaps) -> exit 2 (not a valid sentinel)" '[ "$EXIT" -eq 2 ]'

  echo '{"stop_hook_active": false, "transcript_path": null, "last_assistant_message": "I fixed the null check in parser.py line 42."}' | python3 "$GATE" >/dev/null 2>&1
  EXIT=$?
  assert "(c) Codex payload, no plan-level claim -> exit 0" '[ "$EXIT" -eq 0 ]'

  echo '{"stop_hook_active": false, "transcript_path": null, "last_assistant_message": "Plano executado, tudo corrigido, 100%."}' | python3 "$GATE" >/dev/null 2>&1
  EXIT=$?
  assert "(c) regression: PT claim still blocks without a sentinel -> exit 2" '[ "$EXIT" -eq 2 ]'
fi

# =============================================================================
# (d) sub-gap 3 — hooks.json with the throttle on PreToolUse (not SubagentStart)
# =============================================================================
HOOKS_JSON="$BASE/.codex/hooks.json"
assert "(d) .codex/hooks.json exists and is valid JSON" \
  'python3 -c "import json,sys; json.load(open(\"$HOOKS_JSON\"))" 2>/dev/null'

# (d.2) every rendered custom-agent TOML + config.toml must PARSE (regression for the
# adversarial-audit gap: a {#- -#} comment between two keys ate the newline, joining
# `model_reasoning_effort = "high"developer_instructions = """` -> invalid TOML, so the
# Codex custom agent silently failed to load. tomllib is stdlib >=3.11.)
for T in "$BASE"/.codex/agents/*.toml "$BASE"/.codex/config.toml; do
  assert "(d.2) rendered TOML parses: $(basename "$T")" \
    "python3 -c 'import tomllib,sys; tomllib.load(open(sys.argv[1],\"rb\"))' '$T'"
done

if [ -f "$HOOKS_JSON" ]; then
  PRETOOL_HAS_THROTTLE="$(python3 -c "
import json
d = json.load(open('$HOOKS_JSON'))
pre = d['hooks'].get('PreToolUse', [])
print(any('subagent-throttle' in str(entry) for entry in pre))
")"
  assert "(d) PreToolUse registers subagent-throttle.sh" '[ "$PRETOOL_HAS_THROTTLE" = "True" ]'

  PRETOOL_MATCHER_OK="$(python3 -c "
import json
d = json.load(open('$HOOKS_JSON'))
pre = d['hooks'].get('PreToolUse', [])
matchers = [e.get('matcher','') for e in pre if 'subagent-throttle' in str(e)]
print(any('spawn_agent' in m or 'Agent' in m for m in matchers))
")"
  assert "(d) the throttle PreToolUse matcher matches spawn_agent/Agent" '[ "$PRETOOL_MATCHER_OK" = "True" ]'

  SUBAGENTSTART_HAS_THROTTLE="$(python3 -c "
import json
d = json.load(open('$HOOKS_JSON'))
sa = d['hooks'].get('SubagentStart', [])
print(any('subagent-throttle' in str(entry) for entry in sa))
")"
  assert "(d) SubagentStart no longer has the throttle (event does not block)" '[ "$SUBAGENTSTART_HAS_THROTTLE" = "False" ]'
fi

# =============================================================================
# grep of donor/other-owner-project terms = 0 (F9, generic-product
# honesty — reinforced here for the codex-only subset)
# =============================================================================
DONOR_HITS="$(grep -rlEi 'learnhouse|quero|makershub|agent-harness' "$BASE" 2>/dev/null | wc -l)"
assert "grep learnhouse|quero|makershub|agent-harness in the codex-only render = 0" '[ "$DONOR_HITS" -eq 0 ]'

echo
echo "=== summary ==="
if [ "$FAIL" -eq 0 ]; then
  echo "ALL 3 A1/H3 SUB-GAPS CLOSED (codex-only)."
else
  echo "THERE IS STILL AN OPEN GAP — see FAILs above."
fi
exit $FAIL
