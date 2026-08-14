#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d /tmp/council-rendered-runtime.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

command -v uvx >/dev/null 2>&1 || {
  echo "uvx is required to validate the rendered Council" >&2
  exit 1
}

uvx copier copy "$REPO_ROOT" "$WORK/project" --vcs-ref HEAD \
  --data project_name=councilproof \
  --data owner_name=Tester \
  --data use_claude=true \
  --data use_codex=true \
  --data use_gauntlet_loop=false \
  --data use_delivery_council=true \
  --data use_context_graph=true \
  --data harness_core_paths=src/core/ \
  --data use_exploration_protocol=true \
  --data use_context_delivery=true \
  --data harness_context_provider=codegraph \
  --data harness_language=en \
  --defaults --trust -q

cd "$WORK/project"
git init -q
git config user.email test@example.invalid
git config user.name Test
git add -A
git commit -q -m baseline

grep -q "Opt-in activation" AGENTS.md
grep -q "HARNESS_PLAN_REVIEW_MAX=1" .harness/harness.conf
grep -q "HARNESS_EXECUTION_REVIEW_MAX=1" .harness/harness.conf
grep -q "REVIEW_MODE=SINGLE" .agents/skills/councilproof-delivery-council/SKILL.md
grep -q "REVIEW_MODE=FULL.*only" .agents/skills/councilproof-delivery-council/SKILL.md
test ! -e .harness/council-active
printf '{}\n' | python3 .harness/hooks/council-gate.py pre

PROMPT="$(python3 "$REPO_ROOT/engine/contract/scripts/render_prompt.py" --task 'small fix')"
grep -q "PLAN_REVIEW_MAX=1" <<<"$PROMPT"
grep -q "EXECUTION_REVIEW_MAX=1" <<<"$PROMPT"
grep -q "REVIEW_MODE=SINGLE" <<<"$PROMPT"

python3 .harness/lib/tests/test_objective_control.py
python3 .harness/lib/tests/test_context_delivery.py
python3 .harness/lib/tests/test_council_runtime.py
python3 .harness/lib/tests/test_council_pipeline.py
python3 .harness/lib/tests/test_council_contract.py
python3 .harness/lib/tests/test_council_evaluation.py
