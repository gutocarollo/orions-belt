#!/usr/bin/env bash
# test_ds_gate_hardening.sh — regression for A6.2 and A6.3 (post-v1.0.0
# adversarial audit, H2 hardening):
#   A6.2 — `.ds-baseline.txt` was never generated in any install step,
#     so the ds-gate.sh ratchet stayed permanently in --report mode
#     (never fails, even with an obvious hardcode). Fix: `harness-install.sh`
#     generates the baseline automatically on the 1st install when use_ds_gate
#     was active.
#   A6.3 — `.ds-allowlist` promised globs but matched by literal substring
#     (`grep -vF`) — a pattern like `legacy/**` never matched any real
#     path. Fix: `.harness/lib/ds_allowlist_filter.py` (real fnmatch).
#
# Requires `uvx`. Runs outside orions-belt (fixture in $TMPDIR).
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
INSTALLER="$REPO_ROOT/harness-install.sh"

FAIL=0
WORK="$(mktemp -d /tmp/ds-gate-hardening.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

assert() {
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

# =============================================================================
# A6.2 — harness-install.sh generates .ds-baseline.txt automatically
# =============================================================================
TARGET="$WORK/target-project"
mkdir -p "$TARGET/components"
cd "$TARGET"
git init -q
git config user.email "test@example.com"
git config user.name "Test"
# 1 REAL violation already present BEFORE the install -- the baseline must capture
# that count (not zero), proving it reflects the CURRENT state of the
# target project, not a guessed value.
cat > components/legacy.tsx <<'EOF'
export const Legacy = () => <div className="text-gray-600" />
EOF
git add -A && git commit -qm "fixture pré-existente com 1 hardcode real" >/dev/null

INSTALL_LOG="$WORK/install.log"
if ! "$INSTALLER" "$TARGET" --vcs-ref HEAD \
    --data project_name=dsgate-fixture --data owner_name=Tester \
    --data use_ds_gate=true --data harness_web_app_dir=. \
    --defaults > "$INSTALL_LOG" 2>&1; then
  echo "FAIL: harness-install.sh failed -- $(tail -20 "$INSTALL_LOG")"
  cat "$INSTALL_LOG"
  exit 1
fi

assert "harness-install.sh materialized .harness/lib/ds-gate.sh" '[ -f "$TARGET/.harness/lib/ds-gate.sh" ]'
assert "harness-install.sh materialized the hook ds-gate-posttool.sh (use_ds_gate=true)" \
  '[ -f "$TARGET/.harness/hooks/ds-gate-posttool.sh" ]'
assert "A6.2: .ds-baseline.txt was GENERATED automatically by the 1st install" \
  '[ -f "$TARGET/.ds-baseline.txt" ]'
assert "A6.2: baseline reflects the REAL preexisting violation (color-gray=1), not a guessed zero" \
  'grep -q "^color-gray=1$" "$TARGET/.ds-baseline.txt"'

# proves that the ratchet now truly ENFORCES: a new violation AFTER the
# baseline must make the gate FAIL (before this fix, without a baseline,
# `check` never failed -- always report-only).
cat > "$TARGET/components/new-hardcode.tsx" <<'EOF'
export const New = () => <div className="text-gray-700 bg-red-500" />
EOF
if HARNESS_PROJECT_ROOT="$TARGET" bash "$TARGET/.harness/lib/ds-gate.sh" --dir . check \
   > "$WORK/ds-gate-check.out" 2>&1; then
  DS_GATE_EXIT=0
else
  DS_GATE_EXIT=$?
fi
assert "A6.2: with an existing baseline, a new hardcode MAKES the ratchet fail (exit != 0)" \
  '[ "$DS_GATE_EXIT" -ne 0 ]'
assert "A6.2: violated dimension has the stable INCREASED status" \
  'grep -qE "^color-gray[[:space:]].*INCREASED" "$WORK/ds-gate-check.out"'

# =============================================================================
# A6.3 — .ds-allowlist matches by real GLOB (fnmatch), not literal substring
# =============================================================================
GLOB_DIR="$WORK/glob-fixture"
mkdir -p "$GLOB_DIR/legacy" "$GLOB_DIR/fresh"
cat > "$GLOB_DIR/legacy/old.tsx" <<'EOF'
export const X = () => <div className="text-gray-500" />
EOF
cat > "$GLOB_DIR/fresh/new.tsx" <<'EOF'
export const Y = () => <div className="text-gray-600" />
EOF
cat > "$GLOB_DIR/.ds-allowlist" <<'EOF'
legacy/**
EOF
OUT_GLOB=$(HARNESS_PROJECT_ROOT="$GLOB_DIR" bash "$TARGET/.harness/lib/ds-gate.sh" --dir . --report 2>&1)
assert "A6.3: with allowlist 'legacy/**', only fresh/new.tsx counts (color-gray=1, not 2)" \
  'echo "$OUT_GLOB" | grep -qE "^color-gray +1 "'

rm "$GLOB_DIR/.ds-allowlist"
OUT_NOGLOB=$(HARNESS_PROJECT_ROOT="$GLOB_DIR" bash "$TARGET/.harness/lib/ds-gate.sh" --dir . --report 2>&1)
assert "A6.3 (control): without allowlist, both files count (color-gray=2)" \
  'echo "$OUT_NOGLOB" | grep -qE "^color-gray +2 "'

echo
echo "=== summary ==="
if [ "$FAIL" -eq 0 ]; then
  echo "A6.2 (auto-generated baseline) and A6.3 (real glob) CLOSED."
else
  echo "THERE IS STILL A GAP — see FAILs above."
fi
exit $FAIL
