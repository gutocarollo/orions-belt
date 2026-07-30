#!/usr/bin/env bash
# test_install_report.sh — the install DECISION REPORT is part of the process:
# every install must emit .harness/INSTALL-REPORT.md with the install/skip
# decisions, the gating flag, and applied examples. Runs a real greenfield
# install via harness-install.sh and asserts the report's content.
#
# Requires uvx + git. Fixture in $TMPDIR; never touches the repo.
set -uo pipefail
# PRE-APPROVED INSTALL (consent gate, 2026-07-30). `harness-install.sh` refuses to write without an
# explicit yes, and a non-interactive caller that does not pre-approve exits 65 with the target
# untouched. A test harness IS automation, so it declares the approval once here instead of adding
# a flag to every invocation — this file drives the installer several times. Removing this line does
# not weaken the suite: it makes every install in it abort, which is the gate working as designed.
export HARNESS_INSTALL_ASSUME_YES=1


HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
INSTALLER="$REPO_ROOT/harness-install.sh"
FAIL=0
assert() { if eval "$2"; then echo "PASS: $1"; else echo "FAIL: $1"; FAIL=1; fi; }

if ! command -v uvx >/dev/null 2>&1; then echo "SKIP: uvx unavailable"; exit 77; fi

WORK="$(mktemp -d "${TMPDIR:-/tmp}/install-report.XXXXXX")"; trap 'rm -rf "$WORK"' EXIT
T="$WORK/proj"; mkdir -p "$T"; git -C "$T" init -q

# UI off (default), no prod, no run command -> several components must be SKIPPED.
"$INSTALLER" "$T" --vcs-ref HEAD --data project_name=rep --data owner_name=R --defaults \
  > "$WORK/install.log" 2>&1 || { echo "FAIL: install failed -- $(tail -5 "$WORK/install.log")"; exit 1; }

R="$T/.harness/INSTALL-REPORT.md"
assert "report file was generated at .harness/INSTALL-REPORT.md" '[ -f "$R" ]'
assert "install stdout advertises the decision report" 'grep -q "decision report:" "$WORK/install.log"'
[ -f "$R" ] || { echo "RESULT: FAILURES"; exit 1; }

assert "report has the components decision table" 'grep -q "Components — installed / skipped" "$R"'
assert "report shows an INSTALLED component with its flag (Claude)" \
  'grep -qE "Claude Code surface.*✅ installed.*use_claude=true" "$R"'
assert "report shows a SKIPPED component with its flag (ui-evidence off by default)" \
  'grep -qE "UI-evidence gate.*⛔ skipped.*use_ui_evidence=false" "$R"'
assert "report explains the run skill was NOT generated (empty run command)" \
  'grep -qE "Dev-stack run skill.*⛔ skipped" "$R"'
assert "report has an applied example (italic) for a decision" 'grep -q "\*" "$R"'
assert "report lists file-level strategies from the manifest (owned)" 'grep -qE "^### owned — [0-9]+ file" "$R"'
assert "report has the one-glance NOT-installed summary" 'grep -q "Not installed — one-glance summary" "$R"'
assert "report records the hook-manager decision" 'grep -q "## 3. Hook manager" "$R"'
assert "report is regenerated on reinstall (idempotent, still valid)" \
  '"$INSTALLER" "$T" --vcs-ref HEAD --data project_name=rep --data owner_name=R --defaults >/dev/null 2>&1 && [ -f "$R" ]'

echo
if [ "$FAIL" -eq 0 ]; then echo "RESULT: INSTALL DECISION REPORT PASSED"; else echo "RESULT: FAILURES"; fi
exit "$FAIL"
