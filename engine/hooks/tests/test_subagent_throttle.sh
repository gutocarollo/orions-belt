#!/usr/bin/env bash
# test_subagent_throttle.sh — end-to-end proof of F0 (central config):
# runs engine/hooks/subagent-throttle.sh N times against the fixture at
# fixture-project/.harness/harness.conf and confirms it respects
# HARNESS_SUBAGENT_MAX_CONCURRENT from the .conf, NOT the CAP=6 hardcoded in the
# original learnhouse hook. Then it changes the .conf to 3 and proves the hook
# starts respecting 3 — proving DYNAMIC reading, not a value frozen in the
# process.
#
# Usage: bash engine/hooks/tests/test_subagent_throttle.sh
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOKS_DIR="$(cd "$HERE/.." && pwd)"
HOOK="$HOOKS_DIR/subagent-throttle.sh"
FIXTURE="$HERE/fixture-project"
CONF="$FIXTURE/.harness/harness.conf"
# M-ALTA/H4: the HARNESS_RUNS_DIR default changed from ".claude/runs" to
# ".harness/runs" (neutral) -- reset_slots() removes only the runs/
# subdirectory, NEVER the whole ".harness" (that is where harness.conf lives).
SLOTS_DIR="$FIXTURE/.harness/runs/.slots"

FAIL=0

reset_slots() {
  rm -rf "$FIXTURE/.harness/runs"
}

set_cap() {
  # $1 = new value of HARNESS_SUBAGENT_MAX_CONCURRENT
  cat > "$CONF" <<EOF
# test fixture — NOT a real project config, only proves F0.
PROJECT_NAME=fixture-project
HARNESS_SUBAGENT_MAX_CONCURRENT=$1
HARNESS_SUBAGENT_SLOT_STALE_MINUTES=45
EOF
}

run_hook() {
  CLAUDE_PROJECT_DIR="$FIXTURE" bash "$HOOK"
}

assert_exit() {
  # $1 = description, $2 = obtained exit code, $3 = expected exit code
  if [ "$2" -eq "$3" ]; then
    echo "PASS: $1 (exit=$2)"
  else
    echo "FAIL: $1 (expected exit=$3, obtained exit=$2)"
    FAIL=1
  fi
}

echo "=== Scenario 1: HARNESS_SUBAGENT_MAX_CONCURRENT=6 (original fixture value) ==="
set_cap 6
reset_slots
for i in 1 2 3 4 5 6; do
  run_hook >/tmp/throttle-out-$$ 2>&1
  rc=$?
  assert_exit "call $i/6 should pass" "$rc" 0
done
run_hook >/tmp/throttle-out-$$ 2>&1
rc=$?
assert_exit "call 7 (above cap=6) should be blocked" "$rc" 2
grep -q "6/6" /tmp/throttle-out-$$ && echo "PASS: throttle message cites 6/6 (correct cap in the message)" || { echo "FAIL: throttle message does not cite 6/6: $(cat /tmp/throttle-out-$$)"; FAIL=1; }

echo
echo "=== Scenario 2: change .conf to HARNESS_SUBAGENT_MAX_CONCURRENT=3 (proves dynamic reading) ==="
set_cap 3
reset_slots
for i in 1 2 3; do
  run_hook >/tmp/throttle-out-$$ 2>&1
  rc=$?
  assert_exit "call $i/3 should pass (cap is now 3)" "$rc" 0
done
run_hook >/tmp/throttle-out-$$ 2>&1
rc=$?
assert_exit "call 4 (above cap=3) should be blocked" "$rc" 2
grep -q "3/3" /tmp/throttle-out-$$ && echo "PASS: throttle message cites 3/3 (new cap reflected)" || { echo "FAIL: throttle message does not cite 3/3: $(cat /tmp/throttle-out-$$)"; FAIL=1; }

echo
echo "=== Scenario 3: fail-open — without .harness/harness.conf (renamed), falls back to default 6 ==="
mv "$CONF" "$CONF.bak"
reset_slots
for i in 1 2 3 4 5 6; do
  run_hook >/dev/null 2>&1
  rc=$?
  assert_exit "fail-open call $i/6 should pass" "$rc" 0
done
run_hook >/tmp/throttle-out-$$ 2>&1
rc=$?
assert_exit "fail-open call 7 should be blocked at default 6" "$rc" 2
mv "$CONF.bak" "$CONF"

reset_slots
rm -f /tmp/throttle-out-$$
set_cap 6  # leave the fixture as it was before the test

echo
if [ "$FAIL" -eq 0 ]; then
  echo "RESULT: ALL SCENARIOS PASSED"
  exit 0
else
  echo "RESULT: THERE ARE FAILURES — see FAIL lines above"
  exit 1
fi
