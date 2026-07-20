#!/usr/bin/env bash
# brownfield-install-eval.sh — reusable adversarial evaluation of an orions-belt
# install against a REAL external repository (brownfield). It reproduces the
# real-use matrix (not "the files exist"): fail-closed collision, byte-a-byte
# preservation, idempotent reinstall, edit-abort on owned files, and hook-manager
# conflicts. Everything is logged so a failing install can be debugged offline.
#
# It NEVER touches the source repo: it `git clone --local`s the tracked content
# (history hard-linked, huge untracked runtime junk left behind) into a disposable
# test clone, then installs there.
#
# Usage:
#   eval/brownfield-install-eval.sh <source-repo> [<logs-dir>]
# Example:
#   eval/brownfield-install-eval.sh /home/augusto/code/WhatsApp_Agent_Chat_slim-shape
#
# Exit 0 = all invariants held (collisions may still be reported as FINDINGS in
# the log; a FINDING is a real-world friction to review, not a test failure).
set -uo pipefail

SRC="${1:?usage: brownfield-install-eval.sh <source-repo> [<logs-dir>]}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAMP_SRC="$(basename "$SRC")"
LOGS="${2:-$REPO_ROOT/eval/last-run-$STAMP_SRC}"
INSTALLER="$REPO_ROOT/harness-install.sh"
CLONE="$(mktemp -d "${TMPDIR:-/tmp}/ob-eval-clone.XXXXXX")"
mkdir -p "$LOGS"

FAIL=0
FINDINGS=()
log() { printf '%s\n' "$*" | tee -a "$LOGS/eval.log"; }
assert() { if eval "$2"; then log "PASS: $1"; else log "FAIL: $1"; FAIL=1; fi; }
finding() { FINDINGS+=("$1"); log "FINDING: $1"; }

: > "$LOGS/eval.log"
log "=== orions-belt brownfield eval — source=$SRC ==="
log "harness ref: $(git -C "$REPO_ROOT" describe --tags --always --dirty)"

# 0. Faithful clone of tracked content (excludes untracked runtime junk).
git clone --local -q "$SRC" "$CLONE" || { log "FATAL: clone failed"; exit 1; }
trap 'rm -rf "$CLONE"' EXIT
log "clone: $(git -C "$CLONE" ls-files | wc -l) tracked files, HEAD $(git -C "$CLONE" rev-parse --short HEAD)"
( cd "$CLONE" && git ls-files -z | xargs -0 sha256sum ) > "$LOGS/baseline.sha256" 2>/dev/null

# 1. Dry-run: must be fail-closed on unowned collisions and leave the target untouched.
"$INSTALLER" "$CLONE" --vcs-ref HEAD --dry-run --plan-json "$LOGS/dryrun-plan.json" \
  --data project_name=eval --data owner_name=Eval --defaults \
  > "$LOGS/dryrun.stdout" 2> "$LOGS/dryrun.stderr"
DRY_EXIT=$?
COLLISIONS=$(grep -cE 'no harness ownership record' "$LOGS/dryrun.stderr" || true)
assert "dry-run leaves the target untouched" '[ "$(git -C "$CLONE" status --short | wc -l)" -eq 0 ]'
if [ "$DRY_EXIT" -eq 2 ] && [ "$COLLISIONS" -gt 0 ]; then
  log "dry-run: fail-closed on $COLLISIONS unowned collision(s) (correct)"
  # Feed the collisions back as --preserve so the install can proceed.
  mapfile -t PRESERVE < <(grep -oE '^  - [^:]+: existing path has no harness ownership' "$LOGS/dryrun.stderr" | sed -E 's/^  - //; s/: existing.*//')
elif [ "$DRY_EXIT" -eq 0 ]; then
  log "dry-run: no collisions (greenfield-like target)"; PRESERVE=()
else
  log "dry-run: unexpected exit=$DRY_EXIT"; FAIL=1; PRESERVE=()
fi

# 2. Real install (preserving each collision = the user's own copy wins).
PARGS=(); for p in "${PRESERVE[@]:-}"; do [ -n "$p" ] && PARGS+=(--preserve "$p"); done
"$INSTALLER" "$CLONE" --vcs-ref HEAD --plan-json "$LOGS/install-plan.json" \
  "${PARGS[@]}" --data project_name=eval --data owner_name=Eval --defaults \
  > "$LOGS/install.stdout" 2> "$LOGS/install.stderr"
assert "install succeeds (exit 0)" '[ "$?" -eq 0 ]'
assert "ownership manifest written" '[ -f "$CLONE/.harness/install-manifest.json" ]'
assert "no install-plan* artifact leaks into the target (G1)" \
  '[ "$(find "$CLONE" -name "install-plan*" | wc -l)" -eq 0 ]'

# 3. Byte-a-byte preservation: only the shared merge surfaces may change.
( cd "$CLONE" && git ls-files -z | xargs -0 sha256sum ) > "$LOGS/after.sha256" 2>/dev/null
comm -13 <(sort "$LOGS/baseline.sha256") <(sort "$LOGS/after.sha256") | awk '{print $2}' | sort -u \
  | grep -vE '^(AGENTS\.md|\.claude/CLAUDE\.md|\.gitignore|\.claude/settings\.json)$' > "$LOGS/unexpected-changes.txt" || true
assert "only merge surfaces (AGENTS/CLAUDE/.gitignore/settings) changed among tracked files" \
  '[ ! -s "$LOGS/unexpected-changes.txt" ]'
for f in AGENTS.md .claude/CLAUDE.md; do
  [ -f "$CLONE/$f" ] || continue
  assert "$f: original content precedes the harness block (append, not clobber)" \
    "[ \"\$(awk '/orions-belt:begin/{exit} {n++} END{print n+0}' \"$CLONE/$f\")\" -gt 0 ]"
  assert "$f: exactly one harness block marker" \
    "[ \"\$(grep -c 'orions-belt:begin' \"$CLONE/$f\")\" -eq 1 ]"
done

# 4. Idempotent reinstall (manifest already records preserve; 0 bytes change).
"$INSTALLER" "$CLONE" --vcs-ref HEAD --data project_name=eval --data owner_name=Eval --defaults \
  > "$LOGS/reinstall.stdout" 2> "$LOGS/reinstall.stderr"
( cd "$CLONE" && git ls-files -z | xargs -0 sha256sum ) > "$LOGS/after-reinstall.sha256" 2>/dev/null
assert "reinstall changes 0 tracked bytes (idempotent)" \
  '[ "$(comm -13 <(sort "$LOGS/after.sha256") <(sort "$LOGS/after-reinstall.sha256") | wc -l)" -eq 0 ]'

# 5. Edit-abort: modifying an owned file makes the next install fail-closed.
OWNED=$(python3 -c "import json;m=json.load(open('$CLONE/.harness/install-manifest.json'));print(next(p for p,e in m['files'].items() if e.get('strategy')=='owned'))" 2>/dev/null || true)
if [ -n "$OWNED" ]; then
  printf '\n# eval local hack\n' >> "$CLONE/$OWNED"
  "$INSTALLER" "$CLONE" --vcs-ref HEAD --dry-run --data project_name=eval --data owner_name=Eval --defaults \
    > /dev/null 2> "$LOGS/editabort.stderr"
  assert "editing an owned file ($OWNED) aborts the next install (exit 2)" '[ "$?" -eq 2 ]'
fi

# 6. Hook-manager conflict detection (FINDINGS, not hard failures).
if [ -f "$CLONE/.pre-commit-config.yaml" ]; then
  # Precise: did the installer acknowledge the pre-commit *framework* specifically?
  # (Its ref-integrity boilerplate mentions the words "pre-commit" generically, so
  # match the config filename / an explicit framework warning, not the substring.)
  if [ "$(git -C "$CLONE" config --get core.hooksPath)" = ".githooks" ] \
     && ! grep -qiE 'pre-commit-config|pre-commit framework|pre-commit\.com' "$LOGS/install.stderr" "$LOGS/install.stdout"; then
    finding "pre-commit framework (.pre-commit-config.yaml) present, but the installer set core.hooksPath=.githooks WITHOUT acknowledging it — hooks the framework installs into .git/hooks are silently bypassed (git ignores .git/hooks once core.hooksPath is set)."
  fi
fi

log ""
log "=== SUMMARY: $([ "$FAIL" -eq 0 ] && echo 'ALL INVARIANTS HELD' || echo 'INVARIANT FAILURES') / ${#FINDINGS[@]} finding(s) ==="
log "logs: $LOGS"
exit "$FAIL"
