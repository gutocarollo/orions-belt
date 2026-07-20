#!/usr/bin/env bash
# test_check_platform.sh — regression for M3 (H4 adversarial audit):
# "portable" was an adjective declared nowhere -- the hooks
# depend on Bash>=4, GNU coreutils (stat -c, date +%s%N), flock and python3;
# on macOS/minimal containers part of the gates fail or become a silent no-op.
#
# Proves here: (a) `.harness/lib/check-platform.sh` exists in the render (neutral,
# unconditional dir -- same group as scan_project.py/merge_docs.py);
# (b) running with the real PATH (all deps present on this CI/dev-box),
# exits 0; (c) running with a REALLY missing dependency simulated (minimal
# PATH without `flock`), detects and reports "FALTA flock" and exits != 0 --
# it is not a cosmetic report, the preflight actually CATCHES the absence.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"

FAIL=0
assert() {
  if eval "$2"; then echo "PASS: $1"; else echo "FAIL: $1"; FAIL=1; fi
}

SCRIPT="$REPO_ROOT/templates/.harness/lib/check-platform.sh"
assert "check-platform.sh exists in the templates tree (neutral dir)" '[ -f "$SCRIPT" ]'
assert "check-platform.sh is executable or at least readable by bash" '[ -r "$SCRIPT" ]'

# --- (b) real environment (all deps present) -> exit 0 ---
REAL_OUT="$(bash "$SCRIPT" 2>&1)"
REAL_EXIT=$?
assert "with the real PATH (all deps), check-platform.sh exits 0" '[ "$REAL_EXIT" -eq 0 ]'
assert "with the real PATH, reports OK for flock" 'echo "$REAL_OUT" | grep -q "OK.*flock"'

# --- (c) simulate a REALLY missing dependency: minimal PATH without flock ---
FAKEBIN="$(mktemp -d /tmp/check-platform-fakebin.XXXXXX)"
trap 'rm -rf "$FAKEBIN"' EXIT
for b in bash cat sed awk mkdir rm mktemp uname date stat python3 grep; do
  real="$(command -v "$b" 2>/dev/null || true)"
  [ -n "$real" ] && ln -sf "$real" "$FAKEBIN/$b"
done
# flock and timeout DELIBERATELY absent from this minimal PATH

FAKE_OUT="$(PATH="$FAKEBIN" bash "$SCRIPT" 2>&1)"
FAKE_EXIT=$?
assert "with flock absent from PATH, check-platform.sh detects and reports 'FALTA flock'" \
  'echo "$FAKE_OUT" | grep -q "FALTA.*flock"'
assert "with a required dependency absent, exit code != 0 (does not pass as green)" \
  '[ "$FAKE_EXIT" -ne 0 ]'
assert "the missing-timeout warning also appears (soft dependency)" \
  'echo "$FAKE_OUT" | grep -q "AVISO.*timeout"'

echo
echo "=== summary ==="
if [ "$FAIL" -eq 0 ]; then
  echo "M3 (platform preflight) PROVEN — detects a real missing dependency, not cosmetic."
else
  echo "THERE IS STILL AN OPEN GAP — see FAILs above."
fi
exit $FAIL
