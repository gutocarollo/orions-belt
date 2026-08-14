#!/usr/bin/env bash
# marathon-locate — where the active marathon lives, resolved ONCE.
#
# MATERIALIZATION (orions-belt): a copy of engine/hooks/marathon-locate.sh
# (the authoring/testing source inside the orions-belt repo) for the target
# project. Byte-identical to the source except for this header — this file
# takes no dependency on _tooling_conf.py or any other in-repo path, so
# nothing needs adapting when it lands outside orions-belt.
#
# WHY IT EXISTS. Each of the three marathon hooks resolved its root as
# "$CLAUDE_PROJECT_DIR" (or the Codex equivalent) and stopped there. That
# assumes the run directory lives inside the session's project directory.
# When a session is opened in one repo and the work happens in another
# working directory, all three degrade to a SILENT no-op: the gate does not
# block, the reinject does not reinject, and the precompact does not stamp
# the journal.
#
# MEASURED 2026-08-01 (multi-repo field report). A marathon whose run
# directory lived in a second working directory, driven from a session
# anchored on a different project directory, ran for hours and produced ZERO
# `.stop-strikes` files, and a compaction of that session injected no
# <marathon-run-state> at all. The report from the field — "the marathon gate
# never re-arms and it always stops" — is exactly this mechanism, and
# nothing in the hooks said so out loud.
#
# The failure is silent BY CONSTRUCTION: `[ -f "$ACTIVE" ] || exit 0` cannot
# distinguish "there is no marathon" (the correct state in the vast majority
# of sessions, and the reason the hook must stay quiet) from "the marathon
# exists somewhere I never looked". Both take the same branch.
#
# TWO SOURCES, tried in this order:
#
#   1. $ROOT/$RUNS_DIR/ACTIVE — the local file. Its content may be a SLUG
#      (historical behaviour, unchanged) or an ABSOLUTE PATH to a run
#      directory (cross-repo pointer, new). A path is accepted verbatim, so
#      a project can point at a marathon that lives in a sibling repository
#      without any of the hooks guessing.
#
#   2. $HOME/.harness/marathon-active — the user-level registry, one
#      absolute run directory path per line. This is what makes a marathon
#      portable across repositories WITHOUT scanning the filesystem: the
#      marathon skill appends a line at bootstrap and deletes it at
#      teardown. Discovery by globbing sibling directories was rejected — it
#      would block a session because of an unrelated repository's forgotten
#      ACTIVE, and a gate with false positives gets disabled by its owner,
#      which is worse than a gate that under-fires.
#
#      Registry path is $HOME/.harness/ (not $HOME/.claude/): this project
#      installs on Claude, Codex and Antigravity (use_claude/use_codex/
#      use_antigravity in copier.yml) — a Codex-only or Antigravity-only
#      install has no ".claude" anywhere, and a registry named after one
#      runtime would be invisible to, or confusing from, the others. Every
#      project-level shared directory in this framework is already ".harness/"
#      for the same reason; the user-level registry follows the same rule.
#
# PRUNING DEAD ENTRIES. The registry is durable state living OUTSIDE any
# repo, so it rots: one forgotten teardown would block unrelated future
# sessions forever. An entry whose RUN.md has not been touched for more than
# HARNESS_MARATHON_STALE_DAYS (default 7, read by the caller from
# .harness/harness.conf and exported before sourcing this file — this
# library itself takes no dependency on _tooling_conf.py, so it stays
# testable standalone) is REMOVED from the registry and ignored, as is an
# entry whose RUN.md no longer exists. The cut is on the mtime of RUN.md,
# not of the directory: the skill requires updating RUN.md every time an
# item closes, so that mtime IS the marathon's sign of life — the same
# signal the strike counter already trusts to tell progress from spinning.
#
# WHICH LIVE ENTRY WINS. The registry is user-level, so it routinely holds
# runs from SEVERAL repositories at once (measured 2026-08-12: 10 entries
# across 3 projects). Adopting the FIRST live line — the original behaviour —
# means a session in project A can be handed project B's checklist: the stop
# gate then blocks A's turn demanding B's "next action", which reads exactly
# like the gate misfiring. Order in a file is not a signal about relevance, so
# the choice is now explicit: a run that lives INSIDE this project's root wins;
# among runs that do not, the one whose RUN.md was touched most recently wins
# (same freshness signal the strike counter and the pruner already trust).
#
# PAUSE. A marathon can be suspended without losing its state: a `PAUSED` file
# next to RUN.md. While it exists and has not expired, NOTHING may resume the
# run on its own — the stop gate does not block (so the agent is free to work
# on anything else) and the reinject injects only a short paused notice instead
# of the checklist, because injecting the checklist IS what makes a model pick
# the work back up. When the window expires the state becomes `expired`, which
# is deliberately NOT the same as "resume": the agent must ASK the owner
# whether to resume, extend, or end it. Unparseable or absent `until` means
# paused-forever, never auto-resume — the fail-safe points at asking, never at
# executing.
#
# USAGE (sourced by the hooks):
#   . "$(dirname "$0")/marathon-locate.sh"
#   marathon_locate "$ROOT" "$RUNS_DIR" || exit 0
#   # then read MARATHON_RUN_DIR / MARATHON_RUN_MD / MARATHON_SLUG
#   #           MARATHON_SOURCE_KIND (local|registry) / MARATHON_ACTIVE_FILE
#   marathon_pause_state          # then read MARATHON_PAUSE_STATUS
#   #           none | paused | expired, plus MARATHON_PAUSE_UNTIL / _REASON
#
# USAGE (executed, by the marathon skill):
#   bash marathon-locate.sh register <run-dir>     # idempotent
#   bash marathon-locate.sh unregister <run-dir>
#   bash marathon-locate.sh locate [root] [runs-dir]   # prints the run dir, or exits 1
#   bash marathon-locate.sh pause [<until>] [reason...]   # until: YYYY-MM-DD |
#   #           YYYY-MM-DDTHH:MM | +Nd | +Nh | manual (DEFAULT: +24h)
#   bash marathon-locate.sh resume                 # lifts the pause (does NOT execute)
#   bash marathon-locate.sh status                 # one line: slug, open items, pause state
#   bash marathon-locate.sh ignore-here            # this session ignores the located run
#   bash marathon-locate.sh allow-here             # undo ignore-here for this session
#   bash marathon-locate.sh session-status         # allowed|ignored for this session/run

MARATHON_RUN_DIR=""
MARATHON_RUN_MD=""
MARATHON_SLUG=""
MARATHON_SOURCE_KIND=""
MARATHON_ACTIVE_FILE=""
MARATHON_PAUSE_FILE=""
MARATHON_PAUSE_STATUS=""
MARATHON_PAUSE_UNTIL=""
MARATHON_PAUSE_REASON=""
MARATHON_PAUSE_AT=""

# Captured AT SOURCE TIME. Inside a sourced file "$0" is the CONSUMER (the
# hook doing the sourcing), not this file — so a teardown hint built from
# "$0" would tell the user to run `bash marathon-stop-gate.sh unregister …`,
# a command that does not exist.
MARATHON_LOCATE_SELF="${BASH_SOURCE[0]}"

marathon_registry_path() {
  echo "${MARATHON_REGISTRY:-$HOME/.harness/marathon-active}"
}

marathon_session_id() { # [$1 hook-payload session_id]
  local id="${1:-${CODEX_THREAD_ID:-${CLAUDE_SESSION_ID:-}}}" clean
  [ -n "$id" ] || return 1
  clean="$(printf '%s' "$id" | tr -cd 'A-Za-z0-9._:-')"
  [ "$clean" = "$id" ] || return 1
  printf '%s\n' "$id"
}

marathon_session_blocklist_dir() {
  echo "${MARATHON_SESSION_BLOCKLIST_DIR:-$HOME/.harness/marathon-session-blocklist}"
}

_marathon_canonical_run_dir() { # [$1 run-dir]
  (cd "${1:-$MARATHON_RUN_DIR}" 2>/dev/null && pwd -P)
}

marathon_session_is_ignored() { # $1 session-id, [$2 run-dir]
  local session file run
  session="$(marathon_session_id "${1:-}")" || return 1
  file="$(marathon_session_blocklist_dir)/$session"
  [ -f "$file" ] || return 1
  run="$(_marathon_canonical_run_dir "${2:-$MARATHON_RUN_DIR}")" || return 1
  grep -qxF "$run" "$file" 2>/dev/null
}

marathon_ignore_here() { # [$1 run-dir]
  local session run dir file
  session="$(marathon_session_id)" || {
    echo "marathon-locate: no session identity (CODEX_THREAD_ID/CLAUDE_SESSION_ID)" >&2
    return 2
  }
  if [ -n "${1:-}" ]; then
    run="$(_marathon_canonical_run_dir "$1")" || return 1
    [ -f "$run/RUN.md" ] || { echo "marathon-locate: $run has no RUN.md" >&2; return 1; }
  else
    _marathon_cli_locate || { echo "marathon-locate: no active marathon found" >&2; return 1; }
    run="$(_marathon_canonical_run_dir "$MARATHON_RUN_DIR")" || return 1
  fi
  dir="$(marathon_session_blocklist_dir)"; file="$dir/$session"
  mkdir -p "$dir" || return 1
  touch "$file" || return 1
  grep -qxF "$run" "$file" 2>/dev/null || printf '%s\n' "$run" >> "$file"
  echo "ignored here: $(basename "$run") | session=$session | dir=$run"
}

marathon_allow_here() { # [$1 run-dir]
  local session run dir file tmp
  session="$(marathon_session_id)" || {
    echo "marathon-locate: no session identity (CODEX_THREAD_ID/CLAUDE_SESSION_ID)" >&2
    return 2
  }
  if [ -n "${1:-}" ]; then
    run="$(_marathon_canonical_run_dir "$1")" || return 1
  else
    _marathon_cli_locate || { echo "marathon-locate: no active marathon found" >&2; return 1; }
    run="$(_marathon_canonical_run_dir "$MARATHON_RUN_DIR")" || return 1
  fi
  dir="$(marathon_session_blocklist_dir)"; file="$dir/$session"
  [ -f "$file" ] || { echo "allowed here: $(basename "$run") | session=$session | dir=$run"; return 0; }
  tmp="$file.tmp.$$"
  grep -vxF "$run" "$file" > "$tmp" 2>/dev/null || : > "$tmp"
  mv -f "$tmp" "$file" || { rm -f "$tmp"; return 1; }
  [ -s "$file" ] || rm -f "$file"
  echo "allowed here: $(basename "$run") | session=$session | dir=$run"
}

marathon_session_status() {
  local session
  session="$(marathon_session_id)" || {
    echo "marathon-locate: no session identity (CODEX_THREAD_ID/CLAUDE_SESSION_ID)" >&2
    return 2
  }
  _marathon_cli_locate || { echo "marathon: none active"; return 1; }
  if marathon_session_is_ignored "$session" "$MARATHON_RUN_DIR"; then
    echo "marathon: $MARATHON_SLUG | session=$session | ignored | dir=$MARATHON_RUN_DIR"
  else
    echo "marathon: $MARATHON_SLUG | session=$session | allowed | dir=$MARATHON_RUN_DIR"
  fi
}

# Accept a candidate run directory. A directory without RUN.md is NOT a
# marathon — refusing it here is what keeps a half-created or already-archived
# directory from arming the gate.
_marathon_accept() {
  [ -n "${1:-}" ] || return 1
  [ -f "$1/RUN.md" ] || return 1
  MARATHON_RUN_DIR="$1"
  MARATHON_RUN_MD="$1/RUN.md"
  MARATHON_SLUG="$(basename "$1")"
  MARATHON_SOURCE_KIND="${2:-}"
  MARATHON_ACTIVE_FILE="${3:-}"
  return 0
}

_marathon_under_root() { # $1 root, $2 candidate
  [ -n "$1" ] || return 1
  case "$2" in "$1"/*) return 0 ;; esac
  return 1
}

# Walk the registry: prune dead lines, keep live ones, and adopt ONE of them.
# Rewrites the file only when something actually changed, so a healthy registry
# is never touched.
#
# Adoption is by preference, not by file order (see the header): a run inside
# $root wins; otherwise the freshest RUN.md wins. File order carried no
# meaning and made the winner depend on which project happened to register
# first — a session could be handed an unrelated repository's checklist.
_marathon_scan_registry() {
  local reg="$1" root="${2:-}" stale_days now cutoff line mtime kept="" changed=0
  local in_root="" best="" best_mtime=-1
  [ -f "$reg" ] || return 1
  stale_days="${HARNESS_MARATHON_STALE_DAYS:-7}"
  case "$stale_days" in ''|*[!0-9]*) stale_days=7 ;; esac
  now="$(date +%s)"
  cutoff=$(( now - stale_days * 86400 ))
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      "") continue ;;
      \#*) kept="${kept}${line}"$'\n'; continue ;;
    esac
    if [ ! -f "$line/RUN.md" ]; then changed=1; continue; fi
    mtime="$(stat -c %Y "$line/RUN.md" 2>/dev/null || stat -f %m "$line/RUN.md" 2>/dev/null || echo 0)"
    if [ "$mtime" -lt "$cutoff" ]; then changed=1; continue; fi
    kept="${kept}${line}"$'\n'
    if [ -z "$in_root" ] && _marathon_under_root "$root" "$line"; then in_root="$line"; fi
    if [ "$mtime" -gt "$best_mtime" ]; then best="$line"; best_mtime="$mtime"; fi
  done < "$reg"
  if [ "$changed" -eq 1 ]; then
    if printf '%s' "$kept" > "$reg.tmp.$$" 2>/dev/null; then
      mv -f "$reg.tmp.$$" "$reg" 2>/dev/null || rm -f "$reg.tmp.$$" 2>/dev/null
    else
      rm -f "$reg.tmp.$$" 2>/dev/null
    fi
  fi
  [ -n "$in_root" ] && best="$in_root"
  [ -n "$best" ] || return 1
  _marathon_accept "$best" registry "$reg"
}

marathon_locate() {
  local root="${1:-}" runs_dir="${2:-.harness/runs}" active value
  MARATHON_RUN_DIR=""; MARATHON_RUN_MD=""; MARATHON_SLUG=""
  MARATHON_SOURCE_KIND=""; MARATHON_ACTIVE_FILE=""
  MARATHON_PAUSE_FILE=""; MARATHON_PAUSE_STATUS=""
  MARATHON_PAUSE_UNTIL=""; MARATHON_PAUSE_REASON=""; MARATHON_PAUSE_AT=""
  if [ -n "$root" ]; then
    active="$root/$runs_dir/ACTIVE"
    if [ -f "$active" ]; then
      value="$(head -1 "$active" | tr -d '[:space:]')"
      case "$value" in
        "") : ;;
        /*) _marathon_accept "$value" local "$active" && return 0 ;;
        *)  _marathon_accept "$root/$runs_dir/$value" local "$active" && return 0 ;;
      esac
    fi
  fi
  _marathon_scan_registry "$(marathon_registry_path)" "$root"
}

# ---------------------------------------------------------------- pause -----
#
# One field per line, "key: value", so the file is readable and editable by
# hand — the owner must be able to push the date out with an editor without
# needing the CLI.

_marathon_field() { # $1 file, $2 key
  sed -n "s/^[[:space:]]*$2[[:space:]]*:[[:space:]]*//p" "$1" 2>/dev/null | head -1
}

# A local 12-digit stamp (YYYYMMDDHHMM) out of every accepted spelling, so the
# comparison is a plain integer one and needs no timezone arithmetic and no
# GNU-only `date -d`. Empty output = no deadline (paused until a human says
# otherwise); "INVALID" = unreadable, which the callers treat as paused too.
_marathon_stamp() { # $1 raw "until"
  local raw="${1:-}" n digits stamp y mo d h mi
  case "$raw" in
    ''|manual|MANUAL|indefinite|indefinido|forever) echo ""; return 0 ;;
    +[0-9]*d|+[0-9]*D)
      n="${raw#+}"; n="${n%[dD]}"
      date -v+"${n}"d +%Y%m%d%H%M 2>/dev/null || date -d "+$n days" +%Y%m%d%H%M 2>/dev/null || echo INVALID
      return 0 ;;
    +[0-9]*h|+[0-9]*H)
      n="${raw#+}"; n="${n%[hH]}"
      date -v+"${n}"H +%Y%m%d%H%M 2>/dev/null || date -d "+$n hours" +%Y%m%d%H%M 2>/dev/null || echo INVALID
      return 0 ;;
  esac
  digits="$(printf '%s' "$raw" | tr -cd '0-9')"
  if [ "${#digits}" -ge 12 ]; then stamp="${digits:0:12}"
  elif [ "${#digits}" -eq 10 ]; then stamp="${digits}00"
  elif [ "${#digits}" -eq 8 ]; then stamp="${digits}0000"
  else echo INVALID; return 0
  fi
  # RANGE CHECK (measured 2026-08-12 by test_marathon_pause.sh scenario 9):
  # stripping the separators alone accepted "31-02-2026" — the day-first
  # spelling — as year 3102, a pause that would never expire while the owner
  # believed they had set February. Silently paused-forever is the worst outcome
  # of a typo, so an out-of-range field is rejected loudly instead.
  # Calendar-exact validation (Feb 30) is deliberately NOT attempted: it needs
  # `date -d` (GNU) or `date -j -f` (BSD) and buys much less than it costs — an
  # impossible day slips to the next one, it does not become a wrong year.
  y="${stamp:0:4}"; mo="${stamp:4:2}"; d="${stamp:6:2}"; h="${stamp:8:2}"; mi="${stamp:10:2}"
  if [ "$y" -lt 2000 ] || [ "$y" -gt 2999 ] \
     || [ "$mo" -lt 1 ] || [ "$mo" -gt 12 ] \
     || [ "$d" -lt 1 ]  || [ "$d" -gt 31 ] \
     || [ "$h" -gt 23 ] || [ "$mi" -gt 59 ]; then
    echo INVALID; return 0
  fi
  echo "$stamp"
}

_marathon_human_stamp() { # $1 = 12-digit stamp
  local s="$1"
  [ "${#s}" -eq 12 ] || { echo "$s"; return 0; }
  echo "${s:0:4}-${s:4:2}-${s:6:2}T${s:8:2}:${s:10:2}"
}

# Reads the pause state of an already-located marathon (or of an explicit run
# directory). Sets MARATHON_PAUSE_STATUS to none|paused|expired.
marathon_pause_state() { # [$1 run-dir]
  local dir="${1:-$MARATHON_RUN_DIR}" f target now
  MARATHON_PAUSE_FILE=""; MARATHON_PAUSE_STATUS="none"
  MARATHON_PAUSE_UNTIL=""; MARATHON_PAUSE_REASON=""; MARATHON_PAUSE_AT=""
  [ -n "$dir" ] || return 0
  f="$dir/PAUSED"
  [ -f "$f" ] || return 0
  MARATHON_PAUSE_FILE="$f"
  MARATHON_PAUSE_UNTIL="$(_marathon_field "$f" until)"
  MARATHON_PAUSE_REASON="$(_marathon_field "$f" reason)"
  MARATHON_PAUSE_AT="$(_marathon_field "$f" paused_at)"
  target="$(_marathon_stamp "$MARATHON_PAUSE_UNTIL")"
  if [ -z "$target" ] || [ "$target" = INVALID ]; then
    # No readable deadline → stays paused. The fail-safe direction is "keep
    # sleeping and ask", never "start executing".
    [ "$target" = INVALID ] && MARATHON_PAUSE_UNTIL="manual (unreadable date: ${MARATHON_PAUSE_UNTIL})"
    [ -z "$MARATHON_PAUSE_UNTIL" ] && MARATHON_PAUSE_UNTIL="manual"
    MARATHON_PAUSE_STATUS="paused"
    return 0
  fi
  now="$(date +%Y%m%d%H%M)"
  if [ "$now" -ge "$target" ]; then MARATHON_PAUSE_STATUS="expired"; else MARATHON_PAUSE_STATUS="paused"; fi
  return 0
}

_marathon_cli_locate() {
  marathon_locate "${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}" \
                  "${HARNESS_RUNS_DIR:-.harness/runs}"
}

_marathon_journal() { # $1 line
  [ -f "$MARATHON_RUN_MD" ] || return 0
  printf -- '- %s %s\n' "$(date +%H:%M)" "$1" >> "$MARATHON_RUN_MD"
}

marathon_pause() { # $1 until (default +24h), $@ reason
  # DEFAULT = 24h (owner's decision, 2026-08-12). A bare `pause` is the command
  # typed when stepping away, not a declaration that the run is abandoned — so
  # the window closes on its own the next day and comes back as a QUESTION.
  # `manual` still exists for an explicitly open-ended parking, but it has to be
  # asked for: defaulting to "forever" would quietly bury runs.
  local raw="${1:-+24h}" reason stamp resolved
  [ "$#" -gt 0 ] && shift
  reason="$*"
  _marathon_cli_locate || { echo "marathon-locate: no active marathon to pause" >&2; return 1; }
  stamp="$(_marathon_stamp "$raw")"
  if [ "$stamp" = INVALID ]; then
    echo "marathon-locate: cannot read '$raw' as a date — use YYYY-MM-DD, YYYY-MM-DDTHH:MM, +Nd, +Nh or manual" >&2
    return 2
  fi
  # The RESOLVED absolute instant is what gets stored: writing "+3d" verbatim
  # would be re-evaluated against "now" on every check and would never expire.
  if [ -z "$stamp" ]; then resolved="manual"; else resolved="$(_marathon_human_stamp "$stamp")"; fi
  {
    echo "until: $resolved"
    echo "reason: ${reason:-(not given)}"
    echo "paused_at: $(date +%Y-%m-%dT%H:%M)"
  } > "$MARATHON_RUN_DIR/PAUSED"
  _marathon_journal "marathon PAUSED until $resolved${reason:+ — $reason}"
  echo "paused: $MARATHON_SLUG until $resolved (state kept in $MARATHON_RUN_DIR)"
}

marathon_resume() {
  _marathon_cli_locate || { echo "marathon-locate: no active marathon found" >&2; return 1; }
  if [ -f "$MARATHON_RUN_DIR/PAUSED" ]; then
    rm -f "$MARATHON_RUN_DIR/PAUSED"
    # A fresh strike count: the blocks accumulated before the pause say nothing
    # about whether the resumed run is making progress.
    rm -f "$MARATHON_RUN_DIR/.stop-strikes"
    _marathon_journal "marathon RESUMED (pause lifted)"
    echo "resumed: $MARATHON_SLUG"
  else
    echo "not paused: $MARATHON_SLUG"
  fi
}

marathon_status() {
  local open
  if ! _marathon_cli_locate; then echo "marathon: none active"; return 1; fi
  marathon_pause_state
  open=$(grep -c '^[[:space:]]*- \[[ ~]\]' "$MARATHON_RUN_MD" 2>/dev/null || true)
  case "$MARATHON_PAUSE_STATUS" in
    paused)  echo "marathon: $MARATHON_SLUG | open=$open | PAUSED until $MARATHON_PAUSE_UNTIL | reason: ${MARATHON_PAUSE_REASON:-(not given)} | dir: $MARATHON_RUN_DIR" ;;
    expired) echo "marathon: $MARATHON_SLUG | open=$open | PAUSE EXPIRED (was until $MARATHON_PAUSE_UNTIL) — ask the owner before resuming | dir: $MARATHON_RUN_DIR" ;;
    *)       echo "marathon: $MARATHON_SLUG | open=$open | running | dir: $MARATHON_RUN_DIR" ;;
  esac
}

# The exact command that ends this marathon, so every hook message can say it
# without re-deriving where the pointer lives.
marathon_teardown_hint() {
  case "$MARATHON_SOURCE_KIND" in
    local) echo "rm $MARATHON_ACTIVE_FILE" ;;
    registry) echo "bash $MARATHON_LOCATE_SELF unregister $MARATHON_RUN_DIR" ;;
    *) echo "rm <runs-dir>/ACTIVE" ;;
  esac
}

marathon_register() {
  local dir reg
  dir="$(cd "${1:-.}" 2>/dev/null && pwd)" || { echo "marathon-locate: $1 does not exist" >&2; return 1; }
  [ -f "$dir/RUN.md" ] || { echo "marathon-locate: $dir has no RUN.md — not a marathon" >&2; return 1; }
  reg="$(marathon_registry_path)"
  mkdir -p "$(dirname "$reg")"
  touch "$reg"
  grep -qxF "$dir" "$reg" 2>/dev/null || printf '%s\n' "$dir" >> "$reg"
  echo "$dir"
}

marathon_unregister() {
  local dir reg
  dir="$(cd "${1:-.}" 2>/dev/null && pwd || echo "${1:-}")"
  reg="$(marathon_registry_path)"
  [ -f "$reg" ] || return 0
  grep -vxF "$dir" "$reg" > "$reg.tmp.$$" 2>/dev/null || : > "$reg.tmp.$$"
  mv -f "$reg.tmp.$$" "$reg" 2>/dev/null || rm -f "$reg.tmp.$$" 2>/dev/null
}

# Executed rather than sourced → tiny CLI, so the marathon skill has one
# command to call and this file has something a test can drive directly.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  set -uo pipefail
  case "${1:-}" in
    register) marathon_register "${2:-}" ;;
    unregister) marathon_unregister "${2:-}" ;;
    locate)
      if marathon_locate "${2:-${CLAUDE_PROJECT_DIR:-}}" "${3:-.harness/runs}"; then
        echo "$MARATHON_RUN_DIR"
      else
        exit 1
      fi
      ;;
    pause) shift; marathon_pause "$@" ;;
    resume) marathon_resume ;;
    status) marathon_status ;;
    ignore-here) marathon_ignore_here "${2:-}" ;;
    allow-here) marathon_allow_here "${2:-}" ;;
    session-status) marathon_session_status ;;
    *)
      echo "usage: $0 {register <run-dir>|unregister <run-dir>|locate [root] [runs-dir]|pause [<until>] [reason...]|resume|status|ignore-here [run-dir]|allow-here [run-dir]|session-status}" >&2
      exit 64
      ;;
  esac
fi
