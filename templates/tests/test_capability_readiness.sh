#!/usr/bin/env bash
# Executable capabilities must be explicitly configured, never plausible seeds.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
WORK="$(mktemp -d /tmp/orions-capability-readiness.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT
FAIL=0

assert() { if eval "$2"; then echo "PASS: $1"; else echo "FAIL: $1"; FAIL=1; fi; }
command -v uvx >/dev/null 2>&1 || { echo "SKIP: uvx unavailable"; exit 77; }

render() {
  local dst="$1"; shift
  uvx copier copy "$REPO_ROOT" "$dst" --trust --defaults --vcs-ref HEAD \
    --data project_name=capability-test --data owner_name=Tester \
    --data use_claude=true --data use_codex=false "$@" >/dev/null 2>&1 || {
      echo "FAIL: render failed for $dst" >&2
      return 1
    }
}

render_codex() {
  local dst="$1"; shift
  uvx copier copy "$REPO_ROOT" "$dst" --trust --defaults --vcs-ref HEAD \
    --data project_name=capability-test --data owner_name=Tester \
    --data use_claude=false --data use_codex=true "$@" >/dev/null 2>&1 || {
      echo "FAIL: codex render failed for $dst" >&2
      return 1
    }
}

DEFAULT="$WORK/default"
render "$DEFAULT" || exit 1
assert "default render has no unconfigured run skill" '[ ! -d "$DEFAULT/.claude/skills/run-capability-test" ]'
assert "UI evidence is opt-in by default" '[ ! -e "$DEFAULT/scripts/ui-evidence.sh" ]'
assert "design-system gate is opt-in by default" '[ ! -e "$DEFAULT/.harness/hooks/ds-gate-posttool.sh" ]'
assert "icon guard is opt-in by default" '[ ! -e "$DEFAULT/.claude/hookify.icones-lucide.local.md" ]'
assert "UI skills are opt-in by default" '[ ! -d "$DEFAULT/.claude/skills/ui-component-playbook" ]'

PATH_SEED="$WORK/ui-path-seed"
render "$PATH_SEED" --data harness_web_app_dir=frontend || exit 1
assert "web app path persists even while UI capabilities are disabled" \
  'grep -Fq "harness_web_app_dir: frontend" "$PATH_SEED/.harness/answers.yml"'

RUN="$WORK/run-ready"
render "$RUN" --data harness_run_command=./dev.sh \
  --data 'harness_run_health_command=curl -fsS http://localhost:3000/' || exit 1
assert "explicit run command activates run skill" '[ -f "$RUN/.claude/skills/run-capability-test/SKILL.md" ]'
assert "run skill contains the configured command" 'grep -Fq "./dev.sh" "$RUN/.claude/skills/run-capability-test/SKILL.md"'
assert "run skill contains no guessed apps/api topology" '! grep -Fq "apps/api" "$RUN/.claude/skills/run-capability-test/SKILL.md"'

RUN_CODEX="$WORK/run-ready-codex"
render_codex "$RUN_CODEX" --data harness_run_command=./dev.sh \
  --data 'harness_run_health_command=curl -fsS http://localhost:3000/' || exit 1
assert "Codex-only render receives the configured run skill" \
  '[ -f "$RUN_CODEX/.agents/skills/run-capability-test/SKILL.md" ]'
assert "Codex run skill contains the exact configured command" \
  'grep -Fq "./dev.sh" "$RUN_CODEX/.agents/skills/run-capability-test/SKILL.md"'

RUN_BOTH="$WORK/run-ready-both"
uvx copier copy "$REPO_ROOT" "$RUN_BOTH" --trust --defaults --vcs-ref HEAD \
  --data project_name=capability-test --data owner_name=Tester \
  --data harness_run_command=./dev.sh >/dev/null 2>&1 || exit 1
assert "both-runtime run skills are byte-identical" \
  'diff -q "$RUN_BOTH/.claude/skills/run-capability-test/SKILL.md" "$RUN_BOTH/.agents/skills/run-capability-test/SKILL.md" >/dev/null'

PROD_COMMON=(
  --data has_prod_stack=true --data prod_stack_prefix=capability
  --data prod_registry_url=registry.example.test
  --data prod_public_web_url=https://example.test
)
EASY="$WORK/easypanel"
render "$EASY" "${PROD_COMMON[@]}" --data prod_deployment_driver=easypanel || exit 1
assert "EasyPanel selection does not generate Swarm deploy skill" \
  '[ ! -d "$EASY/.claude/skills/deploy-capability" ]'
assert "EasyPanel selection does not generate Swarm mutation guards" \
  '! find "$EASY/.claude" -type f -name "hookify.capability-prod-*" -print -quit | grep -q .'

SWARM="$WORK/swarm"
render "$SWARM" "${PROD_COMMON[@]}" --data prod_deployment_driver=swarm-direct || exit 1
assert "explicit swarm-direct selection generates deploy skill" \
  '[ -f "$SWARM/.claude/skills/deploy-capability/SKILL.md" ]'
assert "explicit swarm-direct selection generates its guards" \
  'find "$SWARM/.claude" -type f -name "hookify.capability-prod-*" -print -quit | grep -q .'

SWARM_CODEX="$WORK/swarm-codex"
render_codex "$SWARM_CODEX" "${PROD_COMMON[@]}" --data prod_deployment_driver=swarm-direct || exit 1
assert "Codex-only swarm selection generates deploy skill" \
  '[ -f "$SWARM_CODEX/.agents/skills/deploy-capability/SKILL.md" ]'

echo
if [ "$FAIL" -eq 0 ]; then
  echo "ALL CAPABILITY READINESS GATES PASSED."
else
  echo "CAPABILITY READINESS REGRESSION REMAINS."
fi
exit "$FAIL"
