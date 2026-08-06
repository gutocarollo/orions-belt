#!/usr/bin/env bash
# test_marathon_stop_gate.sh — END-TO-END proof of the cross-repo fix, driving
# the REAL hooks as subprocesses.
#
# WHY THIS EXISTS SEPARATELY FROM test_marathon_locate.sh. That file unit-tests
# the marathon-locate.sh library in isolation: slug/absolute-path ACTIVE,
# registry fallback, stale/dead pruning, register/unregister. It never invokes
# marathon-stop-gate.sh, marathon-reinject.sh or marathon-precompact.sh — so
# every defect that lives in the CONSUMER rather than the library was unproven.
# Measured before this file landed: `grep -c marathon-stop-gate` on the unit
# test returned 0.
#
# What only this file asserts, against the real gate:
#   - a NESTED open item blocks (the old `^- \[ \]` anchor counted zero, so a
#     RUN.md whose remaining work sat under a parent bullet released the stop);
#   - an in-progress `[~]` item blocks;
#   - progress is measured by CONTENT — a bare `touch` does not reset the
#     strike counter, while a real edit does;
#   - reinject and precompact also see the cross-repo run (Scenario 10);
#   - stop_hook_active short-circuits, so the gate cannot loop on itself.
#
# ORIGIN: recovered from a superseded local draft of the cross-repo fix
# (b103528, 2026-08-01) that lost to 1f8c857 on production code — better
# registry path, macOS stat fallback, config knob, engine/ source mirror — but
# whose test drove the real consumer, which 1f8c857's does not. The production
# code was discarded; this coverage was not.
#
# THE BUG THIS PINS DOWN (measured 2026-08-01). The three marathon hooks resolved
# the run directory as "$CLAUDE_PROJECT_DIR/$RUNS_DIR/$SLUG". A marathon whose
# run directory lived in ANOTHER repository — the normal case when a session is
# opened in one repo and the work happens in a second working directory — was
# invisible to all three. The gate never blocked, the reinject never reinjected,
# the precompact never stamped. The tell was physical: a multi-hour run with no
# `.stop-strikes` file anywhere.
#
# The regression is silent by construction, so a test that only asserts "blocks
# when there is a local marathon" would have stayed green through the whole
# outage. Scenario 2 is therefore the one that matters: the marathon is in a
# DIFFERENT root from CLAUDE_PROJECT_DIR and the gate must still block.
#
# Usage: bash engine/hooks/tests/test_marathon_locate.sh
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
HOOKS_SRC="$REPO/templates/.harness/hooks"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

FAIL=0
assert_exit() { # $1 desc, $2 got, $3 want
  if [ "$2" -eq "$3" ]; then echo "PASS: $1 (exit=$2)"; else echo "FAIL: $1 (want exit=$3, got=$2)"; FAIL=1; fi
}
assert_grep() { # $1 desc, $2 pattern, $3 file
  if grep -q -- "$2" "$3"; then echo "PASS: $1"; else echo "FAIL: $1 — '$2' not in $(cat "$3")"; FAIL=1; fi
}
assert_nogrep() {
  if grep -q -- "$2" "$3"; then echo "FAIL: $1 — '$2' unexpectedly in $(cat "$3")"; FAIL=1; else echo "PASS: $1"; fi
}

# Two independent roots: PROJ is the session's project directory, WORK is the
# other working directory where the marathon actually lives.
PROJ="$TMP/proj"; WORK="$TMP/work"
mkdir -p "$PROJ/.harness/hooks" "$WORK/.harness/runs/my-run"
cp "$HOOKS_SRC/marathon-locate.sh" "$HOOKS_SRC/marathon-stop-gate.sh" \
   "$HOOKS_SRC/marathon-reinject.sh" "$HOOKS_SRC/marathon-precompact.sh" "$PROJ/.harness/hooks/"
chmod +x "$PROJ/.harness/hooks/"*.sh

RUNMD="$WORK/.harness/runs/my-run/RUN.md"
write_run() { # $1 = next-action line
  cat > "$RUNMD" <<EOF
# RUN: my-run
goal: fixture

## Checklist (source of truth)
- [x] done item
- [ ] open item

## Next action
$1

## Journal
EOF
}
write_run "keep going"

REG="$TMP/marathon-active"
GATE="$PROJ/.harness/hooks/marathon-stop-gate.sh"
OUT="$TMP/out"

run_gate() {
  MARATHON_REGISTRY="$REG" CLAUDE_PROJECT_DIR="$PROJ" \
    bash "$GATE" <<< '{"stop_hook_active":false}' >"$OUT" 2>&1
}

echo "=== Scenario 1: no marathon anywhere → gate stays inert (the common case) ==="
: > "$REG"
run_gate; assert_exit "no marathon must not block" "$?" 0

echo
echo "=== Scenario 2: marathon in ANOTHER root, registered → gate BLOCKS (the bug) ==="
echo "$WORK/.harness/runs/my-run" > "$REG"
run_gate; rc=$?
assert_exit "cross-repo marathon with open items must block" "$rc" 2
assert_grep "message names the run directory" "$WORK/.harness/runs/my-run" "$OUT"
assert_grep "message carries the recorded next action" "keep going" "$OUT"
# The teardown hint must name a command that EXISTS. Built from "$0" it pointed
# at the sourcing hook, which has no unregister verb.
assert_grep "teardown hint points at marathon-locate.sh" "marathon-locate.sh unregister" "$OUT"
[ -f "$WORK/.harness/runs/my-run/.stop-strikes" ] \
  && echo "PASS: strike file written in the run directory (not under CLAUDE_PROJECT_DIR)" \
  || { echo "FAIL: no .stop-strikes in the run directory"; FAIL=1; }
[ -e "$PROJ/.harness/runs" ] && { echo "FAIL: gate wrote state under the project dir"; FAIL=1; } \
  || echo "PASS: gate wrote nothing under the project dir"

echo
echo "=== Scenario 3: local ACTIVE holding an ABSOLUTE PATH → cross-repo pointer ==="
: > "$REG"
mkdir -p "$PROJ/.harness/runs"
echo "$WORK/.harness/runs/my-run" > "$PROJ/.harness/runs/ACTIVE"
run_gate; assert_exit "absolute-path pointer must block" "$?" 2
assert_grep "pointer is reported as a local source" "located via: local" "$OUT"
rm -rf "$PROJ/.harness/runs"

echo
echo "=== Scenario 4: local ACTIVE holding a SLUG → historical behaviour intact ==="
: > "$REG"
mkdir -p "$PROJ/.harness/runs/local-run"
cp "$RUNMD" "$PROJ/.harness/runs/local-run/RUN.md"
echo "local-run" > "$PROJ/.harness/runs/ACTIVE"
run_gate; assert_exit "slug in ACTIVE must still block" "$?" 2
assert_grep "slug run is the one reported" "local-run" "$OUT"
rm -rf "$PROJ/.harness/runs"

echo
echo "=== Scenario 5: WAITING/AGUARDANDO → legitimate stop, still honoured cross-repo ==="
echo "$WORK/.harness/runs/my-run" > "$REG"
write_run "WAITING: which option does the owner want?"
run_gate; assert_exit "WAITING must release the stop" "$?" 0
write_run "AGUARDANDO: qual opção?"
run_gate; assert_exit "AGUARDANDO must release the stop" "$?" 0
write_run "keep going"

echo
echo "=== Scenario 6: checklist with zero open items → legitimate stop ==="
sed -i 's/^- \[ \] open item$/- [x] open item/' "$RUNMD"
run_gate; assert_exit "closed checklist must not block" "$?" 0
write_run "keep going"

echo
echo "=== Scenario 6b: NESTED and in-progress items count as open ==="
# The original anchor '^- \[ \]' ignored indentation, so a RUN.md whose only
# remaining work lived under a parent item reported zero open items and the
# gate released. Measured on the real graph-loop-fechar RUN.md: 1 counted,
# 5 actually open.
cat > "$RUNMD" <<'EOF'
# RUN: my-run
goal: fixture

## Checklist (source of truth)
- [x] parent done
  - [ ] nested still open

## Next action
keep going

## Journal
EOF
run_gate; assert_exit "a nested open item must block" "$?" 2
cat > "$RUNMD" <<'EOF'
# RUN: my-run
goal: fixture

## Checklist (source of truth)
- [~] in progress

## Next action
keep going

## Journal
EOF
run_gate; assert_exit "an in-progress [~] item must block" "$?" 2
cat > "$RUNMD" <<'EOF'
# RUN: my-run
goal: fixture

## Checklist (source of truth)
- [x] all done
  - [x] nested done too

## Next action
wrap up

## Journal
EOF
run_gate; assert_exit "fully closed, nesting included, must not block" "$?" 0
write_run "keep going"

echo
echo "=== Scenario 7: strike cap releases after N blocks WITHOUT progress ==="
rm -f "$WORK/.harness/runs/my-run/.stop-strikes"
run_gate; assert_exit "block 1" "$?" 2
run_gate; assert_exit "block 2" "$?" 2
run_gate; assert_exit "block 3" "$?" 2
run_gate; rc=$?
assert_exit "block 4 releases (3 strikes without progress)" "$rc" 0
assert_grep "release message explains the marathon is still active" "still ACTIVE" "$OUT"

echo
echo "=== Scenario 8: progress on RUN.md RESETS the strikes (the anti-lockup must not eat a live run) ==="
# No sleep here on purpose. Progress is measured by CONTENT, so two edits inside
# the same second are two edits — under the old mtime rule this scenario only
# passed because of an artificial sleep, and real back-to-back turns were
# silently counted as spinning.
rm -f "$WORK/.harness/runs/my-run/.stop-strikes"
run_gate; assert_exit "block 1" "$?" 2
run_gate; assert_exit "block 2" "$?" 2
write_run "next thing"                   # real progress: RUN.md content moves
run_gate; assert_exit "after progress, still blocking (counter reset)" "$?" 2
run_gate; assert_exit "block 2 of the new cycle" "$?" 2
run_gate; assert_exit "block 3 of the new cycle" "$?" 2

echo
echo "=== Scenario 8b: touching RUN.md WITHOUT changing it does NOT reset the strikes ==="
# The anti-lockup exists to free a stuck agent. If a bare `touch` reset the
# counter, an agent that rewrites nothing could hold the gate armed forever.
rm -f "$WORK/.harness/runs/my-run/.stop-strikes"
run_gate; assert_exit "block 1" "$?" 2
touch "$RUNMD"
run_gate; assert_exit "block 2 despite the touch" "$?" 2
touch "$RUNMD"
run_gate; assert_exit "block 3 despite the touch" "$?" 2
run_gate; assert_exit "release: touching is not progress" "$?" 0

echo
echo "=== Scenario 9: registry prunes entries whose RUN.md died or went stale ==="
rm -f "$WORK/.harness/runs/my-run/.stop-strikes"
printf '%s\n%s\n' "$TMP/ghost-run" "$WORK/.harness/runs/my-run" > "$REG"
run_gate; assert_exit "a ghost line must not stop the live entry from arming" "$?" 2
assert_nogrep "ghost line pruned from the registry" "ghost-run" "$REG"
assert_grep "live line kept in the registry" "$WORK/.harness/runs/my-run" "$REG"

touch -d "30 days ago" "$RUNMD"
echo "$WORK/.harness/runs/my-run" > "$REG"
run_gate; assert_exit "a run untouched for 30 days must not block" "$?" 0
assert_nogrep "stale entry pruned from the registry" "my-run" "$REG"
write_run "keep going"   # revive it for the remaining scenarios

echo
echo "=== Scenario 10: reinject and precompact see the cross-repo run too ==="
echo "$WORK/.harness/runs/my-run" > "$REG"
MARATHON_REGISTRY="$REG" CLAUDE_PROJECT_DIR="$PROJ" \
  bash "$PROJ/.harness/hooks/marathon-reinject.sh" >"$OUT" 2>&1
assert_grep "reinject emits the run state block" "<marathon-run-state" "$OUT"
assert_grep "reinject carries the checklist" "open item" "$OUT"

BEFORE=$(wc -l < "$RUNMD")
MARATHON_REGISTRY="$REG" CLAUDE_PROJECT_DIR="$PROJ" \
  bash "$PROJ/.harness/hooks/marathon-precompact.sh" >/dev/null 2>&1
AFTER=$(wc -l < "$RUNMD")
[ "$AFTER" -gt "$BEFORE" ] && echo "PASS: precompact stamped the cross-repo journal" \
  || { echo "FAIL: precompact did not touch the RUN.md ($BEFORE -> $AFTER)"; FAIL=1; }

echo
echo "=== Scenario 11: stop_hook_active=true → never re-block (no infinite loop) ==="
MARATHON_REGISTRY="$REG" CLAUDE_PROJECT_DIR="$PROJ" \
  bash "$GATE" <<< '{"stop_hook_active":true}' >"$OUT" 2>&1
assert_exit "stop_hook_active must short-circuit" "$?" 0

echo
echo "=== Scenario 12: register/unregister CLI is idempotent ==="
: > "$REG"
MARATHON_REGISTRY="$REG" bash "$PROJ/.harness/hooks/marathon-locate.sh" register "$WORK/.harness/runs/my-run" >/dev/null
MARATHON_REGISTRY="$REG" bash "$PROJ/.harness/hooks/marathon-locate.sh" register "$WORK/.harness/runs/my-run" >/dev/null
N=$(grep -c "my-run" "$REG")
[ "$N" -eq 1 ] && echo "PASS: registering twice keeps one line" || { echo "FAIL: $N lines after two registers"; FAIL=1; }
MARATHON_REGISTRY="$REG" bash "$PROJ/.harness/hooks/marathon-locate.sh" unregister "$WORK/.harness/runs/my-run"
assert_nogrep "unregister removes the line" "my-run" "$REG"
MARATHON_REGISTRY="$REG" bash "$PROJ/.harness/hooks/marathon-locate.sh" register "$TMP/not-a-marathon" >/dev/null 2>&1
assert_exit "registering a directory without RUN.md must fail" "$?" 1

echo
if [ "$FAIL" -eq 0 ]; then
  echo "RESULT: ALL SCENARIOS PASSED"
  exit 0
else
  echo "RESULT: THERE ARE FAILURES — see FAIL lines above"
  exit 1
fi
