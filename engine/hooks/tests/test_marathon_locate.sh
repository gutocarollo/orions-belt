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
# Overridable so the SAME suite can be pointed at a real installed project
# (MARATHON_HOOKS_SRC=/path/to/project/.harness/hooks) — proving the copy that
# actually runs there behaves, not only the engine source it came from.
HOOKS_DIR="${MARATHON_HOOKS_SRC:-$(cd "$HERE/.." && pwd)}"
LOCATE="$HOOKS_DIR/marathon-locate.sh"

FAIL=0
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export MARATHON_RUN_INDEX_DIR="$TMP/run-index-default"

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
RUN_REG_CANON="$(cd "$RUN_REG" && pwd -P)"
COUNT="$(grep -cxF "$RUN_REG_CANON" "$REG6" 2>/dev/null || true)"; COUNT="${COUNT:-0}"
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

echo
echo "=== Scenario 8: ignore-here is exact to one session and one run ==="
BLOCKS="$TMP/session-blocklist"
BINDINGS8="$TMP/session-bindings-8"
SESSION_ROOT="$TMP/session-root"
mkdir -p "$SESSION_ROOT"
CODEX_THREAD_ID="session-a" MARATHON_SESSION_BLOCKLIST_DIR="$BLOCKS" \
  MARATHON_REGISTRY="$REG6" bash "$LOCATE" register "$RUN_REG" >/dev/null
CODEX_THREAD_ID="session-a" MARATHON_SESSION_BINDINGS_DIR="$BINDINGS8" \
  bash "$LOCATE" bind-here "$RUN_REG" >/dev/null
CODEX_THREAD_ID="session-a" MARATHON_SESSION_BLOCKLIST_DIR="$BLOCKS" \
  MARATHON_REGISTRY="$REG6" bash "$LOCATE" ignore-here "$RUN_REG" >/dev/null
. "$LOCATE"
if MARATHON_SESSION_BLOCKLIST_DIR="$BLOCKS" marathon_session_is_ignored "session-a" "$RUN_REG"; then
  echo "PASS: ignored session matches its exact run"
else
  echo "FAIL: ignored session was not recorded"; FAIL=1
fi
if MARATHON_SESSION_BLOCKLIST_DIR="$BLOCKS" marathon_session_is_ignored "session-b" "$RUN_REG"; then
  echo "FAIL: a different session inherited the ignore"; FAIL=1
else
  echo "PASS: a different session remains allowed"
fi
if env -u CODEX_THREAD_ID CLAUDE_SESSION_ID="session-a" MARATHON_SESSION_BLOCKLIST_DIR="$BLOCKS" \
  bash -c '. "$1"; marathon_session_is_ignored "session-a" "$2"' _ "$LOCATE" "$RUN_REG"; then
  echo "FAIL: Claude inherited Codex ignore state for the same raw session id"; FAIL=1
else
  echo "PASS: ignore state is isolated by runtime namespace"
fi
STATUS="$(CODEX_THREAD_ID="session-a" MARATHON_SESSION_BLOCKLIST_DIR="$BLOCKS" \
  MARATHON_SESSION_BINDINGS_DIR="$BINDINGS8" MARATHON_REGISTRY="$REG6" CLAUDE_PROJECT_DIR="$SESSION_ROOT" bash "$LOCATE" session-status)"
assert "session-status reports ignored" "$STATUS" \
  "marathon: idempotent | session=session-a | ignored | dir=$RUN_REG_CANON"
CODEX_THREAD_ID="session-a" MARATHON_SESSION_BLOCKLIST_DIR="$BLOCKS" \
  MARATHON_REGISTRY="$REG6" bash "$LOCATE" allow-here "$RUN_REG" >/dev/null
if MARATHON_SESSION_BLOCKLIST_DIR="$BLOCKS" marathon_session_is_ignored "session-a" "$RUN_REG"; then
  echo "FAIL: allow-here did not remove the exact exception"; FAIL=1
else
  echo "PASS: allow-here restores the session"
fi

echo
echo "=== Scenario 9: positive session bindings isolate concurrent marathons ==="
BINDINGS="$TMP/session-bindings"
RUN_INDEX="$TMP/run-index"
RUN_A="$TMP/concurrent/run-a"; RUN_B="$TMP/concurrent/run-b"
mk_run "$RUN_A" "owned by session-a"
mk_run "$RUN_B" "owned by session-b"
RUN_A="$(cd "$RUN_A" && pwd -P)"
RUN_B="$(cd "$RUN_B" && pwd -P)"
CODEX_THREAD_ID="session-a" MARATHON_SESSION_BINDINGS_DIR="$BINDINGS" MARATHON_RUN_INDEX_DIR="$RUN_INDEX" \
  bash "$LOCATE" bind-here "$RUN_A" >/dev/null
assert "session-a binding succeeds" "$?" "0"
CODEX_THREAD_ID="session-b" MARATHON_SESSION_BINDINGS_DIR="$BINDINGS" MARATHON_RUN_INDEX_DIR="$RUN_INDEX" \
  bash "$LOCATE" bind-here "$RUN_B" >/dev/null
assert "session-b binding succeeds" "$?" "0"
. "$LOCATE"
RUN_ID_A="$(awk -F: '/^run_id:[[:space:]]*/ { sub(/^[[:space:]]+/, "", $2); print $2; exit }' "$RUN_A/RUN.md")"
RUN_ID_B="$(awk -F: '/^run_id:[[:space:]]*/ { sub(/^[[:space:]]+/, "", $2); print $2; exit }' "$RUN_B/RUN.md")"
case "$RUN_ID_A" in
  ????????-????-4???-[89ab]???-????????????) echo "PASS: run-a receives an immutable UUIDv4" ;;
  *) echo "FAIL: run-a has invalid run_id [$RUN_ID_A]"; FAIL=1 ;;
esac
assert "binding stores run_id instead of a mutable path" "$(cat "$BINDINGS/codex/session-a")" "$RUN_ID_A"
assert "run index maps run_id to canonical path" "$(cat "$RUN_INDEX/$RUN_ID_A")" "$RUN_A"
RUN_DUP="$TMP/concurrent/run-duplicate-id"
mkdir -p "$RUN_DUP"
cp "$RUN_A/RUN.md" "$RUN_DUP/RUN.md"
CODEX_THREAD_ID="duplicate-owner" MARATHON_SESSION_BINDINGS_DIR="$BINDINGS" MARATHON_RUN_INDEX_DIR="$RUN_INDEX" \
  bash "$LOCATE" bind-here "$RUN_DUP" >/dev/null 2>&1
assert "a live run_id cannot identify two directories" "$?" "1"

MARATHON_SESSION_BINDINGS_DIR="$BINDINGS" MARATHON_RUN_INDEX_DIR="$RUN_INDEX" CODEX_THREAD_ID="session-a" marathon_locate_for_session "$TMP" ".harness/runs" "session-a"
assert "session-a resolves only run-a" "$MARATHON_RUN_DIR" "$RUN_A"
MARATHON_SESSION_BINDINGS_DIR="$BINDINGS" MARATHON_RUN_INDEX_DIR="$RUN_INDEX" CODEX_THREAD_ID="session-b" marathon_locate_for_session "$TMP" ".harness/runs" "session-b"
assert "session-b resolves only run-b" "$MARATHON_RUN_DIR" "$RUN_B"
MARATHON_SESSION_BINDINGS_DIR="$BINDINGS" MARATHON_RUN_INDEX_DIR="$RUN_INDEX" CODEX_THREAD_ID="session-c" marathon_locate_for_session "$TMP" ".harness/runs" "session-c" >/dev/null 2>&1
assert "unbound session does not inherit the freshest run" "$?" "1"
CODEX_THREAD_ID="session-c" MARATHON_SESSION_BINDINGS_DIR="$BINDINGS" MARATHON_RUN_INDEX_DIR="$RUN_INDEX" \
  bash "$LOCATE" bind-here "$RUN_A" >/dev/null 2>&1
assert "one run cannot be bound to a second session" "$?" "1"
CODEX_THREAD_ID="session-a" MARATHON_SESSION_BINDINGS_DIR="$BINDINGS" MARATHON_RUN_INDEX_DIR="$RUN_INDEX" \
  bash "$LOCATE" bind-here "$RUN_B" >/dev/null 2>&1
assert "one session cannot be rebound without explicit unbind" "$?" "1"
CODEX_THREAD_ID="session-a" MARATHON_SESSION_BINDINGS_DIR="$BINDINGS" MARATHON_RUN_INDEX_DIR="$RUN_INDEX" \
  bash "$LOCATE" unbind-here >/dev/null
MARATHON_SESSION_BINDINGS_DIR="$BINDINGS" MARATHON_RUN_INDEX_DIR="$RUN_INDEX" CODEX_THREAD_ID="session-a" marathon_locate_for_session "$TMP" ".harness/runs" "session-a" >/dev/null 2>&1
assert "unbind removes only session-a ownership" "$?" "1"
MARATHON_SESSION_BINDINGS_DIR="$BINDINGS" MARATHON_RUN_INDEX_DIR="$RUN_INDEX" CODEX_THREAD_ID="session-b" marathon_locate_for_session "$TMP" ".harness/runs" "session-b"
assert "unbind leaves session-b ownership intact" "$MARATHON_RUN_DIR" "$RUN_B"

# Runtime is part of the ownership key. Equal raw IDs from different agent
# runtimes are independent conversations and must not collide.
RUN_CLAUDE="$TMP/concurrent/run-claude"
mk_run "$RUN_CLAUDE" "owned by claude session-a"
RUN_CLAUDE="$(cd "$RUN_CLAUDE" && pwd -P)"
env -u CODEX_THREAD_ID CLAUDE_SESSION_ID="session-a" MARATHON_SESSION_BINDINGS_DIR="$BINDINGS" \
  MARATHON_RUN_INDEX_DIR="$RUN_INDEX" bash "$LOCATE" bind-here "$RUN_CLAUDE" >/dev/null
assert "same raw session id can exist in another runtime namespace" "$?" "0"
RUN_ID_CLAUDE="$(awk -F: '/^run_id:[[:space:]]*/ { sub(/^[[:space:]]+/, "", $2); print $2; exit }' "$RUN_CLAUDE/RUN.md")"
assert "claude binding is namespaced" "$(cat "$BINDINGS/claude/session-a")" "$RUN_ID_CLAUDE"
env -u CODEX_THREAD_ID CLAUDE_SESSION_ID="session-a" MARATHON_SESSION_BINDINGS_DIR="$BINDINGS" \
  MARATHON_RUN_INDEX_DIR="$RUN_INDEX" bash -c '. "$1"; marathon_locate_for_session "$2" ".harness/runs" "session-a"; printf "%s" "$MARATHON_RUN_DIR"' _ "$LOCATE" "$TMP" > "$TMP/claude-located"
assert "claude session resolves only its own run" "$(cat "$TMP/claude-located")" "$RUN_CLAUDE"

RUN_LEGACY="$TMP/concurrent/run-legacy"
mk_run "$RUN_LEGACY" "legacy path binding"
RUN_LEGACY="$(cd "$RUN_LEGACY" && pwd -P)"
printf '%s\n' "$RUN_LEGACY" > "$BINDINGS/legacy-session"
CODEX_THREAD_ID="legacy-session" MARATHON_SESSION_BINDINGS_DIR="$BINDINGS" \
  MARATHON_RUN_INDEX_DIR="$RUN_INDEX" bash -c '. "$1"; marathon_locate_for_session "$2" ".harness/runs" "legacy-session"; printf "%s" "$MARATHON_RUN_DIR"' _ "$LOCATE" "$TMP" > "$TMP/legacy-located"
assert "legacy path binding resolves during migration" "$(cat "$TMP/legacy-located")" "$RUN_LEGACY"
RUN_ID_LEGACY="$(awk -F: '/^run_id:[[:space:]]*/ { sub(/^[[:space:]]+/, "", $2); print $2; exit }' "$RUN_LEGACY/RUN.md")"
assert "legacy RUN.md receives a run_id once" "$(cat "$BINDINGS/codex/legacy-session")" "$RUN_ID_LEGACY"
[ ! -f "$BINDINGS/legacy-session" ] && echo "PASS: legacy path binding is removed after migration" \
  || { echo "FAIL: legacy path binding survived migration"; FAIL=1; }

RUN_LEGACY_STALE="$TMP/concurrent/run-legacy-stale"
mk_run "$RUN_LEGACY_STALE" "stale legacy path binding"
RUN_LEGACY_STALE="$(cd "$RUN_LEGACY_STALE" && pwd -P)"
touch -d "30 days ago" "$RUN_LEGACY_STALE/RUN.md" 2>/dev/null || touch -t 202601010000 "$RUN_LEGACY_STALE/RUN.md"
printf '%s\n' "$RUN_LEGACY_STALE" > "$BINDINGS/legacy-stale"
CODEX_THREAD_ID="legacy-stale" MARATHON_SESSION_BINDINGS_DIR="$BINDINGS" \
  MARATHON_RUN_INDEX_DIR="$RUN_INDEX" bash -c '. "$1"; marathon_locate_for_session "$2" ".harness/runs" "legacy-stale"' _ "$LOCATE" "$TMP" >/dev/null 2>&1
assert "stale legacy binding is pruned instead of refreshed by migration" "$?" "1"
if grep -q '^run_id:' "$RUN_LEGACY_STALE/RUN.md"; then
  echo "FAIL: stale legacy RUN.md was mutated during migration"; FAIL=1
else
  echo "PASS: stale legacy RUN.md remains untouched"
fi

RUN_RACE="$TMP/concurrent/run-race"
mk_run "$RUN_RACE" "concurrent bind race"
RACE_BINDINGS="$TMP/session-bindings-race"
(CODEX_THREAD_ID="race-a" MARATHON_SESSION_BINDINGS_DIR="$RACE_BINDINGS" MARATHON_RUN_INDEX_DIR="$RUN_INDEX" \
  bash "$LOCATE" bind-here "$RUN_RACE" >/dev/null 2>&1) & PID_A=$!
(CODEX_THREAD_ID="race-b" MARATHON_SESSION_BINDINGS_DIR="$RACE_BINDINGS" MARATHON_RUN_INDEX_DIR="$RUN_INDEX" \
  bash "$LOCATE" bind-here "$RUN_RACE" >/dev/null 2>&1) & PID_B=$!
wait "$PID_A"; RC_A=$?
wait "$PID_B"; RC_B=$?
SUCCESS_COUNT=0
[ "$RC_A" -eq 0 ] && SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
[ "$RC_B" -eq 0 ] && SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
assert "simultaneous claims produce exactly one owner" "$SUCCESS_COUNT" "1"
OWNER_COUNT="$(find "$RACE_BINDINGS" -type f ! -path '*/.locks/*' 2>/dev/null | wc -l | tr -d ' ')"
assert "race leaves exactly one binding file" "$OWNER_COUNT" "1"
RACE_RUN_ID_COUNT="$(grep -c '^run_id:' "$RUN_RACE/RUN.md" 2>/dev/null || true)"
assert "race assigns exactly one immutable run_id" "$RACE_RUN_ID_COUNT" "1"
RACE_RUN_ID="$(awk -F: '/^run_id:[[:space:]]*/ { sub(/^[[:space:]]+/, "", $2); print $2; exit }' "$RUN_RACE/RUN.md")"
RACE_BOUND_ID="$(find "$RACE_BINDINGS" -type f ! -path '*/.locks/*' -exec sed -n '1p' {} \; 2>/dev/null)"
assert "race winner binds the run_id persisted in RUN.md" "$RACE_BOUND_ID" "$RACE_RUN_ID"

echo
echo "=== Scenario 10: preflight proves the complete four-hook runtime bundle ==="
PREFLIGHT_LOCATE="$HERE/../../../templates/.harness/hooks/marathon-locate.sh"
bash "$LOCATE" preflight > /tmp/marathon-locate-out-$$ 2>&1
assert "authoring locator resolves the rendered runtime bundle" "$?" "0"
bash "$PREFLIGHT_LOCATE" preflight > /tmp/marathon-locate-out-$$ 2>&1
assert "complete hook bundle passes preflight" "$?" "0"
INCOMPLETE="$TMP/incomplete-hooks"
mkdir -p "$INCOMPLETE"
cp "$PREFLIGHT_LOCATE" "$INCOMPLETE/marathon-locate.sh"
bash "$INCOMPLETE/marathon-locate.sh" preflight > /tmp/marathon-locate-out-$$ 2>&1
RC=$?
assert "incomplete hook bundle fails preflight" "$RC" "2"
MISSING_COUNT="$(grep -c 'required hook missing' /tmp/marathon-locate-out-$$ 2>/dev/null || true)"
assert "preflight names all three missing consumers" "$MISSING_COUNT" "3"

rm -f /tmp/marathon-locate-out-$$

echo
if [ "$FAIL" -eq 0 ]; then
  echo "RESULT: ALL SCENARIOS PASSED"
  exit 0
else
  echo "RESULT: THERE ARE FAILURES — see FAIL lines above"
  exit 1
fi
