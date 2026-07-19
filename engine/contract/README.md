# engine/contract — camada executável de enforcement

Porte da pilha de enforcement do `agent-swarm` (`codex/{schemas,scripts,tests,verification}/` —
ver `docs/planning/research/02-agent-swarm.md` e `docs/planning/00-plano-consolidado.md` §3/§6 F1)
para o motor do agent-harness. Quatro camadas, stdlib puro (zero dependência externa):

1. **Schemas** (`schemas/*.schema.json`) — JSON Schema (draft 2020-12) para os payloads
   estruturados que um review adversarial produz: `plan-review-result.schema.json`,
   `execution-review-result.schema.json` (enums `SATISFEITO|REPLANEJAR|BLOQUEADO` e
   `SATISFEITO|CORRIGIR|BLOQUEADO`, com `allOf`/`if`/`then` exigindo `replan_request`/
   `fix_request` quando o veredito não é satisfeito) e `ledger-event.schema.json` (forma de
   um evento do ledger). Portados sem alteração — já eram genéricos.
2. **Witness** (`verification/witness-fixes.json` + `scripts/verify_witness.py`) — marcadores de
   texto load-bearing: cada `fix` declara um `file`+`marker` que DEVE existir literalmente no
   arquivo. `verify_witness.py --witness <path>` falha se o marcador sumiu (proteção contra
   regressão silenciosa de conteúdo que ninguém testa via asserção de comportamento).
3. **Ledger** (`scripts/agent_swarm_ledger.py`) — log JSONL append-only de eventos de loop
   (`review`, `replan-request`, `replan-consumed`, `fix-request`, `fix-consumed`, `validation`,
   `final`) por `run_id`, com subcomando `summary` agregando contagens e último status por loop.
4. **Testes de contrato** (`tests/test_agent_contract.py`, `unittest`) — suíte de regressão que
   protege as invariantes acima e as pontas geradas (schemas parseiam, TOML/YAML de agents
   parseia, o helper `assert_payload_block` funciona, o teste NEGATIVO do witness falha quando o
   marcador não existe).

`scripts/validate_contract.py` é a entrada única: valida os `.json` de `schemas/`+`verification/`,
roda `validate_skills.py`, roda `verify_witness.py`, roda `unittest discover -s tests`, e (a menos
que `--skip-git-check`) roda `git diff --check`. **Nao ha GitHub Actions neste pacote** — a
validação é local/manual, invocada via `python3 engine/contract/scripts/validate_contract.py`.

## O que foi PARAMETRIZADO nesta rodada (F1)

Instrução explícita do plano: trocar hardcode por leitura de `.harness/harness.conf` via
`engine/_tooling_conf.py`, sem duplicar o parser.

| Script | Hardcode original | Chave de config (default = valor original) |
|---|---|---|
| `validate_skills.py` | `SKILL_DIR = ROOT/".agents"/"skills"` | `HARNESS_SKILLS_DIR` |
| `validate_skills.py` | `REQUIRED_SKILLS = ("learnhouse-delivery-council", "adversarial-review", "clarification-plan")` | `HARNESS_REQUIRED_SKILLS` (CSV; default vazio) |
| `validate_skills.py` | `.codex/agents`, `.codex/config.toml` | `HARNESS_CODEX_AGENTS_DIR`, `HARNESS_CODEX_CONFIG_PATH` (skip fail-open se `.codex/` não existir — projeto só-Claude) |
| `validate_skills.py` | `openai.yaml` de `learnhouse-delivery-council` fixo | `HARNESS_COUNCIL_SKILL_NAME` (opcional; vazio = checagem pulada) |
| `agent_swarm_ledger.py` | `RUNS_DIR = ROOT/".agent-swarm"/"runs"` | `HARNESS_LEDGER_DIR` (default `${HARNESS_RUNS_DIR}/agent-swarm` — reaproveita o run-state dir do marathon em vez de um segundo diretório-raiz) |
| `render_prompt.py` | linha 1 `"Use $learnhouse-delivery-council."` | `HARNESS_COUNCIL_SKILL_NAME` (fallback `delivery-council`) |

`validate_contract.py` e `verify_witness.py` NÃO foram parametrizados para apontar a um
projeto-alvo — de propósito. Eles são **self-referential**: protegem o conteúdo do PRÓPRIO
`engine/contract/` (que este `validate_contract.py` esteja íntegro, que os markers do witness
ainda existam nos arquivos deste pacote), não conteúdo de um projeto instalado. `ROOT =
Path(__file__).resolve().parents[1]` continua correto para os dois. Já `validate_skills.py` e
`agent_swarm_ledger.py` validam/gravam estado do **projeto-alvo**, então usam
`_tooling_conf.project_root()` (`HARNESS_PROJECT_ROOT` -> `CLAUDE_PROJECT_DIR` -> `git
rev-parse --show-toplevel` -> cwd).

## O que NÃO foi portado na rodada F1 (deferido para F1.5 — já concluído)

`witness-fixes.json` original tinha 9 entradas; 7 apontavam para conteúdo do **council**
(pipeline em `README.md`, sentinels `REPLAN-REQUEST`/`FIX-REQUEST` em
`.agents/skills/learnhouse-delivery-council/SKILL.md`, gates finais) — arquivos que ainda não
existiam neste layout porque a fusão das 2 linhagens do council (learnhouse `.claude/skills/
learnhouse-delivery-council/SKILL.md` × agent-swarm `.agents/skills/learnhouse-delivery-council/
SKILL.md`) era **F1.5** (`docs/planning/00-plano-consolidado.md` §6 F1.5 e §3 "Merge das 2
linhagens do council"), não F1. Na rodada F1, `verification/witness-fixes.json` ficou só com as
2 entradas cujo marker sobrevivia no que tinha sido de fato portado (`TEST-PAYLOAD-SCOPE-001`,
`LOCAL-CONTRACT-001`) e 7 testes de `tests/test_agent_contract.py` ficaram `@unittest.skip(...)`.

**F1.5 concluído** (mesma sessão): merge real em `templates/.agents/skills/
{{ project_name }}-delivery-council/SKILL.md.jinja` + `templates/.agents/skills/adversarial-review/
SKILL.md.jinja` + `templates/{% if use_codex %}.codex{% endif %}/agents/{{ project_name }}-adversarial-reviewer.toml.jinja`
(paths pós-restructure F3 — `templates/` espelha a raiz do projeto-alvo direto, sem wrapper
`claude/`/`codex/`/`shared/`), com o padrão "REPLAN/FIX-REQUEST+CONSUMED (linhagem agent-swarm)
fundido com subagent-obrigatório+REVISORES+SendMessage (linhagem learnhouse)". Witness próprio em
`templates/verification/council-witness.json` (6 markers, `verify_witness.py --root
templates` — flag `--root` nova, generalização mínima que preserva o default
self-referential deste pacote). 5 dos 7 testes skipped foram REATIVADOS com paths adaptados em
`templates/tests/test_council_merge.py` (perto do conteúdo mesclado, não aqui — ver nota
no topo do arquivo de teste). Os 2 restantes (`test_readme_has_single_ordered_pipeline_with_real_loops`,
`test_historical_plan_doc_is_marked_non_canonical`) continuam skipped: dependem de um README com
diagrama mermaid do pipeline (escopo F7/case-study) e de `docs/PLANO-SWARM.md` (doc histórico
específico do agent-swarm original, sem equivalente aqui) — nenhum dos dois pertence ao merge do
SKILL.md em si.
