#!/usr/bin/env bash
# test_codev_shared_memory.sh — canonizes the CO-DEVELOPMENT premise: Claude and
# Codex work the SAME repo simultaneously, sharing instructions and memory, so a
# round executed by one is visible to the other. The premise is only real if the
# shared state lives in REPO FILES both runtimes read — never in Claude Code's
# native per-user memory (which Codex cannot see). This test locks that in against
# a real full render (both runtimes) via `copier copy --vcs-ref HEAD`.
#
# Requires `uvx`. Fixture in $TMPDIR; never writes into the repo.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
FAIL=0
assert() { if eval "$2"; then echo "PASS: $1"; else echo "FAIL: $1"; FAIL=1; fi; }

if ! command -v uvx >/dev/null 2>&1; then echo "SKIP: uvx unavailable"; exit 77; fi

WORK="$(mktemp -d "${TMPDIR:-/tmp}/codev-shared.XXXXXX")"; trap 'rm -rf "$WORK"' EXIT
F="$WORK/full"
uvx copier copy "$REPO_ROOT" "$F" --vcs-ref HEAD --trust --defaults \
  --data project_name=codev --data owner_name=A \
  --data use_claude=true --data use_codex=true -q > "$WORK/copier.log" 2>&1 \
  || { echo "FAIL: full render failed -- $(tail -20 "$WORK/copier.log")"; exit 1; }

# --- 1. Same instructions: CLAUDE.md (Claude) and AGENTS.md (Codex) are one source ---
assert "instructions single-source: .claude/CLAUDE.md == AGENTS.md (byte-identical)" \
  'diff -q "$F/.claude/CLAUDE.md" "$F/AGENTS.md" >/dev/null'

# --- 2. Both runtimes inject the shared lessons file at SessionStart ---
assert "Claude settings.json SessionStart runs lessons-inject" \
  'python3 -c "import json,sys; d=json.load(open(sys.argv[1])); ss=d.get(chr(104)+\"ooks\",{}).get(\"SessionStart\",[]); sys.exit(0 if any(\"lessons-inject\" in str(e) for e in ss) else 1)" "$F/.claude/settings.json"'
assert "Codex .codex/hooks.json SessionStart runs lessons-inject" \
  'python3 -c "import json,sys; d=json.load(open(sys.argv[1])); ss=d.get(\"hooks\",{}).get(\"SessionStart\",[]); sys.exit(0 if any(\"lessons-inject\" in str(e) for e in ss) else 1)" "$F/.codex/hooks.json"'

# --- 3. Shared memory = single repo files (not per-runtime copies) ---
assert "shared lessons file exists once: tasks/lessons.md" '[ -f "$F/tasks/lessons.md" ]'
assert "shared temporal log exists once: docs/log.md" '[ -f "$F/docs/log.md" ]'
assert "the instructions reference the shared lessons path" 'grep -q "tasks/lessons.md" "$F/AGENTS.md"'
assert "the instructions carry the §16 capture->inject->promote loop" \
  'grep -qE "Self-Improvement Loop|capture . inject . promote" "$F/AGENTS.md"'
assert "lessons-inject reads the config-driven repo file (HARNESS_LESSONS_FILE)" \
  'grep -q "HARNESS_LESSONS_FILE" "$F/.harness/hooks/lessons-inject.sh"'

# --- 4. NO dependency on Claude-native memory (Codex is blind to it) ---
# The shared state must be repo files. A reference to Claude's per-user auto-memory
# would be invisible to Codex and break the premise.
assert "instructions do NOT rely on Claude-native memory (MEMORY.md / ~/.claude memory)" \
  '! grep -qiE "MEMORY\.md|~/\.claude/.*memory|auto-memory|native memory" "$F/AGENTS.md"'

# --- 5. Marathon durable state uses a runtime-neutral shared dir ---
assert "marathon runs dir is runtime-neutral (.harness/runs, not .claude/runs)" \
  'grep -q "\.harness/runs" "$F/.harness/harness.conf" && ! grep -q "HARNESS_RUNS_DIR=.claude/runs" "$F/.harness/harness.conf"'

# --- 6. A skill executed/edited by one runtime is the same file the other reads ---
assert "council skill is byte-identical across .claude and .agents (single source)" \
  'diff -q "$F/.claude/skills/codev-delivery-council/SKILL.md" "$F/.agents/skills/codev-delivery-council/SKILL.md" >/dev/null'

echo
if [ "$FAIL" -eq 0 ]; then echo "RESULT: CO-DEVELOPMENT SHARED-MEMORY PREMISE HELD"; else echo "RESULT: PREMISE VIOLATED"; fi
exit "$FAIL"
