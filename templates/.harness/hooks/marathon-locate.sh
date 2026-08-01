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
# MEASURED 2026-08-01 (learnhouse field report). A marathon whose run
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
# USAGE (sourced by the hooks):
#   . "$(dirname "$0")/marathon-locate.sh"
#   marathon_locate "$ROOT" "$RUNS_DIR" || exit 0
#   # then read MARATHON_RUN_DIR / MARATHON_RUN_MD / MARATHON_SLUG
#   #           MARATHON_SOURCE_KIND (local|registry) / MARATHON_ACTIVE_FILE
#
# USAGE (executed, by the marathon skill):
#   bash marathon-locate.sh register <run-dir>     # idempotent
#   bash marathon-locate.sh unregister <run-dir>
#   bash marathon-locate.sh locate [root] [runs-dir]   # prints the run dir, or exits 1

MARATHON_RUN_DIR=""
MARATHON_RUN_MD=""
MARATHON_SLUG=""
MARATHON_SOURCE_KIND=""
MARATHON_ACTIVE_FILE=""

# Captured AT SOURCE TIME. Inside a sourced file "$0" is the CONSUMER (the
# hook doing the sourcing), not this file — so a teardown hint built from
# "$0" would tell the user to run `bash marathon-stop-gate.sh unregister …`,
# a command that does not exist.
MARATHON_LOCATE_SELF="${BASH_SOURCE[0]}"

marathon_registry_path() {
  echo "${MARATHON_REGISTRY:-$HOME/.harness/marathon-active}"
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

# Walk the registry: prune dead lines, keep live ones, and adopt the first
# live entry. Rewrites the file only when something actually changed, so a
# healthy registry is never touched.
_marathon_scan_registry() {
  local reg="$1" stale_days now cutoff line mtime kept="" changed=0 hit=1
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
    if [ "$hit" -ne 0 ]; then
      _marathon_accept "$line" registry "$reg" && hit=0
    fi
  done < "$reg"
  if [ "$changed" -eq 1 ]; then
    if printf '%s' "$kept" > "$reg.tmp.$$" 2>/dev/null; then
      mv -f "$reg.tmp.$$" "$reg" 2>/dev/null || rm -f "$reg.tmp.$$" 2>/dev/null
    else
      rm -f "$reg.tmp.$$" 2>/dev/null
    fi
  fi
  return "$hit"
}

marathon_locate() {
  local root="${1:-}" runs_dir="${2:-.harness/runs}" active value
  MARATHON_RUN_DIR=""; MARATHON_RUN_MD=""; MARATHON_SLUG=""
  MARATHON_SOURCE_KIND=""; MARATHON_ACTIVE_FILE=""
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
  _marathon_scan_registry "$(marathon_registry_path)"
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
    *)
      echo "usage: $0 {register <run-dir>|unregister <run-dir>|locate [root] [runs-dir]}" >&2
      exit 64
      ;;
  esac
fi
