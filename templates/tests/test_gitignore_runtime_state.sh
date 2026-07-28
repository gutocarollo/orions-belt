#!/usr/bin/env bash
# Every path the harness WRITES at runtime must be ignored by the .gitignore
# block the harness itself installs.
#
# Real gap (2026-07-28): the seed covered {{ harness_evidence_dir }} (the
# ui-evidence PNG dir), .harness/runs/ and .harness/requests/, but NOT four
# other paths the shipped code writes on its own:
#   .harness/evidence/        proof_evidence.py manifests — the exact path the
#                             prova-de-conclusao skill mandates, so every verdict
#                             the completion gate demands left a committable file
#   .harness/pids/            dev-doctor PID registry (machine-local)
#   .harness/install-backups/ VERBATIM copies of the target's pre-merge files
#   .harness/install-journal.json  installer rollback transaction state
#
# The backup tree is the severe one: `git add -A` after an install would commit
# a duplicate of whatever the four shared surfaces contained before the merge.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
WORK="$(mktemp -d /tmp/orions-gitignore-runtime.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT
FAIL=0

assert() { if eval "$2"; then echo "PASS: $1"; else echo "FAIL: $1"; FAIL=1; fi; }
command -v uvx >/dev/null 2>&1 || { echo "SKIP: uvx unavailable"; exit 77; }

TARGET="$WORK/project"
mkdir -p "$TARGET"
git init -q "$TARGET"
git -C "$TARGET" config user.email t@t.test
git -C "$TARGET" config user.name Tester

"$REPO_ROOT/harness-install.sh" "$TARGET" --vcs-ref HEAD \
  --data project_name=ignore-test --data owner_name=Tester \
  --data use_claude=true --data use_codex=false --defaults >"$WORK/install.log" 2>&1
assert "install succeeded" '[ -f "$TARGET/.gitignore" ]'

# `git check-ignore` only matches a trailing-slash pattern when it can tell the
# path is a directory, so always probe a FILE inside each one.
ignored() { git -C "$TARGET" check-ignore -q "$1"; }

for rel in \
  ".harness/runs/RUN.md" \
  ".harness/requests/session-x.md" \
  ".claude/evidence/before.png" \
  ".harness/evidence/proof.json" \
  ".harness/pids/web.pid" \
  ".harness/install-backups/AGENTS.md.bak" \
  ".harness/install-journal.json" \
  ".harness/lib/__pycache__/x.pyc" \
; do
  assert "runtime path is ignored: $rel" "ignored '$rel'"
done

# Harness SOURCE must stay tracked — an over-broad rule would hide the hooks.
for rel in \
  ".harness/hooks/completion-gate.py" \
  ".harness/lib/proof_evidence.py" \
  ".harness/harness.conf" \
  ".harness/install-manifest.json" \
  ".claude/settings.json" \
; do
  assert "harness source is NOT ignored: $rel" "! ignored '$rel'"
done

# End-to-end: a real proof manifest + a real backup must not reach the index.
mkdir -p "$TARGET/.harness/evidence" "$TARGET/.harness/install-backups"
echo '{"schema_version":1}' > "$TARGET/.harness/evidence/proof.json"
echo 'segredo-do-usuario-pre-merge' > "$TARGET/.harness/install-backups/AGENTS.md.bak"
git -C "$TARGET" add -A >/dev/null 2>&1
STAGED="$(git -C "$TARGET" diff --cached --name-only)"
assert "git add -A does not stage the proof manifest" \
  '! printf "%s" "$STAGED" | grep -q "harness/evidence/"'
assert "git add -A does not stage installer backups" \
  '! printf "%s" "$STAGED" | grep -q "harness/install-backups/"'
assert "git add -A still stages the harness hooks" \
  'printf "%s" "$STAGED" | grep -q "harness/hooks/completion-gate.py"'

exit "$FAIL"
