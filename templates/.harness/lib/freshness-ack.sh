#!/usr/bin/env bash
# freshness-ack.sh — record the user's decision after harness-freshness.sh warned
# about a stale/absent instance, so the SessionStart notice stops nagging until
# the template ref changes again. Called by the agent (or by auto-heal).
#
# Usage: freshness-ack.sh <installed|acknowledged>
#   installed    — the instance was (re)installed; the ack is keyed to the fresh
#                  state (and staleness self-clears once the manifest ref catches up).
#   acknowledged — the user chose to keep the current instance as-is for now; the
#                  ack silences the stale/absent notice for THIS template ref.
set -uo pipefail

ACTION="${1:-}"
case "$ACTION" in
  installed|acknowledged) ;;
  *) echo "usage: freshness-ack.sh <installed|acknowledged>" >&2; exit 2 ;;
esac

ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
MANIFEST="$ROOT/.harness/install-manifest.json"
ACK="$ROOT/.harness/.freshness-ack"
mkdir -p "$ROOT/.harness"

# Recompute the same keys harness-freshness.sh checks, so the ack actually silences it.
cur=""
if [ -f "$MANIFEST" ]; then
  source="$(python3 -c "import json;print(json.load(open('$MANIFEST')).get('template',{}).get('source',''))" 2>/dev/null || true)"
  origin="$(git -C "$ROOT" config --get remote.origin.url 2>/dev/null || true)"
  if [ -n "$source" ] && [ "$origin" = "$source" ]; then
    cur="$(git -C "$ROOT" describe --tags --always --dirty 2>/dev/null || true)"
  fi
fi

TS="$(date '+%Y-%m-%d %H:%M:%S %Z')"
{
  echo "stale:${cur:-none}"
  echo "absent:none"
} >> "$ACK"
# De-duplicate while preserving the acked keys.
sort -u "$ACK" -o "$ACK"
echo "freshness-ack: recorded '$ACTION' at $TS (keys: stale:${cur:-none}, absent:none) -> $ACK"
