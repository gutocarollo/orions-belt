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
  --data use_context_graph=true \
  --data harness_core_paths=src/core/ \
  --data use_exploration_protocol=true \
  --data harness_language=en \
  --defaults --trust -q

cd "$WORK/project"
git init -q
git config user.email test@example.invalid
git config user.name Test
git add -A
git commit -q -m baseline
python3 .harness/lib/tests/test_objective_control.py
python3 .harness/lib/tests/test_context_delivery.py
python3 .harness/lib/tests/test_council_runtime.py
python3 .harness/lib/tests/test_council_pipeline.py
python3 .harness/lib/tests/test_council_contract.py
python3 .harness/lib/tests/test_council_evaluation.py
