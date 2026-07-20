#!/usr/bin/env bash
# test_skill_runtime_parity.sh — regressão do gap SIMÉTRICO (auditoria
# adversarial H4, severidade ALTA): council + adversarial-review só
# existiam em `.agents/skills/`, SEM condicional de runtime nenhuma — um
# install `use_claude=true use_codex=false` NÃO tinha
# `{{ project_name }}-delivery-council` nem `adversarial-review` em
# `.claude/skills` (Claude Code não escaneia `.agents/skills`, mesmo
# achado do H3/A1 que motivou o mecanismo skills-shared para as outras 6
# skills). É o espelho exato do gap que H3 fechou para o Codex — aqui era
# o Claude-only que ficava sem o council e sem o revisor adversarial.
#
# Fix: as 2 skills migraram para o mesmo mecanismo skills-shared
# (.harness/skills-shared/{delivery-council,adversarial-review}/) com
# wrappers de 1 linha em .claude/skills/ (gated por use_claude) e
# .agents/skills/ (gated por use_codex).
#
# Também cobre o gap simétrico secundário do mesmo achado: harness_runs_dir
# tinha default ".claude/runs" incondicional — um projeto codex-only
# herdava um path Claude-flavored. Prova que HARNESS_RUNS_DIR resolve para
# o novo default neutro ".harness/runs" num render 100% codex-only.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"

FAIL=0
WORK="$(mktemp -d /tmp/skill-runtime-parity.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

assert() {
  if eval "$2"; then echo "PASS: $1"; else echo "FAIL: $1"; FAIL=1; fi
}

if ! command -v uvx >/dev/null 2>&1; then
  echo "SKIP: uvx indisponível — não é possível provar o fluxo real do copier" >&2
  exit 77
fi

PROJECT_NAME="skillparity"
COUNCIL_SKILL="${PROJECT_NAME}-delivery-council"

# =============================================================================
# 1. Render CLAUDE-ONLY real
# =============================================================================
CLAUDE_ONLY="$WORK/claude-only"
if ! uvx copier copy "$REPO_ROOT" "$CLAUDE_ONLY" --vcs-ref HEAD \
    --data project_name="$PROJECT_NAME" --data owner_name=Tester \
    --data use_claude=true --data use_codex=false \
    --defaults --trust -q > "$WORK/copy-claude.log" 2>&1; then
  echo "FAIL: copier copy --vcs-ref HEAD (claude-only) falhou -- $(tail -20 "$WORK/copy-claude.log")"
  exit 1
fi

assert "(gate simétrico) claude-only: .claude/skills/$COUNCIL_SKILL/SKILL.md existe" \
  '[ -f "$CLAUDE_ONLY/.claude/skills/$COUNCIL_SKILL/SKILL.md" ]'
assert "(gate simétrico) claude-only: .claude/skills/adversarial-review/SKILL.md existe" \
  '[ -f "$CLAUDE_ONLY/.claude/skills/adversarial-review/SKILL.md" ]'
assert "claude-only: .agents/skills NÃO tem o council nem adversarial-review (use_codex=false; .agents/skills em si pode existir vazio -- mesma assimetria pré-existente das outras 6 skills-shared, fora do escopo deste gap)" \
  '[ ! -e "$CLAUDE_ONLY/.agents/skills/$COUNCIL_SKILL" ] && [ ! -e "$CLAUDE_ONLY/.agents/skills/adversarial-review" ]'
assert "claude-only: CLAUDE.md cita a skill do council" \
  'grep -q "$COUNCIL_SKILL" "$CLAUDE_ONLY/.claude/CLAUDE.md"'

# =============================================================================
# 2. Render CODEX-ONLY real
# =============================================================================
CODEX_ONLY="$WORK/codex-only"
if ! uvx copier copy "$REPO_ROOT" "$CODEX_ONLY" --vcs-ref HEAD \
    --data project_name="$PROJECT_NAME" --data owner_name=Tester \
    --data use_claude=false --data use_codex=true \
    --defaults --trust -q > "$WORK/copy-codex.log" 2>&1; then
  echo "FAIL: copier copy --vcs-ref HEAD (codex-only) falhou -- $(tail -20 "$WORK/copy-codex.log")"
  exit 1
fi

assert "(gate simétrico) codex-only: .agents/skills/$COUNCIL_SKILL/SKILL.md existe" \
  '[ -f "$CODEX_ONLY/.agents/skills/$COUNCIL_SKILL/SKILL.md" ]'
assert "(gate simétrico) codex-only: .agents/skills/adversarial-review/SKILL.md existe" \
  '[ -f "$CODEX_ONLY/.agents/skills/adversarial-review/SKILL.md" ]'
assert "codex-only: .claude/ NÃO existe (use_claude=false)" \
  '[ ! -d "$CODEX_ONLY/.claude" ]'
assert "codex-only: companion openai.yaml do council existe (.agents/skills/$COUNCIL_SKILL/agents/openai.yaml)" \
  '[ -f "$CODEX_ONLY/.agents/skills/$COUNCIL_SKILL/agents/openai.yaml" ]'

# --- HARNESS_RUNS_DIR neutro (harness_runs_dir default) ---
assert "codex-only: HARNESS_RUNS_DIR resolve para .harness/runs (default neutro, não .claude/runs)" \
  'grep -q "^HARNESS_RUNS_DIR=.harness/runs$" "$CODEX_ONLY/.harness/harness.conf"'
# grep no CÓDIGO funcional (linha SLOTS=...), não em comentários que citam
# ".claude/runs" como nota histórica do bug já corrigido (mensagem legítima).
assert "codex-only: subagent-throttle.sh usa \$RUNS_DIR na linha SLOTS= (não hardcode)" \
  'grep -q "^SLOTS=\"\$ROOT/\$RUNS_DIR/.slots\"" "$CODEX_ONLY/.harness/hooks/subagent-throttle.sh"'
assert "codex-only: subagent-release.sh usa \$RUNS_DIR na linha SLOTS= (não hardcode)" \
  'grep -q "^SLOTS=\"\$ROOT/\$RUNS_DIR/.slots\"" "$CODEX_ONLY/.harness/hooks/subagent-release.sh"'
assert "codex-only: nenhuma linha de CÓDIGO (fora de comentário #) hardcoda .claude/runs" \
  '! grep -vE "^\s*#" "$CODEX_ONLY/.harness/hooks/subagent-throttle.sh" "$CODEX_ONLY/.harness/hooks/subagent-release.sh" | grep -q "\.claude/runs"'

# =============================================================================
# 3. Render com OS DOIS runtimes (default) -- conteúdo BYTE-IDÊNTICO entre
#    .claude/skills e .agents/skills, mesma fonte única
# =============================================================================
BOTH="$WORK/both"
if ! uvx copier copy "$REPO_ROOT" "$BOTH" --vcs-ref HEAD \
    --data project_name="$PROJECT_NAME" --data owner_name=Tester \
    --defaults --trust -q > "$WORK/copy-both.log" 2>&1; then
  echo "FAIL: copier copy --vcs-ref HEAD (both runtimes) falhou -- $(tail -20 "$WORK/copy-both.log")"
  exit 1
fi

for name in "$COUNCIL_SKILL" "adversarial-review"; do
  A="$BOTH/.claude/skills/$name/SKILL.md"
  B="$BOTH/.agents/skills/$name/SKILL.md"
  if [ -f "$A" ] && [ -f "$B" ]; then
    assert "'$name': .claude e .agents renderizam BYTE-IDÊNTICO (fonte única skills-shared)" \
      'diff -q "$A" "$B" >/dev/null'
  else
    echo "FAIL: '$name' ausente em algum runtime (.claude=$([ -f "$A" ] && echo ok || echo FALTA), .agents=$([ -f "$B" ] && echo ok || echo FALTA))"
    FAIL=1
  fi
done

# --- conteúdo real (não só arquivo vazio/stub) ---
assert "council renderizado tem os sentinels reais (não é stub vazio)" \
  'grep -q "PLAN-ADVERSARIAL-VERIFICATION: SATISFEITO | REPLANEJAR | SABATINAR | BLOQUEADO" "$BOTH/.claude/skills/$COUNCIL_SKILL/SKILL.md"'
assert "adversarial-review renderizado tem o protocolo real (não é stub vazio)" \
  'grep -q "ADVERSARIAL-VERIFICATION" "$BOTH/.claude/skills/adversarial-review/SKILL.md"'

# =============================================================================
# grep de termos do doador/outros projetos do dono = 0 (path-neutro obrigatório)
# =============================================================================
DONOR_HITS="$(grep -rlEi 'learnhouse|quero|makershub|agent-harness' "$WORK" 2>/dev/null | wc -l)"
assert "grep learnhouse|quero|makershub|agent-harness nos 3 renders = 0" '[ "$DONOR_HITS" -eq 0 ]'

echo
echo "=== resumo ==="
if [ "$FAIL" -eq 0 ]; then
  echo "GAP SIMÉTRICO (council+adversarial-review Claude-only) FECHADO."
else
  echo "AINDA HÁ GAP ABERTO — ver FAILs acima."
fi
exit $FAIL
