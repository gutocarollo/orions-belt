#!/usr/bin/env bash
# test_copier_update_e2e.sh — end-to-end proof of Copier's NATIVE 3-way
# merge (F8, gate of docs/planning/00-plano-consolidado.md §6-F8).
#
# Unlike test_harness_init_e2e.sh (F5, which tests merge_docs.py — the
# harness's OWN merge only for the 3 sensitive files): this test
# exercises a real `copier update`, proving (a) a new upstream change
# reaches the rendered file, (b) a local customization survives untouched
# when there is no real conflict, (c) a real conflict generates markers
# `<<<<<<< before updating` / `=======` / `>>>>>>> after updating` instead of
# silently discarding one of the two sides.
#
# Builds three deterministic versions in an isolated local clone of the current
# template. This keeps the proof self-contained instead of depending on historic
# tags that may not exist in a shallow/new clone. The source worktree is never
# mutated; all fixture commits/tags live under the temporary directory.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"

FAIL=0
WORK="$(mktemp -d /tmp/copier-update-e2e.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT
FIXTURE="$WORK/fixture"
SOURCE="$WORK/source"

assert() {
  if eval "$2"; then echo "PASS: $1"; else echo "FAIL: $1"; FAIL=1; fi
}

replace_literal() {
  python3 - "$1" "$2" "$3" <<'PY'
from pathlib import Path
import sys

path, old, new = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
content = path.read_text(encoding="utf-8")
if content.count(old) != 1:
    raise SystemExit(f"fixture replacement expected one match in {path}, found {content.count(old)}")
path.write_text(content.replace(old, new), encoding="utf-8")
PY
}

if ! command -v uvx >/dev/null 2>&1; then
  echo "SKIP: uvx unavailable — cannot prove the real copier update mechanism"
  exit 77  # SKIP convention (README.md #H4): not a PASS
fi

git clone -q --no-hardlinks "$REPO_ROOT" "$SOURCE"
git -C "$SOURCE" config user.email "test@example.com"
git -C "$SOURCE" config user.name "Test"

# v98.0.0: baseline without the later upstream comment on the port line.
replace_literal "$SOURCE/templates/.harness/harness.conf.jinja" \
  'HARNESS_DEV_API_PORT={{ harness_dev_api_port }}  # porta padrão do backend/API em dev' \
  'HARNESS_DEV_API_PORT={{ harness_dev_api_port }}'
git -C "$SOURCE" add templates/.harness/harness.conf.jinja
git -C "$SOURCE" commit -qm "fixture: copier baseline"
git -C "$SOURCE" tag v98.0.0

# v98.1.0: orthogonal upstream change in a different rendered file.
printf '\n# copier-update-e2e fixture v98.1.0\n' >> "$SOURCE/templates/.harness/hooks/reap-leaks.sh"
git -C "$SOURCE" add templates/.harness/hooks/reap-leaks.sh
git -C "$SOURCE" commit -qm "fixture: orthogonal update"
git -C "$SOURCE" tag v98.1.0

# v98.2.0: upstream change on the same line customized by the target.
replace_literal "$SOURCE/templates/.harness/harness.conf.jinja" \
  'HARNESS_DEV_API_PORT={{ harness_dev_api_port }}' \
  'HARNESS_DEV_API_PORT={{ harness_dev_api_port }}  # copier-e2e upstream v98.2.0'
git -C "$SOURCE" add templates/.harness/harness.conf.jinja
git -C "$SOURCE" commit -qm "fixture: conflicting update"
git -C "$SOURCE" tag v98.2.0

mkdir -p "$FIXTURE"

cd "$FIXTURE"
git init -q
git config user.email "test@example.com"
git config user.name "Test"

# --- 1. copy pinned to v98.0.0 ---
if ! timeout 90 uvx copier copy --trust --defaults \
    -d project_name=e2eupdate -d owner_name=T --vcs-ref v98.0.0 \
    "$SOURCE" . > "$WORK/copy.log" 2>&1; then
  echo "FAIL: copier copy v98.0.0 failed -- $(tail -10 "$WORK/copy.log")"
  exit 1
fi
git add -A && git commit -qm "bootstrap v98.0.0" >/dev/null
assert "answers.yml exists and points to v98.0.0" \
  'grep -q "_commit: v98.0.0" .harness/answers.yml'

# --- 2. real local customization: CLAUDE.md line + harness.conf port ---
cat >> .claude/CLAUDE.md <<'EOF'

## Regra específica deste projeto (customização local do usuário)

- Nunca usar a porta 8000 em produção, este time reservou 9100 para a API.
EOF
replace_literal .harness/harness.conf \
  'HARNESS_DEV_API_PORT=8000' 'HARNESS_DEV_API_PORT=9100'
grep -q "HARNESS_DEV_API_PORT=9100" .harness/harness.conf || {
  echo "FAIL: setup — could not customize HARNESS_DEV_API_PORT (did the template format change?)"
  exit 1
}
git add -A && git commit -qm "customizacao local" >/dev/null

# --- 3. update to v98.1.0 (ORTHOGONAL change — reap-leaks.sh) ---
# an explicit --vcs-ref is MANDATORY here: real finding (F8) — `copier update`
# without --vcs-ref jumps straight to the MOST RECENT tag (v0.3.0), it does not
# increment 1-by-1; without the pin, this intermediate step would never really exist.
if ! timeout 90 uvx copier update --trust --defaults --vcs-ref v98.1.0 \
    --answers-file .harness/answers.yml > "$WORK/update1.log" 2>&1; then
  echo "FAIL: copier update v98.1.0 failed -- $(tail -15 "$WORK/update1.log")"
  FAIL=1
fi
assert "update1: reached version v98.1.0" 'grep -q "_commit: v98.1.0" .harness/answers.yml'
assert "update1: upstream change (reap-leaks.sh) arrived" \
  'grep -q "copier-update-e2e fixture v98.1.0" .harness/hooks/reap-leaks.sh'
assert "update1: CLAUDE.md customization survived untouched" \
  'grep -q "reservou 9100 para a API" .claude/CLAUDE.md'
assert "update1: harness.conf customization survived untouched" \
  'grep -q "HARNESS_DEV_API_PORT=9100" .harness/harness.conf'
assert "update1: NO conflict marker (clean merge, no real collision)" \
  '! grep -q "<<<<<<< before updating" .harness/harness.conf'
git add -A && git commit -qm "update to v98.1.0" >/dev/null

# --- 4. update to v98.2.0 (change that CONFLICTS with the customization) ---
timeout 90 uvx copier update --trust --defaults --vcs-ref v98.2.0 \
  --answers-file .harness/answers.yml > "$WORK/update2.log" 2>&1
assert "update2: reached version v98.2.0" 'grep -q "_commit: v98.2.0" .harness/answers.yml'
assert "update2: real CONFLICT generates markers (does not discard silently)" \
  'grep -q "<<<<<<< before updating" .harness/harness.conf'
assert "update2: the 'mine' side preserves the local value (9100)" \
  'sed -n "/<<<<<<< before updating/,/=======/p" .harness/harness.conf | grep -q "9100"'
assert "update2: the 'theirs' side brings the upstream change (new comment)" \
  'sed -n "/=======/,/>>>>>>> after updating/p" .harness/harness.conf | grep -q "copier-e2e upstream v98.2.0"'
assert "update2: git marks the file as unmerged (UU)" \
  'git status --short .harness/harness.conf | grep -q "^UU"'
assert "update2: CLAUDE.md (outside the conflicted file) stays untouched" \
  'grep -q "reservou 9100 para a API" .claude/CLAUDE.md'

echo
if [ "$FAIL" -eq 0 ]; then
  echo "RESULT: ALL SCENARIOS PASSED (copier update e2e — native 3-way merge)"
else
  echo "RESULT: FAILURES DETECTED"
fi
exit "$FAIL"
