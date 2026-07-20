#!/usr/bin/env bash
# harness-freshness.sh — SessionStart drift/freshness guard (both runtimes).
# NON-BLOCKING (always exit 0). It runs on the FIRST prompt of a session and, if
# the installed orions-belt instance is ABSENT or STALE, injects a directive the
# agent surfaces to the user; after the user decides, the agent records it with
# freshness-ack.sh so the nag stops until the template ref changes again.
#
# Detected states:
#   absent — no install manifest and no materialized surfaces (a fresh checkout
#            of a project whose instance is git-ignored/regenerable).
#   stale  — the manifest's template ref is behind the template. Reliable in the
#            SELF-INSTALL / dogfood case (ROOT's git origin == manifest source),
#            where the current ref is `git describe` of ROOT. Remote-only
#            staleness (needs network) is intentionally NOT probed here.
#   fresh  — nothing to say (silent).
#
# Default is WARN-ONLY. HARNESS_AUTOHEAL=1 opts into a hands-free refresh when an
# installer is locatable (self-install: ./harness-install.sh, or $HARNESS_INSTALLER).
set -uo pipefail

ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
MANIFEST="$ROOT/.harness/install-manifest.json"
ACK="$ROOT/.harness/.freshness-ack"

state=fresh
detail=""
cur=""

if [ ! -f "$MANIFEST" ]; then
  # Only speak if the instance genuinely looks un-materialized (avoid nagging on
  # odd partial states we did not create).
  if [ ! -f "$ROOT/AGENTS.md" ] && [ ! -d "$ROOT/.claude" ] && [ ! -d "$ROOT/.agents" ]; then
    state=absent
  else
    exit 0
  fi
else
  read -r ref source < <(python3 -c "import json;t=json.load(open('$MANIFEST')).get('template',{});print(t.get('ref',''), t.get('source',''))" 2>/dev/null || echo " ")
  # Self-install detection: is THIS repo the template it was installed from?
  origin="$(git -C "$ROOT" config --get remote.origin.url 2>/dev/null || true)"
  if [ -n "${source:-}" ] && [ -n "$origin" ] && [ "$origin" = "$source" ]; then
    cur="$(git -C "$ROOT" describe --tags --always --dirty 2>/dev/null || true)"
    if [ -n "$cur" ] && [ -n "${ref:-}" ] && [ "$cur" != "$ref" ]; then
      state=stale
      detail="manifest @ $ref, template @ $cur"
    fi
  fi
fi

[ "$state" = "fresh" ] && exit 0

# Already resolved/acknowledged for this exact situation? Stay quiet.
ackkey="$state:${cur:-none}"
if [ -f "$ACK" ] && grep -Fqx "$ackkey" "$ACK" 2>/dev/null; then
  exit 0
fi

# Opt-in hands-free refresh (only if an installer is locatable).
installer=""
[ -x "$ROOT/harness-install.sh" ] && installer="$ROOT/harness-install.sh"
[ -z "$installer" ] && [ -n "${HARNESS_INSTALLER:-}" ] && [ -x "$HARNESS_INSTALLER" ] && installer="$HARNESS_INSTALLER"
if [ "${HARNESS_AUTOHEAL:-0}" = "1" ] && [ -n "$installer" ]; then
  echo "harness-freshness: HARNESS_AUTOHEAL=1 -> refreshing the instance via $installer ..."
  if bash "$installer" "$ROOT" --vcs-ref HEAD --defaults >/dev/null 2>&1; then
    [ -x "$ROOT/.harness/lib/freshness-ack.sh" ] && bash "$ROOT/.harness/lib/freshness-ack.sh" installed >/dev/null 2>&1 || true
    echo "harness-freshness: instance refreshed and decision recorded."
    exit 0
  fi
  echo "harness-freshness: auto-heal attempt failed; falling back to a warning." >&2
fi

# WARN-ONLY: directive the agent must surface on its first reply, then record.
fix_cmd="run 'harness-install.sh $ROOT --vcs-ref HEAD' from your orions-belt clone"
[ -n "$installer" ] && fix_cmd="run '$installer $ROOT --vcs-ref HEAD'"
{
  echo "[orions-belt freshness] STATE=$state${detail:+ ($detail)}"
  echo "ACTION FOR THE AGENT — surface this on your FIRST reply, then record the decision:"
  if [ "$state" = "absent" ]; then
    echo "  1. Tell the user: the orions-belt instance is NOT materialized in this checkout (skills/hooks/instructions are missing)."
  else
    echo "  1. Tell the user: the orions-belt instance is STALE ($detail) — the template moved since the last install."
  fi
  echo "  2. Offer the fix: $fix_cmd (or set HARNESS_AUTOHEAL=1 for a hands-free refresh next session)."
  echo "  3. After the user decides, RECORD it: 'bash \"$ROOT/.harness/lib/freshness-ack.sh\" <installed|acknowledged>'."
  echo "     (This stops the notice until the template ref changes again. In the 'absent' state the record is implicit: a successful install makes it fresh.)"
}
exit 0
