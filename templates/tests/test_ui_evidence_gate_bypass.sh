#!/usr/bin/env bash
# test_ui_evidence_gate_bypass.sh — regression for the 4 A5 bypasses (post-v1.0.0
# adversarial audit, H2 hardening) against the Stop hook ui-evidence-gate.sh
# and the engine scripts/ui-evidence.sh, REALLY RENDERED via `copier copy
# --vcs-ref HEAD` (never logic reimplemented in prose — same principle as the
# siblings test_harness_install_brownfield_e2e.sh/test_copier_update_e2e.sh).
#
# The 4 bypasses, each proven CLOSED (blocks/fails) in this round:
#   1. FORGED manifest (`echo '{"captures":1}' > manifest.json`, zero PNGs
#      on disk) satisfied the gate. Fix: requires "files" with N ".png" == captures
#      AND each PNG existing on disk.
#   2. Deleting a UI file masked the change (NEWEST=0, gate exited
#      early). Fix: parent-directory mtime (POSIX: `rm` updates the dir's
#      mtime) as a proxy for the instant of deletion.
#   3. HTTP 500 became "1 passed" + valid evidence. Covered by
#      test_ui_evidence_spec_error_status.sh (sibling — needs real Playwright,
#      which is why it is separate and SKIP-safe).
#   4. Preflight of an unavailable host produced "000000" (curl `-w` bug +
#      `|| echo 000` duplicating output), never hit the error branch.
#
# Requires `uvx`. Runs outside orions-belt (fixture in $TMPDIR).
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"

FAIL=0
WORK="$(mktemp -d /tmp/ui-evidence-gate-bypass.XXXXXX)"
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

# --- 0. Real render of the template (harness_web_app_dir=".", use_ui_evidence=true) ---
BASE="$WORK/base"
mkdir -p "$BASE"
RENDER_LOG="$WORK/copier.log"
if ! uvx copier copy "$REPO_ROOT" "$BASE" --vcs-ref HEAD \
    --data project_name=uiev-fixture --data owner_name=Tester \
    --data use_ui_evidence=true \
    --defaults --trust -q > "$RENDER_LOG" 2>&1; then
  echo "FAIL: copier copy --vcs-ref HEAD failed -- $(tail -10 "$RENDER_LOG")"
  exit 1
fi
assert "render produced .harness/hooks/ui-evidence-gate.sh" '[ -f "$BASE/.harness/hooks/ui-evidence-gate.sh" ]'
assert "render produced scripts/ui-evidence.sh" '[ -f "$BASE/scripts/ui-evidence.sh" ]'
assert "render produced tests/visual/evidence.spec.ts" '[ -f "$BASE/tests/visual/evidence.spec.ts" ]'

# --- 0.1 minimal wiring (package.json with "ui:evidence" -- ENGINE_WIRED) + 1 component ---
mkdir -p "$BASE/components"
cat > "$BASE/components/foo.tsx" <<'EOF'
export const Foo = () => <div>foo</div>
EOF
cat > "$BASE/package.json" <<'EOF'
{"name": "uiev-fixture", "scripts": {"ui:evidence": "bash scripts/ui-evidence.sh"}}
EOF

cd "$BASE"
git init -q
git config user.email "test@example.com"
git config user.name "Test"
git add -A && git commit -qm "base fixture (harness instalado + wiring + 1 componente)" >/dev/null

# =============================================================================
# BYPASS 1 — forged manifest (zero real PNGs)
# =============================================================================
B1="$WORK/bypass1"
cp -r "$BASE" "$B1"
cd "$B1"
echo 'export const Foo = () => <div>foo v2</div>' > components/foo.tsx  # UI change, not committed

mkdir -p .claude/evidence/after
echo '{"captures":1}' > .claude/evidence/after/manifest.json  # FORGED: zero PNGs on disk
touch -d '+1 hour' .claude/evidence/after/manifest.json 2>/dev/null || touch .claude/evidence/after/manifest.json

echo '{}' | HARNESS_PROJECT_ROOT="$B1" CLAUDE_PROJECT_DIR="$B1" bash "$B1/.harness/hooks/ui-evidence-gate.sh" \
  >"$WORK/b1.out" 2>"$WORK/b1.err"
B1_EXIT=$?
assert "bypass 1 (forged manifest without PNGs): gate BLOCKS (exit 2), no longer passes silently" \
  '[ "$B1_EXIT" -eq 2 ]'

# proves that REAL evidence (existing PNG + consistent files/captures) still passes
printf '\x89PNG\r\n\x1a\nfake' > .claude/evidence/after/home__default__desktop.png
cat > .claude/evidence/after/manifest.json <<'EOF'
{"label": "after", "captures": 1, "files": {"home__default__desktop.png": "abc123"}}
EOF
touch .claude/evidence/after/manifest.json
echo '{}' | HARNESS_PROJECT_ROOT="$B1" CLAUDE_PROJECT_DIR="$B1" bash "$B1/.harness/hooks/ui-evidence-gate.sh" \
  >"$WORK/b1ok.out" 2>"$WORK/b1ok.err"
B1_OK_EXIT=$?
assert "bypass 1 (positive control): manifest with a real PNG on disk passes (exit 0)" \
  '[ "$B1_OK_EXIT" -eq 0 ]'

# =============================================================================
# BYPASS 2 — deletion masks the UI change
# =============================================================================
B2="$WORK/bypass2"
cp -r "$BASE" "$B2"
cd "$B2"

# OLD manifest (before the deletion) -- must not satisfy the gate afterwards
mkdir -p .claude/evidence/before
echo '{"captures":1,"files":{"x.png":"aaa"}}' > .claude/evidence/before/manifest.json
printf 'x' > .claude/evidence/before/x.png
touch -d '-1 hour' .claude/evidence/before/manifest.json 2>/dev/null || true

rm components/foo.tsx  # deletion, not committed -- the original bypass

echo '{}' | HARNESS_PROJECT_ROOT="$B2" CLAUDE_PROJECT_DIR="$B2" bash "$B2/.harness/hooks/ui-evidence-gate.sh" \
  >"$WORK/b2.out" 2>"$WORK/b2.err"
B2_EXIT=$?
assert "bypass 2 (.tsx deletion): gate BLOCKS (exit 2), does not exit early with NEWEST=0" \
  '[ "$B2_EXIT" -eq 2 ]'

# proves that evidence generated AFTER the deletion (manifest mtime >= parent-
# directory mtime at the instant of deletion) passes
mkdir -p .claude/evidence/after2
printf '\x89PNG\r\n\x1a\nfake' > .claude/evidence/after2/home.png
echo '{"captures":1,"files":{"home.png":"bbb"}}' > .claude/evidence/after2/manifest.json
echo '{}' | HARNESS_PROJECT_ROOT="$B2" CLAUDE_PROJECT_DIR="$B2" bash "$B2/.harness/hooks/ui-evidence-gate.sh" \
  >"$WORK/b2ok.out" 2>"$WORK/b2ok.err"
B2_OK_EXIT=$?
assert "bypass 2 (positive control): real evidence generated AFTER the deletion passes (exit 0)" \
  '[ "$B2_OK_EXIT" -eq 0 ]'

# =============================================================================
# BYPASS 4 — preflight of an unavailable host (curl "000000" vs "000")
# =============================================================================
B4="$WORK/bypass4"
cp -r "$BASE" "$B4"
cd "$B4"
DEAD_PORT=39217  # assumed closed; preflight has --max-time 5 anyway

PLAYWRIGHT_WEB_URL="http://127.0.0.1:$DEAD_PORT" bash scripts/ui-evidence.sh after \
  >"$WORK/b4.out" 2>"$WORK/b4.err"
B4_EXIT=$?
assert "bypass 4 (unavailable host): ui-evidence.sh exits with error (exit 1), preflight catches the case" \
  '[ "$B4_EXIT" -eq 1 ]'
assert "bypass 4: stderr reports PREFLIGHT FALHOU (clear message, not silent generation)" \
  'grep -q "PREFLIGHT FALHOU" "$WORK/b4.err"'
assert "bypass 4: preflight NEVER gets to invoke playwright (no 'ui-evidence: label=' on stdout)" \
  '! grep -q "ui-evidence: label=" "$WORK/b4.out"'

echo
echo "=== summary ==="
if [ "$FAIL" -eq 0 ]; then
  echo "ALL A5 BYPASSES (1,2,4) CLOSED."
else
  echo "THERE IS STILL AN OPEN BYPASS — see FAILs above."
fi
exit $FAIL
