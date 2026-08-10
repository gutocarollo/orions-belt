#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
WORK="$(mktemp -d /tmp/orions-context-delivery.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT
command -v uvx >/dev/null 2>&1 || { echo 'uvx required' >&2; exit 1; }

render() {
  local name="$1"; shift
  uvx copier copy "$ROOT" "$WORK/$name" --vcs-ref HEAD --trust --defaults -q \
    --data project_name=contexttest --data owner_name=Tester --data use_antigravity=false "$@"
}

render off --data use_claude=true --data use_codex=true
[ ! -e "$WORK/off/.harness/context-delivery.enabled" ]
[ -e "$WORK/off/.claude/agents/contexttest-context-scout.md" ]
[ -e "$WORK/off/.codex/agents/contexttest-context-scout.toml" ]
! grep -q 'CONTEXT-PLAN\|CONTEXT-SCOUT-RESULT\|context-delivery' "$WORK/off/.claude/agents/contexttest-context-scout.md"
! grep -q 'CONTEXT-PLAN\|CONTEXT-SCOUT-RESULT\|context-delivery' "$WORK/off/.codex/agents/contexttest-context-scout.toml"
! grep -q '^HARNESS_CONTEXT_DELIVERY_ENABLED=true$' "$WORK/off/.harness/harness.conf"

COMMON=(--data use_context_delivery=true --data use_context_graph=true --data harness_context_provider=codegraph --data use_exploration_protocol=true --data harness_entry_docs=docs/index.md)
render claude --data use_claude=true --data use_codex=false "${COMMON[@]}"
render codex --data use_claude=false --data use_codex=true "${COMMON[@]}"
render both --data use_claude=true --data use_codex=true "${COMMON[@]}"

for d in claude codex both; do
  test -f "$WORK/$d/.harness/context-delivery.enabled"
  python3 -m py_compile "$WORK/$d/.harness/lib/context_predicates.py" "$WORK/$d/.harness/lib/context_provider_probe.py" "$WORK/$d/.harness/lib/context_routing.py" "$WORK/$d/.harness/lib/context_evidence.py" "$WORK/$d/.harness/hooks/context-tool-ledger.py"
  grep -q '^HARNESS_CONTEXT_DELIVERY_ENABLED=true$' "$WORK/$d/.harness/harness.conf"
  grep -q 'F5' "$WORK/$d/.agents/skills/exploration-protocol/SKILL.md" 2>/dev/null || grep -q 'F5' "$WORK/$d/.claude/skills/exploration-protocol/SKILL.md"
  ! grep -q 'fork is MANDATORY and PARALLEL' "$WORK/$d/AGENTS.md" 2>/dev/null || false
  git -C "$WORK/$d" init -q
  git -C "$WORK/$d" config user.email test@example.invalid
  git -C "$WORK/$d" config user.name Test
  git -C "$WORK/$d" add -A
  git -C "$WORK/$d" commit -qm baseline
  (cd "$WORK/$d" && python3 .harness/lib/tests/test_context_delivery.py)
done

python3 - <<'PY' "$WORK/claude/.claude/settings.json" "$WORK/codex/.codex/hooks.json" "$WORK/both/.claude/settings.json" "$WORK/both/.codex/hooks.json"
import json,sys
for path in sys.argv[1:]:
    json.load(open(path))
PY
python3 - <<'PY' "$WORK/codex/.codex/config.toml" "$WORK/codex/.codex/agents/contexttest-context-scout.toml" "$WORK/both/.codex/config.toml"
import sys,tomllib
for path in sys.argv[1:]:
    data=tomllib.load(open(path,'rb'))
    if path.endswith('config.toml'):
        agents=data['agents']
        assert 'max_concurrent_threads_per_session' in agents
        assert 'max_threads' not in agents and 'max_depth' not in agents
PY

python3 - <<'PYMCP' "$WORK/claude/.mcp.json" "$WORK/both/.mcp.json"
import json,sys
for path in sys.argv[1:]:
    data=json.load(open(path))
    server=data["mcpServers"]["codegraph"]
    assert server["command"]=="codegraph"
    assert server["args"]==["serve","--mcp"]
PYMCP
grep -q '^model: sonnet$' "$WORK/claude/.claude/agents/contexttest-context-scout.md"
grep -q '^model: haiku$' "$WORK/claude/.claude/agents/contexttest-context-shard.md"
grep -q 'model = "gpt-5.6-terra"' "$WORK/codex/.codex/agents/contexttest-context-scout.toml"
grep -q 'model = "gpt-5.6-luna"' "$WORK/codex/.codex/agents/contexttest-context-shard.toml"
grep -q 'mcp__codegraph__' "$WORK/claude/.claude/agents/contexttest-context-scout.md" && { echo 'Claude scout unexpectedly has narrow CodeGraph allowlist' >&2; exit 1; } || true
grep -q 'disallowedTools:' "$WORK/claude/.claude/agents/contexttest-context-scout.md"
grep -q '^\[mcp_servers.codegraph\]$' "$WORK/codex/.codex/config.toml"

echo 'context-delivery-regression-ok'
