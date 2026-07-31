#!/usr/bin/env bash
# Task-start routing, the clarification precondition, and the push gate — the three capabilities
# added in the 2026-07-31 donor sync. What this locks:
#
#   1. Per-PARAMETER gating, not per-capability: a phase whose parameter is empty must not be
#      emitted, and a push gate with no command must not exist at all. A route pointing at nothing
#      trains the agent to skim the block — the same defect `use_hookify` fixed for inert rules.
#   2. The exploration block is a COMPLEMENT to the blast-radius block, never a duplicate: one is
#      task-start ("where do I read first"), the other is diff-time ("what breaks if I change
#      this"). Both must be able to exist at once, and each must survive the other being off.
#   3. Commands are interpolated VERBATIM into the generated githook. A real bug caught in this
#      round: `| tojson` is HTML-safe and turns `'` into `&#39;`, so `make test ARGS='x'` became a
#      command that `bash -n` ACCEPTS and that executes wrong. Quotes must survive byte-for-byte.
#   4. The hooks fail open and stay silent outside their trigger — a prompt hook that talks on
#      every message competes with the real work for context.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
WORK="$(mktemp -d /tmp/orions-exploration.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT
FAIL=0

assert() { if eval "$2"; then echo "PASS: $1"; else echo "FAIL: $1"; FAIL=1; fi; }
command -v uvx >/dev/null 2>&1 || { echo "SKIP: uvx unavailable"; exit 77; }

render() {
  local dst="$1"; shift
  uvx copier copy "$REPO_ROOT" "$dst" --trust --defaults --vcs-ref HEAD \
    --data project_name=explore-test --data owner_name=Tester "$@" >/dev/null 2>&1 || {
      echo "FAIL: render failed for $dst" >&2
      return 1
    }
}

DOCS="docs/index.md,docs/log.md,docs/pending/README.md"
REFIDX="docs/reference/README.md"

# =============================================================================
# 1. Off by default — an unconfigured capability must leave ZERO artifacts.
# =============================================================================
OFF="$WORK/off"
render "$OFF" --data use_claude=true --data use_codex=true || exit 1
assert "exploration is opt-in: no kickoff hook by default" \
  '[ ! -f "$OFF/.harness/hooks/exploration-kickoff.py" ]'
assert "exploration is opt-in: no skill by default" \
  '[ ! -d "$OFF/.claude/skills/exploration-protocol" ]'
assert "exploration is opt-in: no canonical block by default" \
  '! grep -q "task-start" "$OFF/AGENTS.md"'
assert "exploration is opt-in: no config keys by default" \
  '! grep -q "HARNESS_ENTRY_DOCS" "$OFF/.harness/harness.conf"'
assert "exploration is opt-in: the scout is not rewritten by default" \
  '! grep -q "F1-bis" "$OFF/.claude/agents/explore-test-context-scout.md"'
assert "push gate is opt-in: no pre-push githook without a test command" \
  '[ ! -f "$OFF/.githooks/pre-push" ]'
# The clarification gate is the exception, and deliberately so: it needs no project-specific
# input, so leaving it off by default would be leaving a free guard on the table.
assert "clarification gate ships on by default (no project input needed)" \
  '[ -f "$OFF/.harness/hooks/clarification-plan-gate.py" ]'
assert "clarification skill ships unconditionally" \
  '[ -f "$OFF/.claude/skills/clarification-plan/SKILL.md" ]'

# =============================================================================
# 2. Fully configured — every phase present, both runtimes, parameters interpolated.
# =============================================================================
FULL="$WORK/full"
render "$FULL" --data use_claude=true --data use_codex=true \
  --data use_exploration_protocol=true --data harness_entry_docs="$DOCS" \
  --data harness_reference_index="$REFIDX" \
  --data use_context_graph=true --data harness_core_paths="src/core/" \
  --data harness_mcp_db_dev_port=18120 || exit 1

assert "kickoff hook is generated" '[ -f "$FULL/.harness/hooks/exploration-kickoff.py" ]'
assert "kickoff hook is valid python" 'python3 -m py_compile "$FULL/.harness/hooks/exploration-kickoff.py"'
assert "skill reaches the Claude surface" '[ -f "$FULL/.claude/skills/exploration-protocol/SKILL.md" ]'
assert "skill reaches the Codex/Antigravity surface" '[ -f "$FULL/.agents/skills/exploration-protocol/SKILL.md" ]'
assert "canonical block reaches AGENTS.md" 'grep -q "task-start" "$FULL/AGENTS.md"'
assert "canonical block reaches CLAUDE.md" 'grep -q "task-start" "$FULL/.claude/CLAUDE.md"'
assert "entry docs are materialised in config" 'grep -Fq "HARNESS_ENTRY_DOCS=$DOCS" "$FULL/.harness/harness.conf"'
assert "reference index is materialised in config" 'grep -Fq "HARNESS_REFERENCE_INDEX=$REFIDX" "$FULL/.harness/harness.conf"'
assert "the ordered route survives into the block" \
  'grep -q "docs/index.md.*docs/log.md.*docs/pending/README.md" "$FULL/AGENTS.md"'
assert "the scout carries the route (Claude)" 'grep -q "F1-bis" "$FULL/.claude/agents/explore-test-context-scout.md"'
assert "the scout carries the route (Codex)" 'grep -q "F1-bis" "$FULL/.codex/agents/explore-test-context-scout.toml"'
assert "the Codex scout is still valid TOML" \
  'python3 -c "import tomllib,sys; tomllib.load(open(sys.argv[1],\"rb\"))" "$FULL/.codex/agents/explore-test-context-scout.toml"'
assert "the kickoff hook is wired on UserPromptSubmit" \
  'python3 -c "
import json,sys
s=json.load(open(sys.argv[1]))
cmds=[h[\"command\"] for m in s[\"hooks\"][\"UserPromptSubmit\"] for h in m[\"hooks\"]]
sys.exit(0 if any(\"exploration-kickoff\" in c for c in cmds) else 1)" "$FULL/.claude/settings.json"'
assert "the clarification gate is wired on AskUserQuestion" \
  'python3 -c "
import json,sys
s=json.load(open(sys.argv[1]))
hit=[m for m in s[\"hooks\"][\"PreToolUse\"] if m.get(\"matcher\")==\"AskUserQuestion\"]
sys.exit(0 if hit else 1)" "$FULL/.claude/settings.json"'

# =============================================================================
# 3. The two blocks are complementary, and each survives the other being off.
# =============================================================================
assert "both blocks coexist when both capabilities are on" \
  '[ "$(grep -c "⭐" "$FULL/AGENTS.md")" -ge 2 ] && grep -q "blast radius" "$FULL/AGENTS.md"'
assert "the task-start block names the diff-time handoff instead of repeating it" \
  'grep -qi "diff-time\|diff começa\|diff begins" "$FULL/AGENTS.md"'

NOGRAPH="$WORK/no-graph"
render "$NOGRAPH" --data use_claude=true --data use_codex=false \
  --data use_exploration_protocol=true --data harness_entry_docs="$DOCS" || exit 1
assert "exploration survives without the code graph" 'grep -q "task-start" "$NOGRAPH/.claude/CLAUDE.md"'
assert "no blast-radius block when the graph capability is off" \
  '! grep -q "blast radius" "$NOGRAPH/.claude/CLAUDE.md"'
assert "the F2 phase degrades to grep and SAYS what is lost" \
  'grep -qi "homonym\|homônimo" "$NOGRAPH/.claude/skills/exploration-protocol/SKILL.md"'

# =============================================================================
# 4. Per-parameter gating INSIDE the capability — the point of the test.
# =============================================================================
NOREF="$WORK/no-refindex"
render "$NOREF" --data use_claude=true --data use_codex=false \
  --data use_exploration_protocol=true --data harness_entry_docs="$DOCS" || exit 1
assert "F1 present when entry docs are set" 'grep -q "docs/index.md" "$NOREF/.claude/CLAUDE.md"'
assert "NO F1-bis phase when the reference index is empty" \
  '! grep -q "F1-bis" "$NOREF/.claude/CLAUDE.md"'
assert "the hook drops F1-bis too" \
  '! grep -q "F1-bis" "$NOREF/.harness/hooks/exploration-kickoff.py"'

NODOCS="$WORK/no-entry-docs"
render "$NODOCS" --data use_claude=true --data use_codex=false \
  --data use_exploration_protocol=true --data harness_reference_index="$REFIDX" || exit 1
assert "NO F1 phase when entry docs are empty" '! grep -q "F1 canonical\|F1 docs" "$NODOCS/.claude/CLAUDE.md"'
assert "F1-bis still present on its own" 'grep -q "F1-bis" "$NODOCS/.claude/CLAUDE.md"'

# =============================================================================
# 5. Hook behaviour — fires on a task, silent otherwise, fail-open on junk.
# =============================================================================
HOOK="$FULL/.harness/hooks/exploration-kickoff.py"
assert "kickoff fires on a substantive task prompt" \
  'printf "%s" "{\"prompt\":\"investigate the inbound worker and fix the coalescing bug\"}" | python3 "$HOOK" | grep -q "EXPLORATION STANDARD"'
assert "kickoff is silent on a short prompt" \
  '[ -z "$(printf "%s" "{\"prompt\":\"continue\"}" | python3 "$HOOK")" ]'
assert "kickoff is silent on a non-task prompt" \
  '[ -z "$(printf "%s" "{\"prompt\":\"what is the current status of the deployment pipeline here\"}" | python3 "$HOOK")" ]'
assert "kickoff is silent once the user names the protocol" \
  '[ -z "$(printf "%s" "{\"prompt\":\"implement the parser following exploration-protocol please\"}" | python3 "$HOOK")" ]'
assert "kickoff fails open on malformed json" \
  'printf "%s" "not json at all" | python3 "$HOOK" >/dev/null 2>&1'

GATE="$FULL/.harness/hooks/clarification-plan-gate.py"
TRANSCRIPT="$WORK/transcript.jsonl"
printf '%s\n' '{"role":"assistant","content":"working"}' > "$TRANSCRIPT"
assert "clarification gate BLOCKS AskUserQuestion when the skill was never loaded" \
  'printf "%s" "{\"tool_name\":\"AskUserQuestion\",\"transcript_path\":\"$TRANSCRIPT\"}" | python3 "$GATE" >/dev/null 2>&1; [ $? -eq 2 ]'
printf '%s\n' '{"role":"assistant","content":"Skill(skill=\"clarification-plan\")"}' >> "$TRANSCRIPT"
assert "clarification gate ALLOWS it once the skill is in the transcript" \
  'printf "%s" "{\"tool_name\":\"AskUserQuestion\",\"transcript_path\":\"$TRANSCRIPT\"}" | python3 "$GATE" >/dev/null 2>&1'
assert "clarification gate ignores every other tool" \
  'printf "%s" "{\"tool_name\":\"Edit\",\"transcript_path\":\"/does/not/exist\"}" | python3 "$GATE" >/dev/null 2>&1'
assert "clarification gate fails OPEN when the transcript is missing" \
  'printf "%s" "{\"tool_name\":\"AskUserQuestion\",\"transcript_path\":\"/does/not/exist\"}" | python3 "$GATE" >/dev/null 2>&1'

# =============================================================================
# 6. Push gate — verbatim interpolation and the skip-never-block rule.
# =============================================================================
PUSH="$WORK/push"
render "$PUSH" --data use_claude=true --data use_codex=false \
  --data harness_pre_push_test_command='pytest -q -m "not slow"' \
  --data harness_pre_push_slow_command="make test-db ARGS='tests/db/'" \
  --data harness_pre_push_slow_probe='pg_isready -h localhost -p 5432 -q' || exit 1
assert "pre-push githook is generated when a command exists" '[ -f "$PUSH/.githooks/pre-push" ]'
assert "pre-push is valid shell" 'bash -n "$PUSH/.githooks/pre-push"'
# The regression this guards: `| tojson` rendered `'` as `&#39;` — valid shell, wrong command.
assert "double quotes survive interpolation byte-for-byte" \
  'grep -Fq "pytest -q -m \"not slow\"" "$PUSH/.githooks/pre-push"'
assert "single quotes survive interpolation byte-for-byte" \
  "grep -Fq \"make test-db ARGS='tests/db/'\" \"\$PUSH/.githooks/pre-push\""
assert "no html entity leaked into the generated hook" '! grep -q "&#" "$PUSH/.githooks/pre-push"'
assert "the probe gates the expensive suite" 'grep -Fq "pg_isready -h localhost -p 5432 -q" "$PUSH/.githooks/pre-push"'
assert "the declared bypass exists" 'grep -q "PUSH_GATE_ACK" "$PUSH/.githooks/pre-push"'
assert "the bypass short-circuits with exit 0" \
  '( cd "$PUSH" && git init -q . >/dev/null 2>&1; PUSH_GATE_ACK=reason bash .githooks/pre-push >/dev/null 2>&1 )'

NOSLOW="$WORK/push-fast-only"
render "$NOSLOW" --data use_claude=true --data use_codex=false \
  --data harness_pre_push_test_command='npm test' || exit 1
# Anchored on the RUNTIME marker, not on the word: "suite cara" also appears in the provenance
# comment at the top of the hook, so a bare grep matches the prose and reports a stage that is not
# there (a pattern search matching its own documentation — caught in this round).
assert "the expensive stage is absent when its command is empty" \
  '! grep -q "rodando a suite cara" "$NOSLOW/.githooks/pre-push"'
assert "the fast stage is still there" 'grep -Fq "npm test" "$NOSLOW/.githooks/pre-push"'

# =============================================================================
# 6b. pre-commit extension point — the escape hatch for an `owned` file.
# Without it, a project needing its own gate had to EDIT the hook, and the edit makes the next
# install abort with "locally modified" — the project leaves the template cycle permanently.
# =============================================================================
PCX="$WORK/pre-commit-extra"
render "$PCX" --data use_claude=true --data use_codex=false \
  --data harness_pre_commit_extra_command='python3 scripts/check_docs.py --staged' || exit 1
assert "the extra gate lands between the two framework lints" \
  'python3 -c "
import sys
lines = open(sys.argv[1]).read().splitlines()
def idx(needle):
    return next(i for i, l in enumerate(lines) if needle in l and not l.lstrip().startswith(\"#\"))
sys.exit(0 if idx(\"docs_wiki_lint.py\") < idx(\"check_docs.py\") < idx(\"ref_integrity.py\") else 1)" "$PCX/.githooks/pre-commit"'
# Both checks read the EXECUTABLE line only, never the whole file. Two reasons, both measured here:
# the provenance comment above the line legitimately contains the string `&#39;` (it documents the
# tojson bug), so a file-wide entity grep matches its own documentation; and `$?` inside a
# double-quoted assert is expanded by the shell before grep ever sees it.
assert "the extra gate is interpolated verbatim and propagates its exit code" \
  'python3 -c "
import sys
line = next(l for l in open(sys.argv[1]).read().splitlines() if l.startswith(\"( \"))
ok = line == \"( python3 scripts/check_docs.py --staged ) || exit \" + chr(36) + chr(63)
sys.exit(0 if ok else 1)" "$PCX/.githooks/pre-commit"'
assert "no html entity leaks into the executable line" \
  'python3 -c "
import sys
line = next(l for l in open(sys.argv[1]).read().splitlines() if l.startswith(\"( \"))
sys.exit(1 if \"&#\" in line else 0)" "$PCX/.githooks/pre-commit"'
assert "pre-commit is still valid shell with the extension" 'bash -n "$PCX/.githooks/pre-commit"'
assert "NO extra stage when the parameter is empty" \
  '! grep -q "PONTO DE EXTENSAO\|PONTO DE EXTENSÃO" "$OFF/.githooks/pre-commit"'
assert "the two framework lints survive an empty parameter" \
  'grep -q "docs_wiki_lint.py" "$OFF/.githooks/pre-commit" && grep -q "ref_integrity.py" "$OFF/.githooks/pre-commit"'

# =============================================================================
# 7. The scanner classifies the new components, and never silently APLICAVEL.
# =============================================================================
SCAN="$(cd "$FULL" && python3 .harness/lib/scan_project.py classify 2>/dev/null)"
check_status() {
  printf "%s" "$SCAN" | python3 -c "
import json,sys
rows = json.load(sys.stdin)['components']
hit = [r for r in rows if r['component'] == sys.argv[1]]
sys.exit(0 if hit and hit[0]['status'] == sys.argv[2] else 1)" "$1" "$2"
}
assert "scanner marks the exploration hook CONDICIONAL (the route is not inferable)" \
  'check_status hook.exploration-kickoff CONDICIONAL'
assert "scanner marks the exploration skill CONDICIONAL" \
  'check_status skill.exploration-protocol CONDICIONAL'
assert "scanner marks the push gate CONDICIONAL (a framework is not an entrypoint)" \
  'check_status githook.pre-push CONDICIONAL'
assert "scanner marks the clarification gate APLICAVEL (needs no project input)" \
  'check_status hook.clarification-plan-gate APLICAVEL'

exit "$FAIL"
