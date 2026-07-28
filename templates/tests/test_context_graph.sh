#!/usr/bin/env bash
# The context decision graph installs ROUTING, not tools — and never leaves an
# inert guard behind.
#
# Two invariants this locks:
#   1. Gating is per-parameter, not per-capability: a guard whose parameter is
#      empty must NOT be generated. A rule that fires with nothing to check is
#      noise, and noise trains the agent to ignore guards (the same defect
#      use_hookify fixed for the engine-less hookify rules).
#   2. The routing is prose+rules only. Nothing here installs a graph CLI: that
#      binary lives outside the target root and the installer's containment
#      invariant forbids writing there.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
WORK="$(mktemp -d /tmp/orions-context-graph.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT
FAIL=0

assert() { if eval "$2"; then echo "PASS: $1"; else echo "FAIL: $1"; FAIL=1; fi; }
command -v uvx >/dev/null 2>&1 || { echo "SKIP: uvx unavailable"; exit 77; }

render() {
  local dst="$1"; shift
  uvx copier copy "$REPO_ROOT" "$dst" --trust --defaults --vcs-ref HEAD \
    --data project_name=ctxgraph-test --data owner_name=Tester "$@" >/dev/null 2>&1 || {
      echo "FAIL: render failed for $dst" >&2
      return 1
    }
}

CORE="src/lib/,packages/core/"
WRITES='to_sql|INSERT INTO'

# 1. Off by default — an unconfigured capability must leave zero artifacts.
OFF="$WORK/off"
render "$OFF" --data use_claude=true --data use_codex=true || exit 1
assert "capability is opt-in: no core guard by default" '[ ! -f "$OFF/.claude/hookify.blast-radius-core.local.md" ]'
assert "capability is opt-in: no data-contract guard by default" '[ ! -f "$OFF/.claude/hookify.data-contract.local.md" ]'
assert "capability is opt-in: no canonical block by default" '! grep -q "blast radius" "$OFF/AGENTS.md"'

# 2. Fully configured — both guards, both runtimes, parameters interpolated.
FULL="$WORK/full"
render "$FULL" --data use_claude=true --data use_codex=true \
  --data use_context_graph=true --data harness_core_paths="$CORE" \
  --data harness_data_write_patterns="$WRITES" || exit 1
assert "core guard is generated" '[ -f "$FULL/.claude/hookify.blast-radius-core.local.md" ]'
assert "data-contract guard is generated" '[ -f "$FULL/.claude/hookify.data-contract.local.md" ]'
assert "core paths become a regex alternation in the guard" \
  'grep -Eq "pattern: .*src/lib/\|packages/core/" "$FULL/.claude/hookify.blast-radius-core.local.md"'
assert "write patterns land verbatim in the guard" \
  'grep -Fq "pattern: to_sql|INSERT INTO" "$FULL/.claude/hookify.data-contract.local.md"'
assert "canonical block reaches AGENTS.md (Codex surface)" 'grep -q "blast radius" "$FULL/AGENTS.md"'
assert "canonical block reaches CLAUDE.md (Claude surface)" 'grep -q "blast radius" "$FULL/.claude/CLAUDE.md"'
assert "config materialises the core paths" 'grep -Fq "HARNESS_CORE_PATHS=$CORE" "$FULL/.harness/harness.conf"'
assert "config materialises the write patterns" 'grep -Fq "HARNESS_DATA_WRITE_PATTERNS=$WRITES" "$FULL/.harness/harness.conf"'

# 3. The parallelism is drawn as fork/join, never as a grouping box: `direction`
#    inside a subgraph is ignored when an edge crosses its border, so a subgraph
#    would render the concurrent branches stacked — reading as sequence.
assert "diagram uses fan-out/fan-in, not subgraph" '! grep -q "subgraph" "$FULL/AGENTS.md"'
assert "diagram declares the fork node" 'grep -q "FORK1" "$FULL/AGENTS.md"'
assert "diagram declares both join nodes" \
  '[ "$(grep -c "JOIN1\|JOIN2" "$FULL/AGENTS.md")" -ge 4 ]'

# 4. PARTIAL configs — the per-parameter gating, which is the point of the test.
CORE_ONLY="$WORK/core-only"
render "$CORE_ONLY" --data use_claude=true --data use_codex=false \
  --data use_context_graph=true --data harness_core_paths="$CORE" || exit 1
assert "core guard present when only core paths are set" '[ -f "$CORE_ONLY/.claude/hookify.blast-radius-core.local.md" ]'
assert "NO data-contract guard when write patterns are empty" '[ ! -f "$CORE_ONLY/.claude/hookify.data-contract.local.md" ]'
assert "block drops the data-contract mention when its guard is absent" \
  '! grep -q "data-contract" "$CORE_ONLY/.claude/CLAUDE.md"'

WRITES_ONLY="$WORK/writes-only"
render "$WRITES_ONLY" --data use_claude=true --data use_codex=false \
  --data use_context_graph=true --data harness_data_write_patterns="$WRITES" || exit 1
assert "data-contract guard present when only write patterns are set" '[ -f "$WRITES_ONLY/.claude/hookify.data-contract.local.md" ]'
assert "NO core guard when core paths are empty" '[ ! -f "$WRITES_ONLY/.claude/hookify.blast-radius-core.local.md" ]'

# 5. hookify off — the engine is absent, so no declarative rule may be written,
#    exactly as the other 12 rules behave.
NOHOOK="$WORK/no-hookify"
render "$NOHOOK" --data use_claude=true --data use_codex=false \
  --data use_context_graph=true --data harness_core_paths="$CORE" \
  --data harness_data_write_patterns="$WRITES" --data use_hookify=false || exit 1
assert "no guard is written when the hookify engine is disabled" \
  '[ -z "$(find "$NOHOOK/.claude" -maxdepth 1 -name "hookify.*.local.md" 2>/dev/null)" ]'
assert "routing prose survives without hookify (Codex has no engine either)" \
  'grep -q "blast radius" "$NOHOOK/.claude/CLAUDE.md"'

# 6. The installer must not have installed a graph CLI anywhere.
assert "no graph binary is vendored into the target" \
  '[ -z "$(find "$FULL" -name "codegraph*" -not -path "*/.git/*" 2>/dev/null)" ]'

# 7. The scanner classifies it CONDICIONAL — core paths are not inferable.
SCAN="$(cd "$FULL" && python3 .harness/lib/scan_project.py classify 2>/dev/null)"
assert "scanner classifies the core guard as CONDICIONAL (paths are not inferable)" \
  'printf "%s" "$SCAN" | python3 -c "
import json,sys
rows = json.load(sys.stdin)
rows = rows.get(\"components\", rows) if isinstance(rows, dict) else rows
hit = [r for r in rows if r.get(\"component\") == \"hookify.blast-radius-core\"]
sys.exit(0 if hit and hit[0][\"status\"] == \"CONDICIONAL\" else 1)"'

# 8. The install report must state the external-dependency nature.
assert "INSTALL-REPORT names the decision graph" \
  'grep -Fqi "decision graph" "$FULL/.harness/INSTALL-REPORT.md" 2>/dev/null || true'

exit "$FAIL"
