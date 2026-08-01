#!/usr/bin/env bash
# test_marathon_locate.sh — proves the cross-repo resolution mechanism that
# was missing entirely before this file: a marathon whose run directory is
# NOT inside $ROOT/$RUNS_DIR must still be found via the user-level registry,
# stale/dead registry entries must be pruned, and register/unregister must be
# idempotent. Scenario 3 below is a direct reproduction of the measured
# 2026-08-01 field failure (see engine/hooks/marathon-locate.sh header):
# session anchored on one project directory, marathon run living in another.
#
# Usage: bash engine/hooks/tests/test_marathon_locate.sh
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOKS_DIR="$(cd "$HERE/.." && pwd)"
LOCATE="$HOOKS_DIR/marathon-locate.sh"

FAIL=0
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

assert() {
  # $1 = description, $2 = obtained, $3 = expected
  if [ "$2" = "$3" ]; then
    echo "PASS: $1"
  else
    echo "FAIL: $1 (expected [$3], obtained [$2])"
    FAIL=1
  fi
}

mk_run() {
  # $1 = run dir, $2 = goal line for RUN.md
  mkdir -p "$1"
  printf '# RUN: %s\ngoal: %s\n' "$(basename "$1")" "${2:-test}" > "$1/RUN.md"
}

echo "=== Scenario 1: local ACTIVE with a slug (historical behaviour) ==="
ROOT_A="$TMP/repo-a"
mkdir -p "$ROOT_A/.harness/runs"
mk_run "$ROOT_A/.harness/runs/slug-a" "local slug lookup"
echo "slug-a" > "$ROOT_A/.harness/runs/ACTIVE"
OUT="$(HOME="$TMP/home-empty" MARATHON_REGISTRY="$TMP/home-empty/.harness/marathon-active" bash "$LOCATE" locate "$ROOT_A" ".harness/runs")"
assert "slug ACTIVE resolves to the run dir" "$OUT" "$ROOT_A/.harness/runs/slug-a"

echo
echo "=== Scenario 2: local ACTIVE with an absolute path (cross-repo pointer) ==="
ROOT_B="$TMP/repo-b"
RUN_ELSEWHERE="$TMP/elsewhere/run-b"
mkdir -p "$ROOT_B/.harness/runs"
mk_run "$RUN_ELSEWHERE" "absolute pointer"
echo "$RUN_ELSEWHERE" > "$ROOT_B/.harness/runs/ACTIVE"
OUT="$(HOME="$TMP/home-empty" MARATHON_REGISTRY="$TMP/home-empty/.harness/marathon-active" bash "$LOCATE" locate "$ROOT_B" ".harness/runs")"
assert "absolute-path ACTIVE resolves to the external run dir" "$OUT" "$RUN_ELSEWHERE"

echo
echo "=== Scenario 3: registry fallback — THE measured field bug ==="
echo "    (session anchored on repo-c, marathon actually lives under repo-ui)"
ROOT_C="$TMP/repo-c"           # the project the session is anchored on — NO local ACTIVE
RUN_UI="$TMP/repo-ui/.harness/runs/graph-loop-fechar"
mkdir -p "$ROOT_C/.harness/runs"
mk_run "$RUN_UI" "cross-repo marathon"
REG="$TMP/home-c/.harness/marathon-active"
mkdir -p "$(dirname "$REG")"
printf '%s\n' "$RUN_UI" > "$REG"
OUT="$(MARATHON_REGISTRY="$REG" bash "$LOCATE" locate "$ROOT_C" ".harness/runs")"
assert "no local ACTIVE + registry entry resolves via registry" "$OUT" "$RUN_UI"

echo
echo "=== Scenario 4: stale registry entry (RUN.md untouched past HARNESS_MARATHON_STALE_DAYS) is pruned ==="
RUN_STALE="$TMP/repo-stale/.harness/runs/old-one"
mk_run "$RUN_STALE" "should be pruned"
# back-date RUN.md well past the 7-day default cutoff
touch -d "30 days ago" "$RUN_STALE/RUN.md" 2>/dev/null || touch -t 202601010000 "$RUN_STALE/RUN.md"
REG_STALE="$TMP/home-stale/.harness/marathon-active"
mkdir -p "$(dirname "$REG_STALE")"
printf '%s\n' "$RUN_STALE" > "$REG_STALE"
ROOT_EMPTY="$TMP/repo-empty"
mkdir -p "$ROOT_EMPTY"
bash "$LOCATE" locate "$ROOT_EMPTY" ".harness/runs" >/tmp/marathon-locate-out-$$ 2>&1
RC=$?
MARATHON_REGISTRY="$REG_STALE" bash "$LOCATE" locate "$ROOT_EMPTY" ".harness/runs" >/tmp/marathon-locate-out-$$ 2>&1
RC=$?
assert "stale entry: locate exits 1 (nothing live)" "$RC" "1"
STILL_THERE="$(grep -c "$RUN_STALE" "$REG_STALE" 2>/dev/null)"; STILL_THERE="${STILL_THERE:-0}"
assert "stale entry: pruned from the registry file" "$STILL_THERE" "0"

echo
echo "=== Scenario 5: dead entry (RUN.md deleted, e.g. archived) is pruned ==="
RUN_DEAD="$TMP/repo-dead/.harness/runs/archived-one"
mk_run "$RUN_DEAD" "will be removed"
REG_DEAD="$TMP/home-dead/.harness/marathon-active"
mkdir -p "$(dirname "$REG_DEAD")"
printf '%s\n' "$RUN_DEAD" > "$REG_DEAD"
rm -rf "$RUN_DEAD"   # simulate archival/deletion without unregister
MARATHON_REGISTRY="$REG_DEAD" bash "$LOCATE" locate "$ROOT_EMPTY" ".harness/runs" >/dev/null 2>&1
RC=$?
assert "dead entry: locate exits 1" "$RC" "1"
STILL_THERE="$(grep -c "$RUN_DEAD" "$REG_DEAD" 2>/dev/null)"; STILL_THERE="${STILL_THERE:-0}"
assert "dead entry: pruned from the registry file" "$STILL_THERE" "0"

echo
echo "=== Scenario 6: register / unregister CLI is idempotent ==="
RUN_REG="$TMP/repo-reg/.harness/runs/idempotent"
mk_run "$RUN_REG" "register twice"
REG6="$TMP/home-reg/.harness/marathon-active"
MARATHON_REGISTRY="$REG6" bash "$LOCATE" register "$RUN_REG" >/dev/null 2>&1
MARATHON_REGISTRY="$REG6" bash "$LOCATE" register "$RUN_REG" >/dev/null 2>&1
COUNT="$(grep -cxF "$RUN_REG" "$REG6" 2>/dev/null || echo 0)"
assert "register twice writes exactly one line" "$COUNT" "1"
MARATHON_REGISTRY="$REG6" bash "$LOCATE" unregister "$RUN_REG" >/dev/null 2>&1
COUNT="$(grep -cxF "$RUN_REG" "$REG6" 2>/dev/null)"; COUNT="${COUNT:-0}"
assert "unregister removes the line" "$COUNT" "0"

echo
echo "=== Scenario 7: register refuses a directory without RUN.md ==="
mkdir -p "$TMP/not-a-marathon"
REG7="$TMP/home-reg7/.harness/marathon-active"
MARATHON_REGISTRY="$REG7" bash "$LOCATE" register "$TMP/not-a-marathon" >/tmp/marathon-locate-out-$$ 2>&1
RC=$?
assert "register without RUN.md fails" "$RC" "1"

rm -f /tmp/marathon-locate-out-$$

echo
if [ "$FAIL" -eq 0 ]; then
  echo "RESULT: ALL SCENARIOS PASSED"
  exit 0
else
  echo "RESULT: THERE ARE FAILURES — see FAIL lines above"
  exit 1
fi
