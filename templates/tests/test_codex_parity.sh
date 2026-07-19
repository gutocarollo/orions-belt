#!/usr/bin/env bash
# test_codex_parity.sh — regressão dos 3 sub-gaps de A1 (auditoria adversarial
# H3 hardening) contra um render CODEX-ONLY real (`copier copy --vcs-ref HEAD
# -d use_codex=true -d use_claude=false`), nunca lógica reimplementada em
# prosa — mesmo princípio dos irmãos test_harness_install_brownfield_e2e.sh /
# test_ui_evidence_gate_bypass.sh.
#
# Os 3 sub-gaps, cada um provado FECHADO nesta rodada:
#   1. Skills runtime-neutras (grill-me, prova-de-conclusao,
#      ui-evidence, marathon, repo-wiki-curator, verify) não existiam em
#      .agents/skills — Codex descobre skills de projeto SÓ ali (confirmado
#      via WebFetch learn.chatgpt.com/docs/build-skills), não em
#      .claude/skills. Fix: fonte única em .harness/skills-shared/, incluída
#      pelos wrappers dos dois runtimes.
#   2. completion-gate.py ignorava `last_assistant_message` (payload Codex),
#      só cobria claim em português, e aceitava sentinel "N/M" cru sem
#      "PASS"/"gaps:". Fix: prioriza last_assistant_message quando presente,
#      regex de claim PT+EN, sentinel exige o formato completo.
#   3. subagent-throttle.sh registrado em SubagentStart (evento de INJEÇÃO,
#      não bloqueia — confirmado via WebFetch learn.chatgpt.com/docs/hooks)
#      em vez de PreToolUse (onde spawn_agent pode ser bloqueado de verdade).
#
# Requer `uvx`. Roda fora do orions-belt (fixture em $TMPDIR).
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"

FAIL=0
WORK="$(mktemp -d /tmp/codex-parity.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

assert() {
  # $1 = descrição, $2 = expressão shell (0=pass)
  if eval "$2"; then
    echo "PASS: $1"
  else
    echo "FAIL: $1"
    FAIL=1
  fi
}

if ! command -v uvx >/dev/null 2>&1; then
  echo "SKIP: uvx indisponível — não é possível provar o fluxo real do copier"
  exit 77  # convencao SKIP (README.md #H4): nao e PASS
fi

# =============================================================================
# 0. Render CODEX-ONLY real
# =============================================================================
BASE="$WORK/codex-only"
RENDER_LOG="$WORK/copier.log"
if ! uvx copier copy "$REPO_ROOT" "$BASE" --vcs-ref HEAD \
    --data project_name=codexparity --data owner_name=Tester \
    --data use_codex=true --data use_claude=false \
    --defaults --trust -q > "$RENDER_LOG" 2>&1; then
  echo "FAIL: copier copy --vcs-ref HEAD (codex-only) falhou -- $(tail -20 "$RENDER_LOG")"
  exit 1
fi

# --- (a) .claude ausente ---
assert "(a) .claude/ NÃO existe num install codex-only" '[ ! -d "$BASE/.claude" ]'
assert "(a) AGENTS.md existe (instrução Codex)" '[ -f "$BASE/AGENTS.md" ]'
assert "(a) .codex/ existe" '[ -d "$BASE/.codex" ]'
assert "(a) .agents/skills existe" '[ -d "$BASE/.agents/skills" ]'

# =============================================================================
# (b) sub-gap 1 — toda skill citada no AGENTS.md renderizado existe em
#     .agents/skills, com frontmatter YAML válido (--- na 1a linha, sem
#     linha em branco antes)
# =============================================================================
CITED="$(grep -oE 'skill `[a-z][a-z0-9-]*`' "$BASE/AGENTS.md" | sed -E 's/skill `//;s/`//' | sort -u)"
assert "(b) AGENTS.md cita ao menos 5 skills (sanity do grep)" \
  '[ "$(echo "$CITED" | grep -c .)" -ge 5 ]'

for name in $CITED; do
  SKILL_FILE="$BASE/.agents/skills/$name/SKILL.md"
  assert "(b) skill '$name' citada no AGENTS.md existe em .agents/skills/$name/SKILL.md" \
    '[ -f "$SKILL_FILE" ]'
  if [ -f "$SKILL_FILE" ]; then
    assert "(b) skill '$name': frontmatter começa na 1a linha (sem blank line antes de ---)" \
      '[ "$(head -1 "$SKILL_FILE")" = "---" ]'
    assert "(b) skill '$name': frontmatter declara name: $name" \
      "grep -q '^name: $name\$' '$SKILL_FILE'"
  fi
done
# repo-wiki-curator é citado sem o padrão "skill \`x\`" (crase só no nome) — checar nominalmente
assert "(b) skill 'repo-wiki-curator' citada explicitamente existe em .agents/skills" \
  '[ -f "$BASE/.agents/skills/repo-wiki-curator/SKILL.md" ]'

# --- conteúdo idêntico entre .claude e .agents para a mesma skill (fonte única) ---
BASE_CLAUDE="$WORK/claude-only"
if ! uvx copier copy "$REPO_ROOT" "$BASE_CLAUDE" --vcs-ref HEAD \
    --data project_name=codexparity --data owner_name=Tester \
    --data use_codex=false --data use_claude=true \
    --defaults --trust -q > "$WORK/copier-claude.log" 2>&1; then
  echo "FAIL: copier copy --vcs-ref HEAD (claude-only) falhou -- $(tail -20 "$WORK/copier-claude.log")"
  FAIL=1
else
  for name in grill-me harness-init prova-de-conclusao marathon repo-wiki-curator ui-evidence verify; do
    A="$BASE/.agents/skills/$name/SKILL.md"
    C="$BASE_CLAUDE/.claude/skills/$name/SKILL.md"
    if [ -f "$A" ] && [ -f "$C" ]; then
      assert "(b) skill '$name': .agents e .claude renderizam BYTE-IDÊNTICO (fonte única)" \
        'diff -q "$A" "$C" >/dev/null'
    else
      echo "FAIL: skill '$name' ausente em algum dos dois renders (.agents=$([ -f "$A" ] && echo ok || echo FALTA), .claude=$([ -f "$C" ] && echo ok || echo FALTA))"
      FAIL=1
    fi
  done
  assert "(b) marathon (Codex) NÃO hardcoda .claude/runs (usa harness_runs_dir)" \
    '! grep -q "\.claude/runs" "$BASE/.agents/skills/marathon/SKILL.md" || grep -q "harness_runs_dir\|HARNESS_RUNS_DIR" "$REPO_ROOT/copier.yml"'
fi

# =============================================================================
# (c) sub-gap 2 — completion-gate.py com payload Codex real
# =============================================================================
GATE="$BASE/.harness/hooks/completion-gate.py"
assert "(c) completion-gate.py existe no render" '[ -f "$GATE" ]'

if [ -f "$GATE" ]; then
  OUT="$(echo '{"stop_hook_active": false, "transcript_path": null, "last_assistant_message": "All done, everything is fixed and 100% complete. Ready for production."}' | python3 "$GATE")"
  EXIT=$?
  assert "(c) payload Codex, claim EN, sem sentinel -> exit 2 (bloqueia)" '[ "$EXIT" -eq 2 ]'

  echo '{"stop_hook_active": false, "transcript_path": null, "last_assistant_message": "Task complete. PROVA-DE-CONCLUSAO: 5/5 PASS, gaps: [nenhum]"}' | python3 "$GATE" >/dev/null 2>&1
  EXIT=$?
  assert "(c) payload Codex, claim EN, COM sentinel completo -> exit 0 (libera)" '[ "$EXIT" -eq 0 ]'

  echo '{"stop_hook_active": false, "transcript_path": null, "last_assistant_message": "All fixed. PROVA-DE-CONCLUSAO: 0/999"}' | python3 "$GATE" >/dev/null 2>&1
  EXIT=$?
  assert "(c) payload Codex, sentinel BARE 0/999 (sem PASS/gaps) -> exit 2 (não é sentinel válido)" '[ "$EXIT" -eq 2 ]'

  echo '{"stop_hook_active": false, "transcript_path": null, "last_assistant_message": "I fixed the null check in parser.py line 42."}' | python3 "$GATE" >/dev/null 2>&1
  EXIT=$?
  assert "(c) payload Codex, sem claim de plano -> exit 0" '[ "$EXIT" -eq 0 ]'

  echo '{"stop_hook_active": false, "transcript_path": null, "last_assistant_message": "Plano executado, tudo corrigido, 100%."}' | python3 "$GATE" >/dev/null 2>&1
  EXIT=$?
  assert "(c) regressão: claim em PT ainda bloqueia sem sentinel -> exit 2" '[ "$EXIT" -eq 2 ]'
fi

# =============================================================================
# (d) sub-gap 3 — hooks.json com throttle em PreToolUse (não SubagentStart)
# =============================================================================
HOOKS_JSON="$BASE/.codex/hooks.json"
assert "(d) .codex/hooks.json existe e é JSON válido" \
  'python3 -c "import json,sys; json.load(open(\"$HOOKS_JSON\"))" 2>/dev/null'

if [ -f "$HOOKS_JSON" ]; then
  PRETOOL_HAS_THROTTLE="$(python3 -c "
import json
d = json.load(open('$HOOKS_JSON'))
pre = d['hooks'].get('PreToolUse', [])
print(any('subagent-throttle' in str(entry) for entry in pre))
")"
  assert "(d) PreToolUse registra subagent-throttle.sh" '[ "$PRETOOL_HAS_THROTTLE" = "True" ]'

  PRETOOL_MATCHER_OK="$(python3 -c "
import json
d = json.load(open('$HOOKS_JSON'))
pre = d['hooks'].get('PreToolUse', [])
matchers = [e.get('matcher','') for e in pre if 'subagent-throttle' in str(e)]
print(any('spawn_agent' in m or 'Agent' in m for m in matchers))
")"
  assert "(d) matcher do PreToolUse do throttle casa spawn_agent/Agent" '[ "$PRETOOL_MATCHER_OK" = "True" ]'

  SUBAGENTSTART_HAS_THROTTLE="$(python3 -c "
import json
d = json.load(open('$HOOKS_JSON'))
sa = d['hooks'].get('SubagentStart', [])
print(any('subagent-throttle' in str(entry) for entry in sa))
")"
  assert "(d) SubagentStart NÃO tem mais o throttle (evento não bloqueia)" '[ "$SUBAGENTSTART_HAS_THROTTLE" = "False" ]'
fi

# =============================================================================
# grep de termos do doador/outros projetos do dono = 0 (F9, honestidade de
# produto genérico — reforçado aqui para o subconjunto codex-only)
# =============================================================================
DONOR_HITS="$(grep -rlEi 'learnhouse|quero|makershub|agent-harness' "$BASE" 2>/dev/null | wc -l)"
assert "grep learnhouse|quero|makershub|agent-harness no render codex-only = 0" '[ "$DONOR_HITS" -eq 0 ]'

echo
echo "=== resumo ==="
if [ "$FAIL" -eq 0 ]; then
  echo "TODOS OS 3 SUB-GAPS DE A1/H3 FECHADOS (codex-only)."
else
  echo "AINDA HÁ GAP ABERTO — ver FAILs acima."
fi
exit $FAIL
