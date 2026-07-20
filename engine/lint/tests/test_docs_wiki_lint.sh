#!/usr/bin/env bash
# test_docs_wiki_lint.sh — F1 proof (Part A): runs engine/lint/docs_wiki_lint.py
# in 3 scenarios and confirms the expected exit code in each one.
#
# 1. Real smoke: against the agent-harness's OWN docs/ (HARNESS_PROJECT_ROOT
#    default = real git root) — must be OK (docs/log.md covers planning/*).
# 2. Clean fixture (clean-docs/): individual citation + collection — must be OK.
# 3. Broken fixture (broken-docs/): orphan.md deliberately unmentioned —
#    must FAIL and cite exactly that file.
#
# Usage: bash engine/lint/tests/test_docs_wiki_lint.sh
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LINT_DIR="$(cd "$HERE/.." && pwd)"
ENGINE_DIR="$(cd "$LINT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$ENGINE_DIR/.." && pwd)"
LINT="$LINT_DIR/docs_wiki_lint.py"
FAIL=0

assert_exit() {
  # $1 = description, $2 = obtained exit, $3 = expected exit
  if [ "$2" -eq "$3" ]; then
    echo "PASS: $1 (exit=$2)"
  else
    echo "FAIL: $1 (expected exit=$3, got exit=$2)"
    FAIL=1
  fi
}

echo "=== Scenario 1: real smoke test against orions-belt's own docs/ ==="
HARNESS_PROJECT_ROOT="$REPO_ROOT" python3 "$LINT" >/tmp/lint-out-$$ 2>&1
rc=$?
assert_exit "orions-belt real docs/ must pass (docs/log.md covers planning/)" "$rc" 0
cat /tmp/lint-out-$$

echo
echo "=== Scenario 2: clean fixture (clean-docs/) ==="
HARNESS_PROJECT_ROOT="$HERE/fixtures/clean-docs" python3 "$LINT" >/tmp/lint-out-$$ 2>&1
rc=$?
assert_exit "clean-docs must pass (a.md cited, collection/ covered)" "$rc" 0

echo
echo "=== Scenario 3: broken fixture (broken-docs/) — intentional orphan.md ==="
HARNESS_PROJECT_ROOT="$HERE/fixtures/broken-docs" python3 "$LINT" >/tmp/lint-out-$$ 2>&1
rc=$?
assert_exit "broken-docs must FAIL (orphan.md unmentioned)" "$rc" 1
if grep -q "orphan.md" /tmp/lint-out-$$; then
  echo "PASS: output cites orphan.md as an orphan"
else
  echo "FAIL: output does not cite orphan.md — $(cat /tmp/lint-out-$$)"
  FAIL=1
fi

echo
echo "=== Scenario 4: repo-wide stray sweep (WARN inbox, never a failure) ==="
STRAYFX="$(mktemp -d /tmp/lint-stray.XXXXXX)"
mkdir -p "$STRAYFX/docs" "$STRAYFX/backend" "$STRAYFX/node_modules/pkg"
printf '# log\n\n## [2026-07-20] chore · docs — seed\n' > "$STRAYFX/docs/log.md"
echo "# readme" > "$STRAYFX/README.md"              # allowed at root
echo "# lost plan" > "$STRAYFX/PLANO-FINAL-v2.md"   # stray at root
echo "# notes" > "$STRAYFX/backend/notes.md"        # stray in a subdir
echo "# dep" > "$STRAYFX/node_modules/pkg/README.md"  # must be skipped
HARNESS_PROJECT_ROOT="$STRAYFX" python3 "$LINT" >/tmp/lint-out-$$ 2>&1
rc=$?
assert_exit "strays are WARN-only (exit stays 0)" "$rc" 0
if grep -q "PLANO-FINAL-v2.md" /tmp/lint-out-$$ && grep -q "backend/notes.md" /tmp/lint-out-$$; then
  echo "PASS: both strays (root + subdir) surface as curator inbox"
else
  echo "FAIL: stray sweep missed a scattered doc — $(cat /tmp/lint-out-$$)"
  FAIL=1
fi
if grep -q "node_modules" /tmp/lint-out-$$ || grep -qE '~ .*README\.md' /tmp/lint-out-$$; then
  echo "FAIL: sweep flagged an allowed/skipped path"
  FAIL=1
else
  echo "PASS: README.md (root) and node_modules/ are not flagged"
fi
rm -rf "$STRAYFX"

rm -f /tmp/lint-out-$$

echo
if [ "$FAIL" -eq 0 ]; then
  echo "RESULT: ALL SCENARIOS PASSED"
  exit 0
else
  echo "RESULT: THERE ARE FAILURES — see FAIL lines above"
  exit 1
fi
