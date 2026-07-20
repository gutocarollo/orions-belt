#!/usr/bin/env bash
# test_ds_pairs_oklch.sh — regression for A6.1 (post-v1.0.0 adversarial
# audit, H2 hardening): a color pair defined in OKLCH (the format
# that this repo's AGENTS.md recommends via TweakCN) with ~zero contrast
# became a silent SKIP in ds-pairs-check.py and the summary said "CONTRATO OK
# em todos os pares" anyway. Proves, against the script RENDERED via
# `copier copy --vcs-ref HEAD` (never against the file in templates/ directly —
# there is no Jinja in the file here, but the repo convention is to always test the
# real installable artifact):
#   1. a low-contrast OKLCH pair is CAUGHT as VIOLA (not SKIP+OK).
#   2. a high-contrast OKLCH pair really passes OK (correct conversion,
#      not just "not crediting a false positive").
#   3. a REALLY unresolvable format (translucent rgba) still reports
#      "NAO AVALIADOS" in the summary -- never "OK em todos os pares" -- and exits
#      with code != 0 (never a false green).
#
# Requires `uvx`. Runs outside orions-belt (fixture in $TMPDIR).
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"

FAIL=0
WORK="$(mktemp -d /tmp/ds-pairs-oklch.XXXXXX)"
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

BASE="$WORK/base"
mkdir -p "$BASE"
RENDER_LOG="$WORK/copier.log"
if ! uvx copier copy "$REPO_ROOT" "$BASE" --vcs-ref HEAD \
    --data project_name=dspairs-fixture --data owner_name=Tester \
    --data use_ds_gate=true \
    --defaults --trust -q > "$RENDER_LOG" 2>&1; then
  echo "FAIL: copier copy --vcs-ref HEAD failed -- $(tail -10 "$RENDER_LOG")"
  exit 1
fi
CHECK="$BASE/.harness/lib/ds-pairs-check.py"
assert "render produced .harness/lib/ds-pairs-check.py" '[ -f "$CHECK" ]'

# --- 1. LOW-contrast OKLCH pair -- must VIOLATE, not SKIP+OK ---
LOW="$WORK/low-contrast"
mkdir -p "$LOW/styles"
cat > "$LOW/styles/globals.css" <<'EOF'
:root {
  --background: #ffffff;
  --primary: oklch(0.6 0.02 250);
  --primary-foreground: oklch(0.62 0.02 250);
}
.dark {
  --background: #000000;
}
EOF
OUT_LOW=$(HARNESS_PROJECT_ROOT="$LOW" HARNESS_WEB_APP_DIR=. python3 "$CHECK" 2>&1)
LOW_EXIT=$?
assert "OKLCH low contrast: exit != 0 (real violation, not SKIP)" '[ "$LOW_EXIT" -ne 0 ]'
assert "OKLCH low contrast: appears as VIOLA (not SKIP) in the output" \
  'echo "$OUT_LOW" | grep -q "primary.*VIOLA\|VIOLA.*primary"'
assert "OKLCH low contrast: summary does NOT say 'OK em todos os pares'" \
  '! echo "$OUT_LOW" | grep -q "OK em todos os pares"'

# --- 2. HIGH-contrast OKLCH pair (pure white over a saturated tone) -- real OK ---
HIGH="$WORK/high-contrast"
mkdir -p "$HIGH/styles"
cat > "$HIGH/styles/globals.css" <<'EOF'
:root {
  --background: #ffffff;
  --primary: oklch(0.5 0.2 25);
  --primary-foreground: oklch(1 0 0);
}
.dark {
  --background: #000000;
}
EOF
OUT_HIGH=$(HARNESS_PROJECT_ROOT="$HIGH" HARNESS_WEB_APP_DIR=. python3 "$CHECK" 2>&1)
HIGH_EXIT=$?
assert "OKLCH high contrast (pure white over a saturated tone): exit 0" '[ "$HIGH_EXIT" -eq 0 ]'
assert "OKLCH high contrast: summary says 'OK em todos os pares'" \
  'echo "$OUT_HIGH" | grep -q "OK em todos os pares"'
assert "oklch(1 0 0) resolved to real white (#ffffff on the pair line)" \
  'echo "$OUT_HIGH" | grep -q "#ffffff"'

# --- 3. REALLY unresolvable format (translucent rgba) -- honest SKIP ---
SKIP="$WORK/real-skip"
mkdir -p "$SKIP/styles"
cat > "$SKIP/styles/globals.css" <<'EOF'
:root {
  --background: #ffffff;
  --primary: rgba(10, 20, 30, 0.4);
  --primary-foreground: #ffffff;
}
.dark {
  --background: #000000;
}
EOF
OUT_SKIP=$(HARNESS_PROJECT_ROOT="$SKIP" HARNESS_WEB_APP_DIR=. python3 "$CHECK" 2>&1)
SKIP_EXIT=$?
assert "translucent rgba (really-unresolvable): exit != 0 (never a false green)" '[ "$SKIP_EXIT" -ne 0 ]'
assert "translucent rgba: summary reports 'NAO AVALIADOS', never 'OK em todos os pares'" \
  'echo "$OUT_SKIP" | grep -qi "NAO AVALIADOS" && ! echo "$OUT_SKIP" | grep -q "OK em todos os pares"'

echo
echo "=== summary ==="
if [ "$FAIL" -eq 0 ]; then
  echo "A6.1 (OKLCH) CLOSED: the low-contrast pair is caught, the summary never lies 'OK'."
else
  echo "THERE IS STILL A GAP — see FAILs above."
fi
exit $FAIL
