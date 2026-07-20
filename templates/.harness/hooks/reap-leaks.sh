#!/usr/bin/env bash
# Stop hook — reaps agent tooling leaks at the end of every turn so they don't
# pile up (headless chromium leaked from raw Playwright scripts without teardown,
# orphaned MCP servers, etc.). Delegates to the `reap` mode of the generic dev-doctor.
#
# NON-BLOCKING (always exit 0). It reports ownership/registry warnings even
# when nothing was killed. It never touches unregistered or cross-project PIDs.
#
# MATERIALIZATION (F9-fixes): it used to point at `scripts/dev-doctor.sh` (a script
# the framework never installed — a dead reference in every target project); it now
# points at `.harness/hooks/dev-doctor.sh`, the generic dev-doctor that SHIPS
# alongside it (reap caps come from HARNESS_REAP_CHROMIUM_MAX_AGE_SECONDS etc. in
# the central config).
set -uo pipefail
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
out="$(bash "$ROOT/.harness/hooks/dev-doctor.sh" reap 2>/dev/null || true)"
n=$(printf '%s\n' "$out" | sed -n 's/.* \([0-9]\{1,\}\) process(es) reaped/\1/p')
# Speaks ONLY when it reaped something (n>0). The runaway WARN (persistent
# process) is emitted on SessionStart (dev-doctor status), once per session — it
# does not spam every turn.
if [ "${n:-0}" -gt 0 ]; then
  echo "reap-leaks: $n process(es) reaped this turn"
  printf '%s\n' "$out" | grep -E 'leaked|orphan tooling|reaped' | sed 's/^/  /'
else
  printf '%s\n' "$out" | grep -E 'WARN' | sed 's/^/reap-leaks: /' || true
fi
exit 0
