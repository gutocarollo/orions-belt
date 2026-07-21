#!/usr/bin/env bash
# test_copier_update_no_op.sh — regression for M1 (H4 adversarial audit):
# `copier update` on the SAME version/tag (zero template change) must be
# a real NO-OP on `.harness/answers.yml`, not only on rendered files.
#
# Real bug found and fixed in this round: `harness_codex_max_threads`,
# `harness_codex_max_depth`, `harness_codex_project_doc_max_bytes`,
# `harness_codex_agents_dir`, `harness_codex_config_path` and
# `harness_mcp_db_prod_port` had a `when` referencing `use_codex`/
# `has_prod_stack`, but those two variables were declared FURTHER DOWN in
# copier.yml. Copier resolves `when` in the questionnaire's DECLARATION ORDER
# (confirmed via Context7 /copier-org/copier docs/configuring.md — "the
# question is skipped and its answer is not recorded" when `when` is
# false): on the 1st `copier copy`, the referenced variable does not yet exist in
# the namespace (undefined = falsy) when the dependent question is evaluated, the
# question is skipped and the answer is not recorded in answers.yml. On the next
# `copier update`, answers.yml already loads the variable from the start, the
# `when` now evaluates true, and the key "appears" as a diff even without
# any real version/template change — an update that should have been a
# no-op was not. Fix: `use_claude`/`use_codex` moved to right after the
# identity section; `harness_mcp_db_prod_port` moved inside the
# `prod_*` block (after `has_prod_stack`).
#
# Uses the current HEAD SHA (not an old tag) on purpose — it needs to
# exercise the CURRENT copier.yml of this working tree, not a historical
# checkpoint. Requires a prior commit of the changes under evaluation (the target is
# the commit, not the dirty working tree).
#
# NEW GOTCHA discovered in this round (also documented in
# docs/manual/14-instalacao-e-update.md): `--vcs-ref HEAD` (the literal
# STRING "HEAD") works for `copier copy`, but BREAKS on `copier
# update` -- Copier writes `_commit` in answers.yml as a composite
# `git describe` (e.g. "v1.0.0-12-g346ea08"), and when running `update` again with
# `--vcs-ref HEAD`, it tries to `git checkout -f` that composite text
# as if it were a valid ref -- it is not (describe != revspec), and the
# update dies with "pathspec did not match any file(s)". Using the RESOLVED
# SHA (`git rev-parse HEAD`) instead of the string "HEAD" avoids the bug
# (reproduced and confirmed in this session, 2 isolated repros) -- it is the same
# commit, it just does not go through the textual "HEAD" resolution that triggers the
# broken path. This test uses the SHA for both the `copy` AND `update` calls.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
HEAD_SHA="$(git -C "$REPO_ROOT" rev-parse HEAD)"

FAIL=0
WORK="$(mktemp -d /tmp/copier-update-noop.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

assert() {
  if eval "$2"; then echo "PASS: $1"; else echo "FAIL: $1"; FAIL=1; fi
}

if ! command -v uvx >/dev/null 2>&1; then
  echo "SKIP: uvx unavailable — cannot prove the real copier update mechanism" >&2
  exit 77
fi

FIXTURE="$WORK/fixture"
mkdir -p "$FIXTURE"
cd "$FIXTURE"
git init -q
git config user.email "test@example.com"
git config user.name "Test"

# --- 1. copy pinned to HEAD (use_codex=true default -- the case that exposes the bug) ---
if ! timeout 90 uvx copier copy --trust --defaults \
    -d project_name=noopupdate -d owner_name=T --vcs-ref "$HEAD_SHA" \
    "$REPO_ROOT" . > "$WORK/copy.log" 2>&1; then
  echo "FAIL: copier copy --vcs-ref $HEAD_SHA failed -- $(tail -20 "$WORK/copy.log")"
  exit 1
fi
git add -A
if ! git commit -qm "bootstrap HEAD" >/dev/null 2>"$WORK/bootstrap-commit.err"; then
  echo "FAIL: bootstrap commit failed (pre-commit must pass on a fresh render) -- $(tail -5 "$WORK/bootstrap-commit.err")"
  exit 1
fi

assert "answers.yml exists" '[ -f .harness/answers.yml ]'
assert "answers.yml ALREADY carries harness_codex_max_threads on the 1st copy (the use_codex variable precedes the question)" \
  'grep -q "^harness_codex_max_threads:" .harness/answers.yml'
assert "answers.yml ALREADY carries harness_codex_agents_dir on the 1st copy" \
  'grep -q "^harness_codex_agents_dir:" .harness/answers.yml'
assert "answers.yml carries harness_mcp_db_prod_port only when has_prod_stack -- default false, missing key is expected" \
  '! grep -q "^harness_mcp_db_prod_port:" .harness/answers.yml'

cp .harness/answers.yml "$WORK/answers-before.yml"

# --- 2. update on the SAME ref (HEAD) -- zero template change, must be a no-op ---
if ! timeout 90 uvx copier update --trust --defaults --vcs-ref "$HEAD_SHA" \
    --answers-file .harness/answers.yml > "$WORK/update.log" 2>&1; then
  echo "FAIL: copier update --vcs-ref $HEAD_SHA (same ref) failed -- $(tail -20 "$WORK/update.log")"
  FAIL=1
fi

assert "update on the SAME ref is a real NO-OP on answers.yml (empty diff)" \
  'diff -q "$WORK/answers-before.yml" .harness/answers.yml >/dev/null'
assert "update on the SAME ref does not dirty the working tree (git status --short empty, except trailing newline)" \
  '[ -z "$(git status --short)" ]'

# --- 3. with explicit has_prod_stack=true, harness_mcp_db_prod_port must
#     appear ALREADY on the 1st copy (not only after an update) ---
FIXTURE2="$WORK/fixture-prod"
mkdir -p "$FIXTURE2"
cd "$FIXTURE2"
git init -q
git config user.email "test@example.com"
git config user.name "Test"
if ! timeout 90 uvx copier copy --trust --defaults \
    -d project_name=noopupdateprod -d owner_name=T -d has_prod_stack=true \
    -d prod_stack_prefix=noop -d prod_registry_url=registry.local \
    -d prod_public_web_url=https://noop.local --vcs-ref "$HEAD_SHA" \
    "$REPO_ROOT" . > "$WORK/copy-prod.log" 2>&1; then
  echo "FAIL: copier copy --vcs-ref $HEAD_SHA (has_prod_stack=true) failed -- $(tail -20 "$WORK/copy-prod.log")"
  FAIL=1
else
  assert "with has_prod_stack=true, harness_mcp_db_prod_port ALREADY appears on the 1st copy" \
    'grep -q "^harness_mcp_db_prod_port:" .harness/answers.yml'
fi

echo
echo "=== summary ==="
if [ "$FAIL" -eq 0 ]; then
  echo "M1 (non-idempotent no-op) FIXED — copier update on the same ref does not change answers.yml."
else
  echo "THERE IS STILL AN OPEN GAP — see FAILs above."
fi
exit $FAIL
