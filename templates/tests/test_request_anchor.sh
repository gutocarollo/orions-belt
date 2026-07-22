#!/usr/bin/env bash
# test_request_anchor.sh — the Original Request Anchor: capture the user's verbatim
# request, re-inject it at SessionStart (beating context compaction), and force
# every adversarial review to confront the ORIGINAL objective (estimand fidelity),
# not the drifted derived plan — the "reviewed the wrong thing correctly" failure.
# Runs against a REAL full render (both runtimes) via copier --vcs-ref HEAD.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
FAIL=0
assert() { if eval "$2"; then echo "PASS: $1"; else echo "FAIL: $1"; FAIL=1; fi; }

if ! command -v uvx >/dev/null 2>&1; then echo "SKIP: uvx unavailable"; exit 77; fi

WORK="$(mktemp -d "${TMPDIR:-/tmp}/req-anchor.XXXXXX")"; trap 'rm -rf "$WORK"' EXIT
F="$WORK/full"
uvx copier copy "$REPO_ROOT" "$F" --vcs-ref HEAD --trust --defaults \
  --data project_name=anchor --data owner_name=A \
  --data use_claude=true --data use_codex=true -q > "$WORK/copier.log" 2>&1 \
  || { echo "FAIL: full render failed -- $(tail -20 "$WORK/copier.log")"; exit 1; }

# --- 1. Both hooks materialize and are registered in BOTH runtimes ---
assert "request-ledger.py materialized" '[ -f "$F/.harness/hooks/request-ledger.py" ]'
assert "request-reinject.py materialized" '[ -f "$F/.harness/hooks/request-reinject.py" ]'
assert "Claude UserPromptSubmit runs request-ledger" \
  'python3 -c "import json,sys;d=json.load(open(sys.argv[1]));ups=d[chr(104)+\"ooks\"][\"UserPromptSubmit\"];sys.exit(0 if any(\"request-ledger\" in str(e) for e in ups) else 1)" "$F/.claude/settings.json"'
assert "Claude SessionStart runs request-reinject" \
  'python3 -c "import json,sys;d=json.load(open(sys.argv[1]));ss=d[chr(104)+\"ooks\"][\"SessionStart\"];sys.exit(0 if any(\"request-reinject\" in str(e) for e in ss) else 1)" "$F/.claude/settings.json"'
assert "Codex UserPromptSubmit runs request-ledger" \
  'python3 -c "import json,sys;d=json.load(open(sys.argv[1]));ups=d[\"hooks\"][\"UserPromptSubmit\"];sys.exit(0 if any(\"request-ledger\" in str(e) for e in ups) else 1)" "$F/.codex/hooks.json"'
assert "Codex SessionStart runs request-reinject" \
  'python3 -c "import json,sys;d=json.load(open(sys.argv[1]));ss=d[\"hooks\"][\"SessionStart\"];sys.exit(0 if any(\"request-reinject\" in str(e) for e in ss) else 1)" "$F/.codex/hooks.json"'

# --- 2. Capture behavior: ANCHOR then amendment, trivial skipped, verbatim ---
export CLAUDE_PROJECT_DIR="$F"
echo '{"prompt":"implemente o takeover que acumula contexto e solta na mao do agente","session_id":"t1"}' | python3 "$F/.harness/hooks/request-ledger.py"
echo '{"prompt":"os sinteticos injetados devem ser considerados reais","session_id":"t1"}' | python3 "$F/.harness/hooks/request-ledger.py"
echo '{"prompt":"continue","session_id":"t1"}' | python3 "$F/.harness/hooks/request-ledger.py"
L="$F/.harness/requests/session-t1.md"
assert "ledger created" '[ -f "$L" ]'
assert "first prompt recorded as ANCHOR" 'grep -qE "^## \[.*\] ANCHOR" "$L"'
assert "second prompt recorded as amendment" 'grep -qE "^## \[.*\] amendment" "$L"'
assert "verbatim objective preserved" 'grep -q "solta na mao do agente" "$L"'
assert "trivial ack (continue) NOT recorded" '[ "$(grep -cE "^## \[.*\] amendment" "$L")" -eq 1 ] && ! grep -qxF "continue" "$L"'

# --- 3. Re-injection surfaces the ANCHOR + the blocking directive ---
OUT="$(python3 "$F/.harness/hooks/request-reinject.py")"
assert "reinject emits the anchor block" 'printf "%s" "$OUT" | grep -q "original-request-anchor"'
assert "reinject carries the verbatim objective" 'printf "%s" "$OUT" | grep -q "solta na mao do agente"'
assert "reinject states silent substitution is BLOCKING" 'printf "%s" "$OUT" | grep -qi "BLOCKING"'
# CURRENT-TASK.md takes priority over the ledger
printf "# obj\n\nprovar resposta no cutoff\n" > "$F/.harness/requests/CURRENT-TASK.md"
assert "CURRENT-TASK.md overrides the ledger anchor" \
  'python3 "$F/.harness/hooks/request-reinject.py" | grep -q "provar resposta no cutoff"'
unset CLAUDE_PROJECT_DIR

# --- 4. Contract enforcement: the reviewer + council mandate estimand fidelity ---
REV="$F/.agents/skills/adversarial-review/SKILL.md"
COU="$F/.agents/skills/anchor-delivery-council/SKILL.md"
assert "adversarial-review has the §1.0 estimand-fidelity axis" \
  'grep -qi "estimand fidelity" "$REV"'
assert "adversarial-review reads the request anchor file" \
  'grep -q "requests/CURRENT-TASK.md" "$REV" || grep -q "requests/session-" "$REV"'
assert "adversarial-review calls silent substitution BLOQUEANTE" \
  'grep -qi "silently drift\|silently substituted\|substitution" "$REV" && grep -q "BLOQUEANTE" "$REV"'
assert "council writes/handles CURRENT-TASK.md and hands it to the reviewer" \
  'grep -q "CURRENT-TASK.md" "$COU"'

# --- 5. Anchor ledger is git-ignored (verbatim prompts, possibly sensitive) ---
assert ".harness/requests/ is git-ignored in the seed" 'grep -q "\.harness/requests/" "$F/.gitignore"'

echo
if [ "$FAIL" -eq 0 ]; then echo "RESULT: ORIGINAL REQUEST ANCHOR PASSED"; else echo "RESULT: FAILURES"; fi
exit "$FAIL"
