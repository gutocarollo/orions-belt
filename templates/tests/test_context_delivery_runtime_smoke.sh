#!/usr/bin/env bash
set -euo pipefail

[ "${ORIONS_RUNTIME_SMOKE:-0}" = 1 ] || {
  echo 'SKIP: set ORIONS_RUNTIME_SMOKE=1 to authorize real Claude/Codex calls'
  exit 77
}
RUNTIME_SMOKE_TARGET="${RUNTIME_SMOKE_TARGET:-all}"
case "$RUNTIME_SMOKE_TARGET" in
  all) required_commands=(uvx claude codex codegraph) ;;
  claude) required_commands=(uvx claude codegraph) ;;
  codex) required_commands=(uvx codex codegraph) ;;
  *) echo "BLOCKED: RUNTIME_SMOKE_TARGET must be all, claude or codex" >&2; exit 1 ;;
esac
for cmd in "${required_commands[@]}"; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "BLOCKED: $cmd missing" >&2; exit 1; }
done

run_timed() {
  local seconds="$1"; shift
  python3 - "$seconds" "$@" <<'PY'
import subprocess, sys
try:
    result = subprocess.run(sys.argv[2:], timeout=float(sys.argv[1]))
except subprocess.TimeoutExpired:
    raise SystemExit(124)
raise SystemExit(result.returncode)
PY
}

assert_runtime_receipts() {
  local runtime="$1"
  python3 - "$runtime" "$PWD" <<'PY'
import json,pathlib,sys
runtime,root=sys.argv[1],pathlib.Path(sys.argv[2])
sys.path.insert(0, str(root / ".harness/lib"))
from context_provider_probe import parse_codegraph_status
lifecycle=[json.loads(line) for path in (root/".harness/runs/subagents").rglob("*.jsonl") for line in path.read_text().splitlines() if line.strip()]
tools=[json.loads(line) for path in (root/".harness/runs/context-tools").rglob("*.jsonl") for line in path.read_text().splitlines() if line.strip()]
sessions={item.get("session_id") for item in lifecycle if item.get("agent_type")=="runtimesmoke-context-scout"}
assert len(sessions)==1 and None not in sessions and "" not in sessions, sessions
session=next(iter(sessions))
posts={item["tool_use_id"]:item for item in tools if item.get("event")=="PostToolUse" and item.get("session_id")==session}
pres={item["tool_use_id"]:item for item in tools if item.get("event")=="PreToolUse" and item.get("session_id")==session}
statuses=[item for item in posts.values() if item.get("methods")==["codegraph-status"] and not item.get("agent_id") and not item.get("agent_type")]
graphs=[item for item in posts.values() if "codegraph" in item.get("methods",[]) and item.get("agent_type")=="runtimesmoke-context-scout"]
reads=[item for item in posts.values() if "targeted-read" in item.get("methods",[]) and item.get("agent_type")=="runtimesmoke-context-scout"]
assert len(statuses)==1, statuses
assert graphs, posts
assert reads, posts
status=statuses[0]
derived=parse_codegraph_status(status["response_excerpt"])
assert derived["index_fresh"] is True and derived["pending_changes"]==0, derived
assert pres[status["tool_use_id"]]["seq"] < status["seq"] < min(pres[item["tool_use_id"]]["seq"] for item in graphs)
assert any(item.get("event")=="SubagentStart" for item in lifecycle)
assert any(item.get("event")=="SubagentStop" for item in lifecycle)
assert all(item.get("runtime")==runtime for item in lifecycle+tools)
PY
}

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
WORK="$(mktemp -d /tmp/orions-context-runtime.XXXXXX)"
cleanup() {
  local rc=$?
  if [ "$rc" -ne 0 ] && [ "${KEEP_RUNTIME_SMOKE_WORK:-0}" = 1 ]; then
    echo "runtime smoke artifacts retained at $WORK" >&2
  else
    rm -rf "$WORK"
  fi
}
trap cleanup EXIT
uvx copier copy "$ROOT" "$WORK/project" --vcs-ref HEAD --trust --defaults -q \
  --data project_name=runtimesmoke --data owner_name=Tester --data use_antigravity=false \
  --data use_claude=true --data use_codex=true --data use_context_delivery=true \
  --data use_context_graph=true --data harness_context_provider=codegraph
cd "$WORK/project"
git init -q
git config user.email smoke@example.invalid
git config user.name Smoke
printf '%s\n' 'runtime-marker' > marker.txt
git add -A
git commit -qm baseline
codegraph init -i >"$WORK/codegraph-init.log" 2>&1

SOURCE_CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
CODEX_SMOKE_HOME="$WORK/codex-home"
SMOKE_HOME="$WORK/home"
REAL_PROJECT="$(pwd -P)"
test -f "$SOURCE_CODEX_HOME/auth.json" || { echo "BLOCKED: Codex auth.json missing" >&2; exit 1; }
mkdir -p "$CODEX_SMOKE_HOME" "$SMOKE_HOME"
ln -s "$SOURCE_CODEX_HOME/auth.json" "$CODEX_SMOKE_HOME/auth.json"
printf '[projects."%s"]\ntrust_level = "trusted"\n' "$REAL_PROJECT" > "$CODEX_SMOKE_HOME/config.toml"

if [ "$RUNTIME_SMOKE_TARGET" != codex ]; then
# Negative control: a Codex TOML is not a Claude custom-agent registration.
cp .claude/agents/runtimesmoke-context-scout.md "$WORK/claude-agent.md"
rm .claude/agents/runtimesmoke-context-scout.md
rm -rf .harness/runs/subagents .harness/runs/context-tools
set +e
run_timed 180 claude -p '@agent-runtimesmoke-context-scout Return exactly NEGATIVE-CONTROL.' \
  --setting-sources project --output-format json --max-turns 4 >"$WORK/claude-negative.json" 2>"$WORK/claude-negative.err"
negative_rc=$?
set -e
if find .harness/runs/subagents -type f -name '*.jsonl' -print 2>/dev/null | xargs -r grep -q 'runtimesmoke-context-scout'; then
  echo 'FAIL: Claude registered a Codex-only TOML agent' >&2
  exit 1
fi
echo "Claude negative control: no native scout lifecycle (rc=$negative_rc)"

# Positive Claude control: coordinator CLI freshness, native Markdown agent,
# real Read and operational CodeGraph MCP calls.
cp "$WORK/claude-agent.md" .claude/agents/runtimesmoke-context-scout.md
rm -rf .harness/runs/subagents .harness/runs/context-tools
set +e
run_timed 300 claude -p 'First use Bash yourself to execute exactly `codegraph status --json`. If and only if it proves a fresh index with zero pending changes, delegate exactly once to the native runtimesmoke-context-scout agent. Give the scout CONTEXT-PLAN KNOWN_SYMBOL_IMPACT with required methods targeted-read and codegraph. The scout must use Read on marker.txt and one operational CodeGraph MCP search/explore call for runtime-marker, but must not invoke status or Bash. Then return exactly CLAUDE-POSITIVE.' \
  --setting-sources project --output-format json --max-turns 12 >"$WORK/claude-positive.json" 2>"$WORK/claude-positive.err"
positive_rc=$?
set -e
[ "$positive_rc" -eq 0 ] || { cat "$WORK/claude-positive.err" >&2; exit 1; }
python3 - "$WORK/claude-positive.json" <<'PY'
import json,sys
result=json.load(open(sys.argv[1]))
if result.get("is_error") or result.get("api_error_status"):
    raise SystemExit(f"Claude runtime blocked: {result.get('result') or result}")
PY
grep -R -q '"event": "SubagentStart"' .harness/runs/subagents
grep -R -q '"event": "SubagentStop"' .harness/runs/subagents
grep -R -q '"agent_type": "runtimesmoke-context-scout"' .harness/runs/subagents
grep -R -Eq '"model": "[^" ]+"' .harness/runs/subagents
assert_runtime_receipts claude
fi

if [ "$RUNTIME_SMOKE_TARGET" != claude ]; then
# Positive Codex control: coordinator CLI freshness, named role, real Read and
# operational CodeGraph MCP calls.
rm -rf .harness/runs/subagents .harness/runs/context-tools
set +e
HOME="$SMOKE_HOME" CODEX_HOME="$CODEX_SMOKE_HOME" run_timed 360 codex exec --json --sandbox workspace-write --ignore-rules --dangerously-bypass-hook-trust -c 'model_reasoning_effort="high"' \
  'Use tools in this exact order. Step 1: call exec_command once with exactly `codegraph status --json`. Its hook injects a session-bound codex_context_receipts.py command. Step 2: if fresh, call spawn_agent exactly once with agent_type runtimesmoke-context-scout, fork_turns none, and task: use the read tool on marker.txt, then use the configured CodeGraph MCP operational explore tool for runtime-marker, return CODEX-POSITIVE, make no writes, do not spawn. A full-history fork is forbidden because custom agent types require fork_turns none or a bounded positive value. Step 3: wait for that exact non-empty agent id. Step 4: run exactly the session-bound codex_context_receipts.py command injected in step 1. Never call wait before a successful spawn_agent and never claim delegation without a non-empty receiver id. Then return exactly CODEX-POSITIVE.' \
  >"$WORK/codex-positive.jsonl" 2>"$WORK/codex-positive.err"
codex_rc=$?
set -e
[ "$codex_rc" -eq 0 ] || { cat "$WORK/codex-positive.err" >&2; exit 1; }
grep -R -q '"event": "SubagentStart"' .harness/runs/subagents
grep -R -q '"event": "SubagentStop"' .harness/runs/subagents
grep -R -q '"agent_type": "runtimesmoke-context-scout"' .harness/runs/subagents
grep -R -Eq '"model": "[^" ]+"' .harness/runs/subagents
assert_runtime_receipts codex
fi

echo "context-delivery-${RUNTIME_SMOKE_TARGET}-runtime-smoke-ok"
