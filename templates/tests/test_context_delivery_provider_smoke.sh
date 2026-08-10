#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
WORK="$(mktemp -d /tmp/orions-context-provider.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

for cmd in uvx codegraph; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "SKIP: $cmd missing"; exit 77; }
done

uvx copier copy "$ROOT" "$WORK/project" --vcs-ref HEAD --trust --defaults -q \
  --data project_name=providersmoke --data owner_name=Tester --data use_antigravity=false \
  --data use_claude=true --data use_codex=true --data use_context_delivery=true \
  --data use_context_graph=true --data harness_context_provider=codegraph

cd "$WORK/project"
mkdir -p src/components app/dashboard
cat > src/components/HoverCard.tsx <<'TSX'
export function HoverCard() {
  return <div className="transition-transform hover:scale-105">Card</div>;
}
TSX
cat > app/dashboard/page.tsx <<'TSX'
import { HoverCard } from "../../src/components/HoverCard";
export default function Page() { return <HoverCard />; }
TSX

git init -q
git config user.email smoke@example.invalid
git config user.name Smoke
git add -A
git commit -qm baseline

codegraph --version > "$WORK/codegraph-version.txt"
codegraph init -i > "$WORK/codegraph-init.txt" 2>&1
codegraph status --json > "$WORK/codegraph-status.json" 2>"$WORK/codegraph-status.err"
# Provider transport probe: legacy MCP stdio handshake. The separate real
# Claude/Codex smoke is authoritative for host compatibility.
python3 "$ROOT/templates/tests/context_delivery_mcp_probe.py" \
  --cwd "$WORK/project" --timeout 60 -- codegraph serve --mcp > "$WORK/mcp-tools.json"

python3 - <<'PY' "$WORK/mcp-tools.json" "$WORK/project/.mcp.json" "$WORK/project/.codex/config.toml"
import json,sys,tomllib
probe=json.load(open(sys.argv[1]))
assert probe["probeMode"]=="legacy-mcp-stdio-2025-11-25"
tools=set(probe["tools"])
if not tools.intersection({"codegraph_explore","codegraph_context","codegraph_search","codegraph_impact"}):
    raise SystemExit(f"missing operational CodeGraph query tool: {sorted(tools)}")
mcp=json.load(open(sys.argv[2]))["mcpServers"]["codegraph"]
assert mcp["command"]=="codegraph" and mcp["args"]==["serve","--mcp"]
config=tomllib.load(open(sys.argv[3],"rb"))["mcp_servers"]["codegraph"]
assert config["command"]=="codegraph" and config["args"]==["serve","--mcp"]
PY

python3 - "$WORK/codegraph-status.json" "$WORK/project/.harness/lib" <<'PYSTATUS'
import pathlib,sys
sys.path.insert(0, sys.argv[2])
from context_provider_probe import parse_codegraph_status
status=parse_codegraph_status(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
assert status["provider"]=="codegraph"
assert status["index_fresh"] is True and status["pending_changes"]==0, status
PYSTATUS

echo context-delivery-provider-smoke-ok
