# loop.md — manutenção autônoma do orions-belt (rodar com /loop sem argumentos)

<!--
DOGFOOD (2026-07-19): o framework roda sobre si mesmo o mesmo loop de manutenção que INSTALA
nos projetos-alvo (templates/.claude/loop.md.jinja). Diferença de paths: aqui o motor de lint
vive em `engine/lint/` (não `.harness/lib/`, que é o path do projeto-alvo renderizado), e o
orions-belt não tem frontend/understand/ds-gate sobre si — então os checks stack-específicos
do template não se aplicam. Governança do repo: SCHEMA.md §5.
-->

Você está no loop de manutenção (Self-Improvement Loop — AGENTS.md/CLAUDE.md §16 do repo-alvo;
aqui, a governança é SCHEMA.md §5). Uma passada = os checks abaixo, na ordem, consertando o que
for barato e reportando o que não for. `/loop` roda no modelo da própria sessão (assinatura),
não usa API.

## Checks da passada

- **Wiki/documentação íntegra** — `python3 engine/lint/docs_wiki_lint.py --worktree`. FAIL →
  corrigir `docs/log.md` (índice temporal único) ou o índice da categoria (`docs/manual/README.md`
  para capítulos), regidos por `SCHEMA.md`, e re-rodar. Órfão sob `docs/` sem índice = falha.
- **Integridade referencial** — `python3 engine/lint/ref_integrity.py --selftest` (o detector
  funciona) + `python3 engine/lint/ref_integrity.py --range <ref-da-última-passada-verde>..HEAD`
  (refs `[link]`/`[stale]` que escaparam do pre-commit). Achado → repoint / desativar / allowlist.
- **Suíte de regressão do template** — os gates que provam o framework não regrediu:
  `python3 templates/tests/test_council_merge.py`,
  `python3 templates/.harness/lib/tests/test_scan_project.py`,
  `python3 engine/contract/scripts/validate_contract.py`; e, se `uvx` disponível,
  `bash templates/tests/test_codex_parity.sh` + `bash templates/tests/test_skill_runtime_parity.sh`.
  FAIL → diagnosticar e corrigir antes de seguir (§11 execução sequencial).
- **Drift template × manual** — componente novo/alterado em `templates/`/`engine/` sem o
  capítulo correspondente de `docs/manual/` atualizado no mesmo ciclo é bug de documentação
  (SCHEMA.md §5). Reportar o par driftado.
- **Árvore git suja de artefato órfão** — `git status --short`: arquivo gerado/dump que não
  deveria ser commitado (`long-context.md`, `.curate/`, PDF, JSON grande solto em `docs/`)?
  Reportar com path; não deletar nada tracked sem ordem explícita.
- **NOTICE × skills de terceiros** — se a lista de skills portadas (`.claude/skills/`) mudou,
  conferir se `templates/NOTICE.jinja` e `PROVENANCE.json` continuam sincronizados (limitação
  conhecida item 14, sem teste automatizado ainda). Reportar dessincronização.

## Regras do loop

- Ação irreversível (push, publish no GitHub, `gh repo edit --visibility`, delete tracked,
  reescrita de orphan/tag) = FORA do loop; apenas reportar como pendência para decisão humana.
- Cada passada termina com resumo de 3-6 linhas: o que passou, o que consertou, o que precisa
  de decisão humana.
- Nada a fazer em 2 passadas seguidas → encerrar o loop (self-paced: não agendar próxima).
