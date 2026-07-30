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
# PATH without `flock`), detects the stable `MISSING` status for flock and exits != 0 --
# it is not a cosmetic report, the preflight actually CATCHES the absence.
set -uo pipefail
# PRE-APPROVED INSTALL (consent gate, 2026-07-30). `harness-install.sh` refuses to write without an
# explicit yes, and a non-interactive caller that does not pre-approve exits 65 with the target
# untouched. A test harness IS automation, so it declares the approval once here instead of adding
# a flag to every invocation — this file drives the installer several times. Removing this line does
# not weaken the suite: it makes every install in it abort, which is the gate working as designed.
export HARNESS_INSTALL_ASSUME_YES=1


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
OLDPY_BIN=""
trap 'rm -rf "$FAKEBIN"; [ -z "${OLDPY_BIN:-}" ] || rm -rf "$OLDPY_BIN"' EXIT
for b in bash cat sed awk mkdir rm mktemp uname date stat python3 grep; do
  real="$(command -v "$b" 2>/dev/null || true)"
  [ -n "$real" ] && ln -sf "$real" "$FAKEBIN/$b"
done
# flock and timeout DELIBERATELY absent from this minimal PATH

FAKE_OUT="$(PATH="$FAKEBIN" bash "$SCRIPT" 2>&1)"
FAKE_EXIT=$?
assert "with flock absent from PATH, check-platform.sh emits the stable MISSING status" \
  'echo "$FAKE_OUT" | grep -qE "^[[:space:]]*MISSING[[:space:]]+flock([[:space:]]|$)"'
assert "with a required dependency absent, exit code != 0 (does not pass as green)" \
  '[ "$FAKE_EXIT" -ne 0 ]'
assert "the missing-timeout warning also appears (soft dependency)" \
  'echo "$FAKE_OUT" | grep -qE "^[[:space:]]*WARN[[:space:]]+timeout([[:space:]]|$)"'

# --- (d) an older python3 is present but unsupported ---
OLDPY_BIN="$(mktemp -d /tmp/check-platform-old-python.XXXXXX)"
for b in bash cat sed awk mkdir rm mktemp uname date stat grep flock dirname; do
  real="$(command -v "$b" 2>/dev/null || true)"
  [ -n "$real" ] && ln -sf "$real" "$OLDPY_BIN/$b"
done
cat > "$OLDPY_BIN/python3" <<'EOF'
#!/bin/sh
if [ "${1:-}" = "--version" ]; then
  echo "Python 3.9.6"
  exit 0
fi
exit 1
EOF
chmod +x "$OLDPY_BIN/python3"
OLDPY_OUT="$(PATH="$OLDPY_BIN" bash "$SCRIPT" 2>&1)"
OLDPY_EXIT=$?
assert "Python 3.9 is rejected even when python3 exists" \
  'echo "$OLDPY_OUT" | grep -qE "MISSING.*python3.*3.9.6.*required >=3.14"'
assert "unsupported Python makes the preflight fail" '[ "$OLDPY_EXIT" -ne 0 ]'

INSTALL_OUT="$(PATH="$OLDPY_BIN" bash "$REPO_ROOT/harness-install.sh" "$REPO_ROOT" --dry-run 2>&1)"
INSTALL_EXIT=$?
assert "installer blocks Python 3.9 before rendering" \
  'echo "$INSTALL_OUT" | grep -q "Python 3.14 or newer is required"'
assert "installer returns failure for Python 3.9" '[ "$INSTALL_EXIT" -ne 0 ]'

echo
echo "=== summary ==="
if [ "$FAIL" -eq 0 ]; then
  echo "M3 (platform preflight) PROVEN — detects a real missing dependency, not cosmetic."
else
  echo "THERE IS STILL AN OPEN GAP — see FAILs above."
fi
exit $FAIL
