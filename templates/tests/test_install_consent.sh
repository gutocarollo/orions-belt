#!/usr/bin/env bash
# The installer may not write anything without explicit approval, and an edit made inside a
# generated block must be visible BEFORE the next apply silently discards it.
#
# Invariants locked here (adopter report, 2026-07-30):
#   1. Consent is fail-CLOSED. A non-interactive run without `--yes` aborts and leaves the target
#      byte-untouched — "no answer" never reads as "yes".
#   2. The plan is itemized before it is applied, and the classes that REPLACE project-authored
#      content (`marked-block`, `structured-json`) are called out separately from the
#      ownership-checked ones, because only the former can lose local work without a conflict.
#   3. `--yes` (or HARNESS_INSTALL_ASSUME_YES=1) is the ONLY way to pre-approve, and it is honoured.
#   4. Re-installing over a block the project edited is exactly the case that must stop and name the
#      file — the adopter's original symptom was a design-token canon re-appearing in a backend.
#   5. The block guard is PRECISE: silent on an intact block, silent on edits ABOVE/BELOW the
#      markers (that region belongs to the project), loud only on edits INSIDE. A guard that fires
#      on legitimate input trains the operator to ignore it.
#   6. Every marked-block file gets a block hash — all three syntaxes, including the `#`-comment
#      form used by `.gitignore` (a first cut handled only `<!-- -->` and silently skipped it).
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
WORK="$(mktemp -d /tmp/orions-consent.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT
FAIL=0
assert() { if eval "$2"; then echo "PASS: $1"; else echo "FAIL: $1"; FAIL=1; fi; }
command -v uvx >/dev/null 2>&1 || { echo "SKIP: uvx unavailable"; exit 77; }

new_target() {
  local t="$1"
  mkdir -p "$t"
  git -C "$t" init -q
  git -C "$t" config user.email t@example.com
  git -C "$t" config user.name t
  echo "# project" > "$t/README.md"
  git -C "$t" add -A >/dev/null
  git -C "$t" commit -qm init
}
# every path except the pre-existing README.md and the .git dir
target_paths() { find "$1" -mindepth 1 -not -path "$1/.git*" -not -name README.md | wc -l | tr -d ' '; }
install() { timeout 600 "$REPO_ROOT/harness-install.sh" "$@" --defaults --vcs-ref HEAD \
              --data project_name=consent --data owner_name=tester </dev/null; }

# ---- 1/2: fail-closed, itemized -----------------------------------------------------------------
T1="$WORK/t1"; new_target "$T1"
install "$T1" > "$WORK/t1.log" 2>&1; RC1=$?
assert "non-interactive run without --yes aborts (65)" '[ "$RC1" -eq 65 ]'
assert "refused plan wrote NOTHING into the target" '[ "$(target_paths "$T1")" -eq 0 ]'
assert "refused plan wrote no ownership manifest" '[ ! -e "$T1/.harness/install-manifest.json" ]'
assert "the plan was itemized for the human" 'grep -q "install-consent: the harness wants to write" "$WORK/t1.log"'
assert "the abort names how to proceed" 'grep -q -- "--yes" "$WORK/t1.log"'

# ---- 3: --yes is honoured -----------------------------------------------------------------------
install "$T1" --yes > "$WORK/t1b.log" 2>&1; RC2=$?
assert "--yes applies the plan" '[ "$RC2" -eq 0 ]'
assert "approved plan wrote the manifest" '[ -f "$T1/.harness/install-manifest.json" ]'
assert "approval mode is announced" 'grep -q "plan pre-approved" "$WORK/t1b.log"'

# ---- 6: block hash for EVERY marked-block file, both marker syntaxes ----------------------------
assert "every marked-block file recorded a block hash" \
  'python3 -c "
import json,sys
m=json.load(open(sys.argv[1]))[\"files\"]
mb={k:v for k,v in m.items() if v.get(\"strategy\")==\"marked-block\"}
sys.exit(0 if mb and all(v.get(\"last_applied_block_sha256\") for v in mb.values()) else 1)
" "$T1/.harness/install-manifest.json"'
assert "the .gitignore (# comment marker) is among them" \
  'python3 -c "
import json,sys
m=json.load(open(sys.argv[1]))[\"files\"]
e=m.get(\".gitignore\",{})
sys.exit(0 if e.get(\"strategy\")==\"marked-block\" and e.get(\"last_applied_block_sha256\") else 1)
" "$T1/.harness/install-manifest.json"'

# ---- 5: guard precision -------------------------------------------------------------------------
GUARD="$T1/.harness/hooks/harness-block-guard.py"
assert "block guard is installed" '[ -f "$GUARD" ]'
OUT_INTACT="$(CLAUDE_PROJECT_DIR="$T1" python3 "$GUARD" 2>&1)"
assert "guard is SILENT on an intact block" '[ -z "$OUT_INTACT" ]'

printf '\n## project section\n' >> "$T1/AGENTS.md"
OUT_OUTSIDE="$(CLAUDE_PROJECT_DIR="$T1" python3 "$GUARD" 2>&1)"
assert "guard is SILENT on an edit BELOW the markers (no false positive)" '[ -z "$OUT_OUTSIDE" ]'

python3 - "$T1" <<'PY'
import pathlib, sys
p = pathlib.Path(sys.argv[1]) / ".claude" / "CLAUDE.md"
t = p.read_text(encoding="utf-8")
j = t.index("<!-- orions-belt:end -->")
p.write_text(t[:j] + "\n## injected INSIDE the generated block\n" + t[j:], encoding="utf-8")
PY
OUT_INSIDE="$(CLAUDE_PROJECT_DIR="$T1" python3 "$GUARD" 2>&1)"
assert "guard WARNS on an edit inside the block" 'grep -q "edited IN PLACE" <<< "$OUT_INSIDE"'
assert "guard names the offending file" 'grep -q ".claude/CLAUDE.md" <<< "$OUT_INSIDE"'
assert "guard does NOT name the file edited only below the markers" '! grep -q "AGENTS.md" <<< "$OUT_INSIDE"'

# ---- 4: re-install over an edited block stops and names it --------------------------------------
install "$T1" > "$WORK/t1c.log" 2>&1; RC3=$?
assert "re-install over an edited block needs approval (65)" '[ "$RC3" -eq 65 ]'
assert "the itemized plan flags the replacing class" 'grep -q "REPLACES CONTENT THE PROJECT MAY HAVE AUTHORED" "$WORK/t1c.log"'
assert "it names the marked-block file by path and strategy" 'grep -q "\.claude/CLAUDE\.md  \[marked-block" "$WORK/t1c.log"'
assert "it explains that approving restores removed canon" 'grep -q "brings it back" "$WORK/t1c.log"'

# ---- dry-run stays non-mutating and needs no approval -------------------------------------------
T2="$WORK/t2"; new_target "$T2"
install "$T2" --dry-run > "$WORK/t2.log" 2>&1; RC4=$?
assert "--dry-run succeeds without approval" '[ "$RC4" -eq 0 ]'
assert "--dry-run wrote nothing" '[ "$(target_paths "$T2")" -eq 0 ]'

if [ "$FAIL" -eq 0 ]; then echo; echo "ALL INSTALL CONSENT GATES PASSED."; else echo; echo "INSTALL CONSENT GATES FAILED."; fi
exit "$FAIL"
