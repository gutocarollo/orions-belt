#!/usr/bin/env bash
# check-platform.sh — platform preflight (M3/H4, adversarial review).
#
# THE PROBLEM: this framework's hooks/scripts (`.harness/hooks/`,
# `.harness/lib/`) depend on a specific GNU/Linux subset --
# `mapfile`/`declare -A` (Bash >=4; macOS ships Bash 3.2 due to the GPLv3
# license), `stat -c` (GNU coreutils; BSD/macOS uses `stat -f`), `date +%s%N`
# (nanoseconds -- GNU date only; BSD date has no `%N`), `flock` (util-linux,
# Linux -- no native equivalent on macOS) and Python >=3.14. Before this script,
# "portable" was DECLARED nowhere and the failure of one of these deps was
# SILENT -- a hook ran, an unknown `stat -c` turned into stray stderr or a
# wrong value, and the corresponding gate failed/became a no-op with no
# explicit warning at install time.
#
# WHAT THIS SCRIPT DOES: a cheap preflight, runs once (at install time, or at
# any time), reports PASS/MISSING per dependency with the suggested fix
# command. It does not try to port the hooks to pure BSD/POSIX (out of scope
# for this round -- see docs/manual/15-limitacoes-conhecidas.md) -- it just
# makes the gap visible and actionable instead of discovered hook-by-hook.
#
# Exit code: 0 = all REQUIRED dependencies present (even with light warnings);
# 1 = at least one REQUIRED dependency is missing -- the caller
# (harness-install.sh, or the user manually) decides whether to abort or
# proceed aware of the risk (never blocks copier copy/update itself on its
# own, which is platform-agnostic).
set -uo pipefail

MISSING=0
WARN=0

pass() { echo "  OK      $1"; }
fail() { echo "  MISSING $1 -- $2"; MISSING=$((MISSING + 1)); }
warn() { echo "  WARN    $1 -- $2"; WARN=$((WARN + 1)); }

echo "check-platform.sh -- harness platform preflight"
echo "uname: $(uname -a 2>/dev/null || echo 'unavailable')"
echo

# --- Bash >= 4 (mapfile, declare -A) ---
if [ -n "${BASH_VERSINFO:-}" ] && [ "${BASH_VERSINFO[0]}" -ge 4 ]; then
  pass "Bash ${BASH_VERSINFO[0]}.${BASH_VERSINFO[1]} (>=4, supports mapfile/declare -A)"
else
  fail "Bash ${BASH_VERSINFO[0]:-unknown}.x (<4)" \
    "macOS: brew install bash (the system Bash is 3.2, GPLv3); run the hooks with the brew Bash, not /bin/bash"
fi

# --- GNU coreutils: stat -c ---
if stat -c %Y . >/dev/null 2>&1; then
  pass "stat -c (GNU coreutils)"
else
  fail "stat -c (GNU coreutils)" \
    "macOS: brew install coreutils, use 'gstat -c' or prefix PATH with the brew coreutils (see README/manual)"
fi

# --- GNU date: %N (nanoseconds) ---
if date +%s%N 2>/dev/null | grep -qE '^[0-9]{15,}$'; then
  pass "date +%s%N (GNU date, nanoseconds)"
else
  warn "date +%s%N (GNU date, nanoseconds)" \
    "BSD/macOS date does not support %N; scripts that generate unique names by timestamp (e.g. subagent-throttle.sh) collide more easily without nanoseconds -- brew install coreutils + 'gdate'"
fi

# --- flock (util-linux) ---
if command -v flock >/dev/null 2>&1; then
  pass "flock (util-linux)"
else
  fail "flock (util-linux)" \
    "macOS: brew install util-linux (flock does not exist natively); without it, subagent-throttle.sh/subagent-release.sh cannot atomically acquire a slot"
fi

# --- Python >= 3.14 ---
if command -v python3 >/dev/null 2>&1 && \
   python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 14) else 1)' 2>/dev/null; then
  pass "python3 ($(python3 --version 2>&1), required >=3.14)"
elif command -v python3 >/dev/null 2>&1; then
  fail "python3 ($(python3 --version 2>&1), required >=3.14)" \
    "macOS: brew install python@3.14 and place Homebrew bin before /usr/bin in PATH"
else
  fail "python3 >=3.14" "install Python 3.14 (macOS: brew install python@3.14) -- several hooks/scripts (.harness/lib/*.py) require it"
fi

# --- timeout (GNU coreutils) ---
if command -v timeout >/dev/null 2>&1; then
  pass "timeout (GNU coreutils)"
else
  warn "timeout (GNU coreutils)" \
    "macOS: brew install coreutils, use 'gtimeout' or prefix PATH -- used only in non-blocking spots (e.g. provision-push.sh)"
fi

echo
if [ "$MISSING" -gt 0 ]; then
  echo "RESULT: $MISSING REQUIRED dependency(ies) missing, $WARN warning(s). See docs/manual/15-limitacoes-conhecidas.md."
  exit 1
fi
echo "RESULT: all required dependencies present ($WARN non-blocking warning(s))."
exit 0
