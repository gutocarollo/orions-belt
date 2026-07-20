#!/usr/bin/env bash
# Focused regressions for contained runtime hardening. Uses isolated temporary
# repositories/processes and never mutates the Orion's Belt worktree.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
WORK="$(mktemp -d /tmp/orions-contained-safety.XXXXXX)"
CHILD_PID=""
trap '[ -n "$CHILD_PID" ] && kill "$CHILD_PID" 2>/dev/null || true; rm -rf "$WORK"' EXIT
FAIL=0

assert() {
  if eval "$2"; then
    echo "PASS: $1"
  else
    echo "FAIL: $1"
    FAIL=1
  fi
}

# 1. The central parser preserves hashes, spaces, equals, dollars and Unicode.
CONF_ROOT="$WORK/conf"
mkdir -p "$CONF_ROOT/.harness"
cat > "$CONF_ROOT/.harness/harness.conf" <<'EOF'
PROJECT_NAME=C# Academy
PASSWORD="p@ss#word = $cash"
UNICODE="ação 🚀"
BASE=alpha
DERIVED="${BASE}=beta # literal" # actual comment
SINGLE_LITERAL='${BASE}'
ESCAPED_LITERAL="\${BASE}"
COMMENTED=value # comment
APOSTROPHE=O'Reilly
WINDOWS_PATH=C:\tools\bin
EOF
for parser in "$REPO_ROOT/engine/_tooling_conf.py" "$REPO_ROOT/templates/.harness/lib/_tooling_conf.py"; do
  assert "$(basename "$(dirname "$parser")") parser keeps C#" \
    '[ "$(HARNESS_PROJECT_ROOT="$CONF_ROOT" python3 "$parser" get PROJECT_NAME missing)" = "C# Academy" ]'
  assert "$(basename "$(dirname "$parser")") parser keeps quoted special characters" \
    '[ "$(HARNESS_PROJECT_ROOT="$CONF_ROOT" python3 "$parser" get PASSWORD missing)" = '\''p@ss#word = $cash'\'' ]'
  assert "$(basename "$(dirname "$parser")") parser expands variables without losing literal hash" \
    '[ "$(HARNESS_PROJECT_ROOT="$CONF_ROOT" python3 "$parser" get DERIVED missing)" = "alpha=beta # literal" ]'
  assert "$(basename "$(dirname "$parser")") parser keeps Unicode" \
    '[ "$(HARNESS_PROJECT_ROOT="$CONF_ROOT" python3 "$parser" get UNICODE missing)" = "ação 🚀" ]'
  assert "$(basename "$(dirname "$parser")") parser keeps unquoted apostrophes" \
    '[ "$(HARNESS_PROJECT_ROOT="$CONF_ROOT" python3 "$parser" get APOSTROPHE missing)" = "O'\''Reilly" ]'
  assert "$(basename "$(dirname "$parser")") parser keeps unquoted backslashes" \
    '[ "$(HARNESS_PROJECT_ROOT="$CONF_ROOT" python3 "$parser" get WINDOWS_PATH missing)" = "C:\tools\bin" ]'
  assert "$(basename "$(dirname "$parser")") parser keeps single-quoted refs literal" \
    '[ "$(HARNESS_PROJECT_ROOT="$CONF_ROOT" python3 "$parser" get SINGLE_LITERAL missing)" = '\''${BASE}'\'' ]'
  assert "$(basename "$(dirname "$parser")") parser keeps escaped refs literal" \
    '[ "$(HARNESS_PROJECT_ROOT="$CONF_ROOT" python3 "$parser" get ESCAPED_LITERAL missing)" = '\''${BASE}'\'' ]'
done

# 2. git-doctor reports a poisoned state without creating a stash or changing files.
GIT_ROOT="$WORK/git-doctor"
git init -q "$GIT_ROOT"
git -C "$GIT_ROOT" config user.email test@example.test
git -C "$GIT_ROOT" config user.name Test
printf 'base\n' > "$GIT_ROOT/tracked.txt"
git -C "$GIT_ROOT" add tracked.txt
git -C "$GIT_ROOT" commit -qm base
printf 'dirty\n' >> "$GIT_ROOT/tracked.txt"
mkdir -p "$GIT_ROOT/.git/rebase-merge"
BEFORE_STATUS="$(git -C "$GIT_ROOT" status --porcelain)"
BEFORE_STASH="$(git -C "$GIT_ROOT" stash list)"
CLAUDE_PROJECT_DIR="$GIT_ROOT" bash "$REPO_ROOT/templates/.harness/hooks/git-doctor.sh.jinja" \
  > "$WORK/git-doctor.out"
assert "git-doctor is diagnose-only" \
  '[ "$(git -C "$GIT_ROOT" status --porcelain)" = "$BEFORE_STATUS" ]'
assert "git-doctor creates no stash" \
  '[ "$(git -C "$GIT_ROOT" stash list)" = "$BEFORE_STASH" ]'
assert "git-doctor explicitly reports no mutation" \
  'grep -q "No files were changed or stashed" "$WORK/git-doctor.out"'

# 3. Reaper refuses global discovery and honors an explicit ownership lease.
REAP_ROOT="$WORK/reaper"
mkdir -p "$REAP_ROOT/.harness/hooks" "$REAP_ROOT/.harness/lib"
cp "$REPO_ROOT/templates/.harness/hooks/dev-doctor.sh" "$REAP_ROOT/.harness/hooks/"
cp "$REPO_ROOT/templates/.harness/lib/_tooling_conf.py" "$REAP_ROOT/.harness/lib/"
printf 'HARNESS_PID_REGISTRY_DIR=.harness/pids\n' > "$REAP_ROOT/.harness/harness.conf"
(cd "$REAP_ROOT" && bash -c 'exec -a headless_shell sleep 60') & CHILD_PID=$!
sleep 0.1
CLAUDE_PROJECT_DIR="$REAP_ROOT" bash "$REAP_ROOT/.harness/hooks/dev-doctor.sh" reap \
  > "$WORK/reap-unowned.out"
assert "unregistered process remains alive" 'kill -0 "$CHILD_PID" 2>/dev/null'
assert "missing registry is an explicit warning" 'grep -q "WARN no project PID registry" "$WORK/reap-unowned.out"'
mkdir -p "$REAP_ROOT/.harness/pids"
PROC_STAT="$(<"/proc/$CHILD_PID/stat")"; PROC_REST="${PROC_STAT##*) }"
START_TICKS="$(awk '{print $20}' <<<"$PROC_REST")"
printf '%s %s %s\n' "$CHILD_PID" "$START_TICKS" "$(( $(date +%s) + 60 ))" > "$REAP_ROOT/.harness/pids/evidence.pid"
CLAUDE_PROJECT_DIR="$REAP_ROOT" bash "$REAP_ROOT/.harness/hooks/dev-doctor.sh" reap \
  > "$WORK/reap-active-lease.out"
assert "registered tooling with an active lease remains alive" 'kill -0 "$CHILD_PID" 2>/dev/null'
assert "active lease is reported explicitly" 'grep -q "ownership lease is still active" "$WORK/reap-active-lease.out"'
printf '%s %s %s\n' "$CHILD_PID" "$START_TICKS" "$(( $(date +%s) - 1 ))" > "$REAP_ROOT/.harness/pids/evidence.pid"
CLAUDE_PROJECT_DIR="$REAP_ROOT" bash "$REAP_ROOT/.harness/hooks/dev-doctor.sh" reap \
  > "$WORK/reap-owned.out"
for _ in 1 2 3 4 5; do kill -0 "$CHILD_PID" 2>/dev/null || break; sleep 0.1; done
assert "expired registered project-owned tooling is terminated" '! kill -0 "$CHILD_PID" 2>/dev/null'
CHILD_PID=""

# 4. Invalid Git selectors fail, and selftest preserves pre-existing old fixture names.
REF_ROOT="$WORK/ref-integrity"
git init -q "$REF_ROOT"
git -C "$REF_ROOT" config user.email test@example.test
git -C "$REF_ROOT" config user.name Test
mkdir -p "$REF_ROOT/docs" "$REF_ROOT/engine/lint" "$REF_ROOT/.harness/lib"
cp "$REPO_ROOT/engine/_tooling_conf.py" "$REF_ROOT/engine/_tooling_conf.py"
cp "$REPO_ROOT/engine/lint/ref_integrity.py" "$REF_ROOT/engine/lint/ref_integrity.py"
cp "$REPO_ROOT/templates/.harness/lib/_tooling_conf.py" "$REF_ROOT/.harness/lib/_tooling_conf.py"
cp "$REPO_ROOT/templates/.harness/lib/ref_integrity.py" "$REF_ROOT/.harness/lib/ref_integrity.py"
printf 'base\n' > "$REF_ROOT/docs/base.md"
git -C "$REF_ROOT" add . && git -C "$REF_ROOT" commit -qm base
for lint in "$REF_ROOT/engine/lint/ref_integrity.py" "$REF_ROOT/.harness/lib/ref_integrity.py"; do
  HARNESS_PROJECT_ROOT="$REF_ROOT" python3 "$lint" --range DOES_NOT_EXIST..HEAD \
    > "$WORK/ref.out" 2> "$WORK/ref.err"
  RC=$?
  assert "$(basename "$(dirname "$lint")") invalid range returns usage/data error" '[ "$RC" -eq 2 ]'
  printf 'KEEP-DEAD\n' > "$REF_ROOT/docs/.selftest-ref-dead.md"
  printf 'KEEP-FENCE\n' > "$REF_ROOT/docs/.selftest-ref-fence.md"
  HARNESS_PROJECT_ROOT="$REF_ROOT" python3 "$lint" --selftest > "$WORK/selftest.out"
  assert "$(basename "$(dirname "$lint")") selftest preserves pre-existing files" \
    'grep -qx KEEP-DEAD "$REF_ROOT/docs/.selftest-ref-dead.md" && grep -qx KEEP-FENCE "$REF_ROOT/docs/.selftest-ref-fence.md"'
done

# 5. Explicit Husky chaining must never follow a symlink outside the project.
HOOK_ROOT="$WORK/hooks"
git init -q "$HOOK_ROOT"
mkdir -p "$HOOK_ROOT/.husky"
printf '#!/usr/bin/env bash\necho external\n' > "$WORK/external-pre-commit"
EXTERNAL_BEFORE="$(sha256sum "$WORK/external-pre-commit" | awk '{print $1}')"
ln -s "$WORK/external-pre-commit" "$HOOK_ROOT/.husky/pre-commit"
bash "$REPO_ROOT/templates/.harness/lib/set_hooks_path.sh" "$HOOK_ROOT" --chain-existing \
  > "$WORK/hooks.out" 2> "$WORK/hooks.err"
HOOK_RC=$?
assert "Husky symlink chaining is rejected" '[ "$HOOK_RC" -eq 1 ]'
assert "Husky symlink target outside project is byte-untouched" \
  '[ "$(sha256sum "$WORK/external-pre-commit" | awk '\''{print $1}'\'')" = "$EXTERNAL_BEFORE" ]'
assert "unsafe Husky path is reported explicitly" 'grep -q "unsafe Husky pre-commit" "$WORK/hooks.err"'

# 6. The chain must execute before an early exit in the existing Husky hook.
CHAIN_ROOT="$WORK/hooks-early-exit"
git init -q "$CHAIN_ROOT"
mkdir -p "$CHAIN_ROOT/.husky" "$CHAIN_ROOT/.githooks"
printf '#!/usr/bin/env bash\nexit 0\n' > "$CHAIN_ROOT/.husky/pre-commit"
printf '#!/usr/bin/env bash\ntouch "$ORIONS_BELT_ROOT/.chain-ran"\n' > "$CHAIN_ROOT/.githooks/pre-commit"
chmod +x "$CHAIN_ROOT/.husky/pre-commit" "$CHAIN_ROOT/.githooks/pre-commit"
bash "$REPO_ROOT/templates/.harness/lib/set_hooks_path.sh" "$CHAIN_ROOT" --chain-existing \
  > "$WORK/hooks-chain.out" 2> "$WORK/hooks-chain.err"
(cd "$CHAIN_ROOT" && bash .husky/pre-commit)
assert "Husky chain runs before an existing early exit" '[ -f "$CHAIN_ROOT/.chain-ran" ]'
assert "Husky chain marker is idempotent" \
  '[ "$(grep -c "^# orions-belt:begin pre-commit$" "$CHAIN_ROOT/.husky/pre-commit")" -eq 1 ]'

echo
if [ "$FAIL" -eq 0 ]; then
echo "ALL CONTAINED RUNTIME SAFETY TESTS PASSED."
else
  echo "CONTAINED RUNTIME SAFETY REGRESSION REMAINS."
fi
exit "$FAIL"
