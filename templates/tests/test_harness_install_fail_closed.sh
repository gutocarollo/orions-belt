#!/usr/bin/env bash
# End-to-end safety regressions for the real render -> plan -> apply pipeline.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
INSTALLER="$REPO_ROOT/harness-install.sh"
EXPECTED_SOURCE="$(git -C "$REPO_ROOT" config --get remote.origin.url 2>/dev/null || basename "$REPO_ROOT")"
WORK="$(mktemp -d /tmp/harness-install-fail-closed.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT
FAIL=0

assert() {
  if eval "$2"; then echo "PASS: $1"; else echo "FAIL: $1"; FAIL=1; fi
}

if ! command -v uvx >/dev/null 2>&1; then
  echo "SKIP: uvx unavailable"
  exit 77
fi

COMMON=(--vcs-ref HEAD --data owner_name=Tester --defaults)

# 1. A symlinked parent must fail before creating anything through it.
TARGET1="$WORK/symlink-parent"
EXTERNAL1="$WORK/external-codex"
mkdir -p "$TARGET1" "$EXTERNAL1"
ln -s "$EXTERNAL1" "$TARGET1/.codex"
set +e
"$INSTALLER" "$TARGET1" "${COMMON[@]}" --data project_name=symlink-parent \
  --data use_claude=false --data use_codex=true >"$WORK/symlink-parent.log" 2>&1
RC1=$?
set -e
assert "symlinked parent aborts non-zero" '[ "$RC1" -ne 0 ]'
assert "symlinked parent remains a symlink" '[ -L "$TARGET1/.codex" ]'
assert "external directory is byte-empty (no mkdir side effect)" '[ -z "$(find "$EXTERNAL1" -mindepth 1 -print -quit)" ]'
assert "failed plan wrote no ownership manifest" '[ ! -e "$TARGET1/.harness/install-manifest.json" ]'

# 2. A symlinked shared file must be preserved, not materialized/replaced.
TARGET2="$WORK/symlink-file"
mkdir -p "$TARGET2"
printf 'central instructions\n' > "$WORK/central-agents.md"
ln -s "$WORK/central-agents.md" "$TARGET2/AGENTS.md"
set +e
"$INSTALLER" "$TARGET2" "${COMMON[@]}" --data project_name=symlink-file \
  --data use_claude=false --data use_codex=true >"$WORK/symlink-file.log" 2>&1
RC2=$?
set -e
assert "symlinked destination aborts non-zero" '[ "$RC2" -ne 0 ]'
assert "AGENTS symlink is preserved" '[ -L "$TARGET2/AGENTS.md" ]'
assert "external instruction content is preserved" 'grep -qx "central instructions" "$WORK/central-agents.md"'

# 3. An unknown whole-file collision aborts the entire plan before other files land.
TARGET3="$WORK/unowned-collision"
mkdir -p "$TARGET3"
printf 'user notice\n' > "$TARGET3/NOTICE"
set +e
"$INSTALLER" "$TARGET3" "${COMMON[@]}" --data project_name=unowned-collision \
  --data use_claude=true --data use_codex=false >"$WORK/collision.log" 2>&1
RC3=$?
set -e
assert "unowned collision aborts non-zero" '[ "$RC3" -ne 0 ]'
assert "unowned colliding file stays intact" 'grep -qx "user notice" "$TARGET3/NOTICE"'
assert "no partial AGENTS/CLAUDE install occurred" '[ ! -e "$TARGET3/.claude/CLAUDE.md" ]'

# 4. A successful install must materialize the real target root, never scratch.
TARGET4="$WORK/project-root"
"$INSTALLER" "$TARGET4" "${COMMON[@]}" --data project_name=project-root \
  --data use_claude=false --data use_codex=true --data harness_dev_web_port=4321 \
  >"$WORK/project-root.log" 2>&1
TARGET4_REAL="$(cd "$TARGET4" && pwd -P)"
assert "successful install writes ownership manifest" '[ -f "$TARGET4/.harness/install-manifest.json" ]'
assert "harness.conf PROJECT_ROOT is the canonical target" \
  'grep -Fqx "PROJECT_ROOT=$TARGET4_REAL" "$TARGET4/.harness/harness.conf"'
assert "first install records a non-default answer" \
  'grep -Fqx "HARNESS_DEV_WEB_PORT=4321" "$TARGET4/.harness/harness.conf"'
assert "rendered target contains no deleted scratch path" \
  '! grep -Rqs "/tmp/harness-install\." "$TARGET4/AGENTS.md" "$TARGET4/.harness" "$TARGET4/.codex"'

# The answers file must not inherit Copier's per-render dirty pseudo-commit;
# otherwise every same-input reinstall rewrites it forever.
PLAN4="$WORK/project-root-reinstall.json"
"$INSTALLER" "$TARGET4" --dry-run --plan-json "$PLAN4" "${COMMON[@]}" \
  --data project_name=project-root --data use_claude=false --data use_codex=true \
  >"$WORK/project-root-reinstall.log" 2>&1
assert "same-input reinstall is a byte no-op" \
  'python3 -c '\''import json,sys; p=json.load(open(sys.argv[1])); raise SystemExit(0 if p.get("counts") == {"unchanged": len(p.get("files", []))} else 1)'\'' "$PLAN4"'
assert "reinstall reuses omitted managed answers instead of resetting defaults" \
  'grep -Fqx "HARNESS_DEV_WEB_PORT=4321" "$TARGET4/.harness/harness.conf"'
assert "answers metadata uses stable installer provenance" \
  'grep -Fqx "_src_path: '\''$EXPECTED_SOURCE'\''" "$TARGET4/.harness/answers.yml"'

# 5. Dry-run emits a plan but leaves an existing empty target empty.
TARGET5="$WORK/dry-run"
PLAN5="$WORK/dry-run-plan.json"
mkdir -p "$TARGET5"
"$INSTALLER" "$TARGET5" --dry-run --plan-json "$PLAN5" "${COMMON[@]}" \
  --data project_name=dry-run --data use_claude=false --data use_codex=true \
  >"$WORK/dry-run.log" 2>&1
assert "dry-run plan is valid JSON" 'python3 -m json.tool "$PLAN5" >/dev/null'
assert "dry-run leaves target empty" '[ -z "$(find "$TARGET5" -mindepth 1 -print -quit)" ]'

# 6. Dry-run must not create a missing target directory.
TARGET6="$WORK/dry-run-missing"
set +e
"$INSTALLER" "$TARGET6" --dry-run "${COMMON[@]}" \
  --data project_name=dry-run-missing --data use_claude=false --data use_codex=true \
  >"$WORK/dry-run-missing.log" 2>&1
RC6=$?
set -e
assert "dry-run against missing target fails non-zero" '[ "$RC6" -ne 0 ]'
assert "dry-run does not create missing target" '[ ! -e "$TARGET6" ]'

echo
if [ "$FAIL" -eq 0 ]; then
  echo "RESULT: ALL FAIL-CLOSED INSTALL GATES PASSED"
else
  echo "RESULT: FAILURES DETECTED"
fi
exit "$FAIL"
