#!/usr/bin/env bash
# test_harness_freshness.sh — the SessionStart freshness guard: warn on the first
# prompt when the installed instance is absent or stale, stay silent when fresh or
# already acknowledged, and let freshness-ack.sh record the decision. Uses a
# controlled git fixture (no copier needed) so the stale path is deterministic.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
HOOK="$REPO_ROOT/templates/.harness/hooks/harness-freshness.sh"
ACKLIB="$REPO_ROOT/templates/.harness/lib/freshness-ack.sh"
FAIL=0
assert() { if eval "$2"; then echo "PASS: $1"; else echo "FAIL: $1"; FAIL=1; fi; }

WORK="$(mktemp -d "${TMPDIR:-/tmp}/freshness.XXXXXX")"; trap 'rm -rf "$WORK"' EXIT

mk_repo() {  # $1=dir ; creates a git repo with origin=test://src and one tagged commit
  local d="$1"; mkdir -p "$d/.harness/hooks" "$d/.harness/lib"
  git -C "$d" init -q
  git -C "$d" config user.email t@t; git -C "$d" config user.name t
  git -C "$d" remote add origin "test://src"
  ( cd "$d" && : > f && git add f && git commit -qm c1 && git tag v9.9.9 )
  cp "$HOOK" "$d/.harness/hooks/"; cp "$ACKLIB" "$d/.harness/lib/"
}
manifest() {  # $1=dir $2=ref  ; writes a manifest with source=test://src
  printf '{"files":{},"template":{"ref":"%s","source":"test://src"},"version":1}\n' "$2" > "$1/.harness/install-manifest.json"
}
run() { CLAUDE_PROJECT_DIR="$1" bash "$1/.harness/hooks/harness-freshness.sh" 2>/dev/null; }

# --- ABSENT: no manifest, no surfaces -> warn ---
A="$WORK/absent"; mkdir -p "$A/.harness/hooks"; git -C "$A" init -q; cp "$HOOK" "$A/.harness/hooks/"
assert "absent -> warns STATE=absent" 'run "$A" | grep -q "STATE=absent"'

# --- FRESH: manifest ref == current git describe -> silent ---
FR="$WORK/fresh"; mk_repo "$FR"
CUR="$(git -C "$FR" describe --tags --always --dirty)"
manifest "$FR" "$CUR"
assert "fresh (ref == describe) -> silent (no output)" '[ -z "$(run "$FR")" ]'

# --- STALE: manifest ref behind current describe -> warn ---
ST="$WORK/stale"; mk_repo "$ST"
manifest "$ST" "v0.0.1-OLD"
assert "stale (ref behind, origin==source) -> warns STATE=stale" 'run "$ST" | grep -q "STATE=stale"'
assert "stale warning shows both refs" 'run "$ST" | grep -q "v0.0.1-OLD"'

# --- ACK silences the stale nag ---
CLAUDE_PROJECT_DIR="$ST" bash "$ST/.harness/lib/freshness-ack.sh" acknowledged >/dev/null 2>&1
assert "after freshness-ack -> stale nag is silenced" '[ -z "$(run "$ST")" ]'
assert "ack file records the decision key" 'grep -q "stale:" "$ST/.harness/.freshness-ack"'

# --- PARTIAL (manifest missing but AGENTS.md present) -> silent (do not nag odd states) ---
P="$WORK/partial"; mkdir -p "$P/.harness/hooks"; git -C "$P" init -q; cp "$HOOK" "$P/.harness/hooks/"; : > "$P/AGENTS.md"
assert "partial (no manifest, AGENTS present) -> silent" '[ -z "$(run "$P")" ]'

echo
if [ "$FAIL" -eq 0 ]; then echo "RESULT: FRESHNESS GUARD PASSED"; else echo "RESULT: FAILURES"; fi
exit "$FAIL"
