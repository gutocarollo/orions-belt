#!/usr/bin/env bash
# test_marathon_pause.sh — END-TO-END proof of the PAUSE mechanism and of the
# registry ADOPTION PREFERENCE, driving the real hooks as subprocesses.
#
# WHY THIS EXISTS (measured 2026-08-12, field report across 3 repos).
#
# 1. There was no way to suspend a marathon. The only exits were "finish it" or
#    "delete ACTIVE / unregister", and the second one throws the durable state
#    away — the checklist, the decisions, the journal. So a run that had to wait
#    on something external stayed armed, and the stop gate kept pushing the
#    agent back into it every single turn.
#
# 2. The registry adopted the FIRST live line. The registry is user-level and
#    routinely holds runs from several projects at once (10 entries across 3
#    projects when this was measured), so a session in project A could be handed
#    project B's checklist. Reads exactly like the gate misfiring.
#
# What only this file asserts:
#   - a paused run makes the gate inert and keeps the reinject from injecting the
#     CHECKLIST (injecting it is what makes a model resume on its own);
#   - an expired window neither blocks nor resumes: it produces a question;
#   - `+Nd` is stored RESOLVED, so a relative pause actually expires;
#   - an unreadable date stays paused (fail-safe = ask, never execute);
#   - resume clears the strike counter and re-arms the gate;
#   - a run inside the session's root beats a fresher run in another repo.
#
# Usage: bash engine/hooks/tests/test_marathon_pause.sh
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
# Overridable so the SAME suite can be pointed at a real installed project
# (MARATHON_HOOKS_SRC=/path/to/project/.harness/hooks) — proving the copy that
# actually runs there behaves, not only the template it came from.
HOOKS_SRC="${MARATHON_HOOKS_SRC:-$REPO/templates/.harness/hooks}"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export MARATHON_RUN_INDEX_DIR="$TMP/run-index"

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
assert_file() {
  if [ -f "$2" ]; then echo "PASS: $1"; else echo "FAIL: $1 — $2 missing"; FAIL=1; fi
}
assert_nofile() {
  if [ -f "$2" ]; then echo "FAIL: $1 — $2 exists"; FAIL=1; else echo "PASS: $1"; fi
}

PROJ="$TMP/proj"; WORK="$TMP/work"
mkdir -p "$PROJ/.harness/hooks" "$WORK/.harness/runs/my-run"
cp "$HOOKS_SRC/marathon-locate.sh" "$HOOKS_SRC/marathon-stop-gate.sh" \
   "$HOOKS_SRC/marathon-reinject.sh" "$HOOKS_SRC/marathon-precompact.sh" "$PROJ/.harness/hooks/"
chmod +x "$PROJ/.harness/hooks/"*.sh

HOOKS="$PROJ/.harness/hooks"
LOCATE="$HOOKS/marathon-locate.sh"
GATE="$HOOKS/marathon-stop-gate.sh"
RUNDIR="$WORK/.harness/runs/my-run"
RUNMD="$RUNDIR/RUN.md"
REG="$TMP/marathon-active"
BINDINGS="$TMP/session-bindings"
OUT="$TMP/out"

write_run() { # $1 = checklist body
  local run_id
  run_id="$(awk -F: '/^run_id:[[:space:]]*/ { sub(/^[[:space:]]+/, "", $2); print $2; exit }' "$RUNMD" 2>/dev/null)"
  [ -n "$run_id" ] || run_id="$(python3 -c 'import uuid; print(uuid.uuid4())')"
  cat > "$RUNMD" <<EOF
# RUN: my-run
run_id: $run_id
goal: fixture

## Checklist (source of truth)
- [x] done item
$1

## Next action
keep going

## Journal
EOF
}
write_run "- [ ] UNIQUEOPENITEM"
echo "$RUNDIR" > "$REG"
CODEX_THREAD_ID="session-pause" MARATHON_SESSION_BINDINGS_DIR="$BINDINGS" \
  bash "$LOCATE" bind-here "$RUNDIR" >/dev/null

run_gate() {
  MARATHON_REGISTRY="$REG" MARATHON_SESSION_BINDINGS_DIR="$BINDINGS" CLAUDE_PROJECT_DIR="$PROJ" \
    bash "$GATE" <<< '{"session_id":"session-pause","stop_hook_active":false}' >"$OUT" 2>&1
}
run_reinject() {
  MARATHON_REGISTRY="$REG" MARATHON_SESSION_BINDINGS_DIR="$BINDINGS" CLAUDE_PROJECT_DIR="$PROJ" \
    bash "$HOOKS/marathon-reinject.sh" <<< '{"session_id":"session-pause"}' >"$OUT" 2>&1
}
cli() {
  CODEX_THREAD_ID="session-pause" MARATHON_SESSION_BINDINGS_DIR="$BINDINGS" \
    MARATHON_REGISTRY="$REG" CLAUDE_PROJECT_DIR="$PROJ" bash "$LOCATE" "$@"
}

echo "=== Scenario 1: baseline (not paused) — gate blocks, reinject pushes the checklist ==="
rm -f "$RUNDIR/PAUSED"
run_gate; assert_exit "open item blocks" "$?" 2
run_reinject
assert_grep "reinject injects the checklist when running" "UNIQUEOPENITEM" "$OUT"
assert_grep "reinject says ACTIVE" "Marathon ACTIVE" "$OUT"

echo
echo "=== Scenario 2: pause with NO date → 24h window (the owner's default), gate goes inert ==="
# A bare `pause` must not park the run forever: the default window closes the
# next day and comes back as a question. Asserted against a stamp computed here,
# so a silent change of the default (or of the storage format) fails loudly.
cli pause > "$TMP/cli" 2>&1; assert_exit "pause CLI succeeds" "$?" 0
assert_file "PAUSED file written next to RUN.md" "$RUNDIR/PAUSED"
WANT24="$(date -v+24H +%Y-%m-%dT%H:%M 2>/dev/null || date -d '+24 hours' +%Y-%m-%dT%H:%M)"
assert_grep "the default window is 24h, resolved to an absolute instant" "^until: $WANT24\$" "$RUNDIR/PAUSED"
assert_nogrep "the default is NOT open-ended" "^until: manual" "$RUNDIR/PAUSED"
assert_grep "pause is journalled in RUN.md" "marathon PAUSED until $WANT24" "$RUNMD"
run_gate; assert_exit "paused run must NOT block the stop" "$?" 0
assert_nogrep "paused gate says nothing at all" "." "$OUT"

echo
echo "=== Scenario 2b: open-ended parking still available, but only when asked for ==="
cli pause manual "sem data, decisão do dono" >/dev/null 2>&1
assert_grep "explicit manual is honoured" "^until: manual" "$RUNDIR/PAUSED"
run_gate; assert_exit "manual pause must not block" "$?" 0
run_reinject; assert_grep "manual pause reports as paused" 'status="paused"' "$OUT"
cli pause >/dev/null 2>&1   # back to the default window for the next scenario

echo
echo "=== Scenario 3: reinject must NOT hand a paused run its checklist ==="
run_reinject
assert_grep "reinject marks the run as paused" 'status="paused"' "$OUT"
assert_grep "reinject forbids resuming" "DO NOT resume" "$OUT"
assert_nogrep "the checklist is withheld while paused" "UNIQUEOPENITEM" "$OUT"
assert_nogrep "the Next action is withheld while paused" "keep going" "$OUT"

echo
echo "=== Scenario 4: resume re-arms the gate and clears the strikes ==="
echo "9 0" > "$RUNDIR/.stop-strikes"
cli resume > "$TMP/cli" 2>&1; assert_exit "resume CLI succeeds" "$?" 0
assert_nofile "PAUSED removed" "$RUNDIR/PAUSED"
assert_nofile "strike counter cleared on resume" "$RUNDIR/.stop-strikes"
assert_grep "resume is journalled" "marathon RESUMED" "$RUNMD"
run_gate; assert_exit "resumed run blocks again" "$?" 2

echo
echo "=== Scenario 5: dated pause in the future → paused ==="
cli pause 2099-01-01 "aguardando o cliente" >/dev/null 2>&1
assert_grep "future date stored" "^until: 2099-01-01T00:00" "$RUNDIR/PAUSED"
assert_grep "reason stored" "^reason: aguardando o cliente" "$RUNDIR/PAUSED"
run_gate; assert_exit "future pause must not block" "$?" 0
cli status > "$TMP/cli" 2>&1
assert_grep "status reports PAUSED" "PAUSED until 2099-01-01T00:00" "$TMP/cli"

echo
echo "=== Scenario 6: relative +Nd is stored RESOLVED (a stored '+2d' would never expire) ==="
cli pause +2d "esperando build" >/dev/null 2>&1
assert_nogrep "the raw relative form is not what gets stored" "+2d" "$RUNDIR/PAUSED"
assert_grep "resolved to an absolute instant" "^until: 20[0-9][0-9]-[01][0-9]-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]$" "$RUNDIR/PAUSED"
run_gate; assert_exit "a +2d pause is still in the future" "$?" 0

echo
echo "=== Scenario 7: expired window → neither blocks nor resumes; it ASKS ==="
cat > "$RUNDIR/PAUSED" <<'EOF'
until: 2020-01-01T00:00
reason: janela curta de teste
paused_at: 2019-12-31T23:00
EOF
run_gate; rc=$?
assert_exit "expired pause must not block" "$rc" 0
assert_grep "gate reports the expiry to the owner" "pause window ended" "$OUT"
assert_grep "gate states nothing was resumed automatically" "NOTHING was resumed automatically" "$OUT"
assert_grep "gate offers the resume command" "marathon-locate.sh resume" "$OUT"
python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "$OUT" \
  && echo "PASS: the expiry message is valid JSON for the harness" \
  || { echo "FAIL: expiry message is not valid JSON"; FAIL=1; }
run_reinject
assert_grep "reinject marks the expiry" 'status="pause-expired"' "$OUT"
assert_grep "reinject demands the question first" "MANDATORY, BEFORE ANY WORK" "$OUT"
assert_grep "reinject bans executing the next action" "Do NOT execute" "$OUT"
assert_grep "reinject still carries the state as context for the question" "UNIQUEOPENITEM" "$OUT"

echo
echo "=== Scenario 8: an unreadable date stays PAUSED (fail-safe is asking, never executing) ==="
cat > "$RUNDIR/PAUSED" <<'EOF'
until: quando o Bruno responder
reason: data escrita a mão
paused_at: 2026-08-12T10:00
EOF
run_gate; assert_exit "unreadable date must not block" "$?" 0
assert_nogrep "and must not be reported as expired either" "pause window ended" "$OUT"
run_reinject
assert_grep "unreadable date is treated as paused" 'status="paused"' "$OUT"
assert_grep "the unreadable value is surfaced, not swallowed" "unreadable date" "$OUT"

echo
echo "=== Scenario 9: pause CLI refuses a date it cannot resolve ==="
rm -f "$RUNDIR/PAUSED"
cli pause 31-02-2026 "formato errado" >"$TMP/cli" 2>&1; rc=$?
assert_exit "an unresolvable spelling is rejected" "$rc" 2
assert_nofile "nothing is written when the date is rejected" "$RUNDIR/PAUSED"
assert_grep "the error names the accepted spellings" "YYYY-MM-DD" "$TMP/cli"

echo
echo "=== Scenario 10: expired pause on a FINISHED checklist stays silent (no nagging) ==="
write_run "- [x] UNIQUEOPENITEM"
cat > "$RUNDIR/PAUSED" <<'EOF'
until: 2020-01-01T00:00
reason: terminou e ficou pausado
paused_at: 2019-12-31T23:00
EOF
run_gate; assert_exit "closed checklist releases the stop" "$?" 0
assert_nogrep "and says nothing about the expired window" "pause window ended" "$OUT"
write_run "- [ ] UNIQUEOPENITEM"

echo
echo "=== Scenario 11: precompact stamps the pause state in the journal ==="
cli pause 2099-01-01 "parada longa" >/dev/null 2>&1
MARATHON_REGISTRY="$REG" MARATHON_SESSION_BINDINGS_DIR="$BINDINGS" CLAUDE_PROJECT_DIR="$PROJ" \
  bash "$HOOKS/marathon-precompact.sh" <<< '{"session_id":"session-pause"}' >/dev/null 2>&1
assert_grep "journal says the compaction happened while paused" "run PAUSED until 2099-01-01T00:00" "$RUNMD"
rm -f "$RUNDIR/PAUSED"

echo
echo "=== Scenario 12: a run INSIDE the session root beats a fresher run elsewhere ==="
# The old rule was file order, which made the winner depend on which project
# registered first. Here the other-repo run is deliberately the FIRST line AND
# the freshest; the local one must still win.
mkdir -p "$PROJ/.harness/runs/local-run"
cp "$RUNMD" "$PROJ/.harness/runs/local-run/RUN.md"
awk '{ sub(/^# RUN: my-run$/, "# RUN: local-run"); print }' "$PROJ/.harness/runs/local-run/RUN.md" > "$TMP/lr" \
  && mv "$TMP/lr" "$PROJ/.harness/runs/local-run/RUN.md"
touch "$RUNMD"                                     # other repo's run is the freshest
printf '%s\n%s\n' "$RUNDIR" "$PROJ/.harness/runs/local-run" > "$REG"
GOT="$(cli locate "$PROJ" ".harness/runs")"
if [ "$GOT" = "$PROJ/.harness/runs/local-run" ]; then
  echo "PASS: the in-root run is adopted over the fresher foreign one"
else
  echo "FAIL: adopted '$GOT', wanted '$PROJ/.harness/runs/local-run'"; FAIL=1
fi

echo
echo "=== Scenario 13: with no in-root candidate, the FRESHEST run wins (not line order) ==="
mkdir -p "$TMP/other/.harness/runs/stale-run"
cp "$RUNMD" "$TMP/other/.harness/runs/stale-run/RUN.md"
touch -t 202608010000 "$TMP/other/.harness/runs/stale-run/RUN.md"   # older, but first in the file
touch "$RUNMD"
printf '%s\n%s\n' "$TMP/other/.harness/runs/stale-run" "$RUNDIR" > "$REG"
GOT="$(cli locate "$PROJ" ".harness/runs" 2>/dev/null)"
if [ "$GOT" = "$RUNDIR" ]; then
  echo "PASS: freshest RUN.md wins among foreign candidates"
else
  echo "FAIL: adopted '$GOT', wanted '$RUNDIR'"; FAIL=1
fi
rm -rf "$PROJ/.harness/runs"

echo
if [ "$FAIL" -eq 0 ]; then
  echo "RESULT: ALL SCENARIOS PASSED"
  exit 0
else
  echo "RESULT: THERE ARE FAILURES — see FAIL lines above"
  exit 1
fi
