#!/usr/bin/env bash
# A shipped rule set must declare the engine that executes it.
#
# Real gap (2026-07-28, install on a Python repo): the 5 hookify rules were
# rendered unconditionally with `enabled: true` while the plugin that runs them
# was neither installed nor declared anywhere — inert markdown, and nothing in
# INSTALL-REPORT.md saying the guard did not exist. Installing the plugin is not
# an option for the installer: it lives in ~/.claude/plugins, outside the target
# root, and the whole containment model forbids writing there. So the contract
# is DECLARE, never install: the project's .claude/settings.json carries
# extraKnownMarketplaces + enabledPlugins (the documented "team marketplaces"
# mechanism) and the runtime asks the user for install consent.
#
# The brownfield case is the one that actually matters and the one that used to
# fail: merge_settings_json rewrote only `hooks`, so a new top-level key reached
# a greenfield create and NEVER an existing settings.json.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
WORK="$(mktemp -d /tmp/orions-hookify-dependency.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT
FAIL=0

assert() { if eval "$2"; then echo "PASS: $1"; else echo "FAIL: $1"; FAIL=1; fi; }
command -v uvx >/dev/null 2>&1 || { echo "SKIP: uvx unavailable"; exit 77; }

render() {
  local dst="$1"; shift
  uvx copier copy "$REPO_ROOT" "$dst" --trust --defaults --vcs-ref HEAD \
    --data project_name=hookify-test --data owner_name=Tester "$@" >/dev/null 2>&1 || {
      echo "FAIL: render failed for $dst" >&2
      return 1
    }
}

plugin_declared() {  # $1 = settings.json path
  python3 - "$1" <<'PY'
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
enabled = data.get("enabledPlugins", {})
markets = data.get("extraKnownMarketplaces", {})
ok = (
    enabled.get("hookify@claude-plugins-official") is True
    and markets.get("claude-plugins-official", {}).get("source", {}).get("repo")
    == "anthropics/claude-plugins-official"
)
raise SystemExit(0 if ok else 1)
PY
}

# 1. Default: rules ship AND the engine they need is declared.
ON="$WORK/on"
render "$ON" --data use_claude=true --data use_codex=false || exit 1
assert "default renders the hookify rules" '[ -f "$ON/.claude/hookify.bare-python.local.md" ]'
assert "default declares the hookify plugin engine" 'plugin_declared "$ON/.claude/settings.json"'
assert "settings.json stays valid JSON" 'python3 -c "import json,sys;json.load(open(sys.argv[1]))" "$ON/.claude/settings.json"'
assert "harness hooks still registered next to the declaration" \
  'grep -Fq ".harness/hooks/completion-gate.py" "$ON/.claude/settings.json"'

# 2. Opt-out leaves no inert artifact behind — no rules AND no declaration.
OFF="$WORK/off"
render "$OFF" --data use_claude=true --data use_codex=false --data use_hookify=false || exit 1
assert "use_hookify=false renders no hookify rule" \
  '[ -z "$(find "$OFF/.claude" -maxdepth 1 -name "hookify.*.local.md" 2>/dev/null)" ]'
assert "use_hookify=false declares no plugin" '! plugin_declared "$OFF/.claude/settings.json"'
assert "use_hookify=false still produces valid settings.json" \
  'python3 -c "import json,sys;json.load(open(sys.argv[1]))" "$OFF/.claude/settings.json"'

# 3. Codex-only must not grow a Claude plugin declaration.
CODEX="$WORK/codex"
render "$CODEX" --data use_claude=false --data use_codex=true || exit 1
assert "codex-only render has no .claude/settings.json" '[ ! -f "$CODEX/.claude/settings.json" ]'

# 4. BROWNFIELD: an existing settings.json must receive the declaration, and
#    the project's own hook must survive it.
BROWN="$WORK/brownfield"
mkdir -p "$BROWN/.claude"
git init -q "$BROWN"
cat > "$BROWN/.claude/settings.json" <<'EOF'
{
  "hooks": {
    "Stop": [{ "hooks": [{ "type": "command", "command": "echo projeto-tinha-isto" }] }]
  }
}
EOF
"$REPO_ROOT/harness-install.sh" "$BROWN" --vcs-ref HEAD \
  --data project_name=hookify-brownfield --data owner_name=Tester \
  --data use_claude=true --data use_codex=false --defaults >"$WORK/brownfield.log" 2>&1
assert "brownfield install succeeds" '[ $? -eq 0 ] && [ -f "$BROWN/.claude/settings.json" ]'
assert "brownfield settings.json receives the plugin declaration" 'plugin_declared "$BROWN/.claude/settings.json"'
assert "pre-existing project hook survives the merge" \
  'grep -Fq "projeto-tinha-isto" "$BROWN/.claude/settings.json"'
assert "brownfield also gets the harness hooks" \
  'grep -Fq ".harness/hooks/completion-gate.py" "$BROWN/.claude/settings.json"'

# 5. The report must state the decision instead of leaving it implicit.
assert "INSTALL-REPORT names the hookify decision" \
  'grep -Fqi "hookify" "$BROWN/.harness/INSTALL-REPORT.md"'

exit "$FAIL"
