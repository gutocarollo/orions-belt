# Investigação 2 — gutocarollo/agent-swarm (clone lido arquivo a arquivo)

- **Clone:** `/tmp/claude-1000/-home-augusto-code-learnhouse/d14a153c-a4e0-4575-82ab-a19228a1a393/scratchpad/harness-portable/clones/agent-swarm`
- **HEAD:** `df68912` (2026-07-07) — 12 commits. História: 9 commits iniciais constroem a trilha Codex (`f2bb06a Add Codex-native agent swarm` → `3f155d8 Add executable contract validation` → `316231c Remove GitHub Actions validation`), depois `20ea7b2` move tudo para `codex/`, `76e9232` adiciona a trilha `claude/` (extração do learnhouse em 2026-07-07) e `df68912` porta "4 padrões slim-shape" para ref-integrity/docs-wiki-lint + CI.
- **40 arquivos tracked** (1 raiz + 16 em `claude/` + 23 em `codex/`). Todos lidos.
- **Validação executada nesta sessão:** `python3 scripts/validate_contract.py --skip-git-check` na trilha codex → **verde** (3 JSONs ok, `skill-contract-ok`, `witness: 9/9 verified`, **16/16 testes unittest OK**).

---

## (a) Inventário por trilha

### Raiz
| Arquivo | Linhas | Papel |
|---|---:|---|
| `README.md` | 11 | Declara o repo como "maquinário de agentes multi-runtime extraído de projetos reais"; `codex/` = trilha OpenAI Codex (conteúdo original), `claude/` = trilha Claude Code (padronização de documentação). |

### Trilha `codex/` (23 arquivos) — pacote Codex-native do Delivery Council + contrato executável
| Arquivo | Linhas | Papel |
|---|---:|---|
| `codex/README.md` | 375 | **Contrato canônico**: ordem fixa `PLAN -> PLAN_REVIEW -> EXECUTION -> EXECUTION_REVIEW`, tabela de ARGS, fluxograma mermaid dos gates, sentinels obrigatórios (`REPLAN-REQUEST/CONSUMED`, `FIX-REQUEST/CONSUMED`), exemplos de pares INVÁLIDOS de sentinels (L257-276), tabela do contrato executável (L285-292). |
| `codex/AGENTS.md` | 39 | Constituição de manutenção: quais 4 arquivos manter sincronizados, preservar gates/handoffs, "não transforme os scripts em segundo orquestrador" (L21), sem GitHub Actions (validação local), não copiar `.claude/CLAUDE.md`/segredos. |
| `codex/docs/PLANO-SWARM.md` | 609 | Visão original (histórico, marcado não-canônico em L1-8): decisão Codex-native vs Agents SDK (D1 com opções A/B/C, L554-575), arquitetura `AGENTS.md + .agents/skills + .codex/agents + prompts`, "Skill = processo / Agent = executor / AGENTS.md = constituição / Prompt = gatilho" (L103-107), nuance de subagents na IDE (L111-123), o que saiu do MVP (SDK, MCP server, runner Python, traces — L525-535). |
| `codex/.agents/skills/learnhouse-delivery-council/SKILL.md` | 305 | Skill orquestradora COM camada de handoff: passo 10 manda registrar rodadas no ledger (L80), blocos `REPLAN-REQUEST`→`REPLAN-CONSUMED` (L125-143) e `FIX-REQUEST`→`FIX-CONSUMED` (L199-221) com comandos de ledger prontos (L148-149, L226-227), gate "execucao NAO pode comecar" após REPLANEJAR na rodada final (L152). |
| `codex/.agents/skills/adversarial-review/SKILL.md` | 272 | Contrato da review (9 classes de prova, veredictos REAL/TEORICO/REFUTADO/NAO-PROVADO, anti-padrões) + **§7 "Saida para loops do Delivery Council"** (L236-272): sentinels por loop + espelho JSON opcional nos schemas. |
| `codex/.agents/skills/clarification-plan/SKILL.md` | 75 | Blocos D[n] com comportamento/exemplo bom/exemplo ruim/quando escolher + terceira via obrigatória. |
| `codex/.agents/skills/learnhouse-delivery-council/agents/openai.yaml` | 4 | Metadata de interface da skill (display_name, short_description, default_prompt). |
| `codex/.codex/agents/*.toml` (4) | 16-59 | Personas: `context-scout` (read-only, Context Brief), `implementer` (workspace-write, só plano aprovado), `adversarial-reviewer` (read-only, effort=high, sentinels + FIX/REPLAN-REQUEST mandatórios + gates de rodada final + espelho JSON, L27-58), `test-auditor` (read-only, evidência sustenta claim). |
| `codex/.codex/config.toml` | 5 | `project_doc_max_bytes=65536`, `[agents] max_threads=4, max_depth=1`. |
| `codex/schemas/*.schema.json` (3) | 20-50 | Contratos JSON draft 2020-12 (detalhe em (b)). |
| `codex/scripts/*.py` (5) | 46-112 | `validate_contract`, `validate_skills`, `verify_witness`, `agent_swarm_ledger`, `render_prompt` (detalhe em (b)). |
| `codex/tests/test_agent_contract.py` | 364 | 16 testes de regressão do CONTRATO EM PROSA (detalhe em (b)). |
| `codex/verification/witness-fixes.json` | 59 | 9 marcadores load-bearing (detalhe em (b)). |
| `codex/.gitignore` | 12 | Ignora `.agent-swarm/runs/` (ledger é evidência local, nunca commitada). |

### Trilha `claude/` (16 arquivos) — extração sanitizada do harness learnhouse (2026-07-07)
| Arquivo | Linhas | Estado vs learnhouse vivo |
|---|---:|---|
| `claude/README.md` | 27 | Mapa artefato→path original; explica que `docs/index.md`/`log.md` reais ficaram FORA (conteúdo privado). |
| `claude/CLAUDE.md` | 184 | CLAUDE.md **curado para publicação**: só blocos de metodologia (wiki Karpathy, council, LEI ZERO, §14 DRY, §15 Boris Cherny, §16 self-improvement). Infra/prod/credenciais removidos. |
| `claude/docs/SCHEMA.md` | 99 | **Byte-idêntico** a `learnhouse/docs/SCHEMA.md`. |
| `claude/scripts/docs-wiki-lint.py` | 165 | **Byte-idêntico 3-way** (learnhouse + harness-wiki/sources). Contém padrão portado do "slim-shape" (`check_no_foreign_live_links`, L74-92). |
| `claude/scripts/ref-integrity.py` | 341 | **Byte-idêntico 3-way**. |
| `claude/scripts/design-system-wiki-lint.py` | 24 | Shim de compat — idêntico ao learnhouse. |
| `claude/githooks/pre-commit` | 5 | Idêntico (adaptador fino `ref-integrity --staged`). |
| `claude/github-workflows/docs-integrity.yaml` | 52 | Quase idêntico ao learnhouse (learnhouse adiciona `workflow_dispatch` + trigger no próprio path do workflow). |
| `claude/hooks/lessons-inject.sh` | 12 | Idêntico (SessionStart, cap 80 linhas, tag `<lessons-learned>`). |
| `claude/loop.md` | 28 | Idêntico ao `.claude/loop.md` (6 checks + regras). |
| `claude/ref-integrity-allowlist` | 23 | Sanitizado: `Proposta-Comercial-Quero-Quero.pdf` → `proposta-comercial-<cliente>.pdf` (L21). |
| `claude/skills/learnhouse-delivery-council/SKILL.md` | 235 | **Idêntico** ao `.claude/skills/` do learnhouse (variante "subagent obrigatório", SEM handoffs — ver (c)). |
| `claude/skills/adversarial-review/SKILL.md` | 238 | Idêntico exceto descrição sanitizada ("LearnHouse/QQ Academy" → "LearnHouse", L3). |
| `claude/skills/ref-integrity/SKILL.md` | 55 | Idêntico. Documenta o padrão "1 fonte de lógica, 3 adaptadores finos" (pre-commit/skill/loop) + CI. |
| `claude/skills/repo-wiki-curator/SKILL.md` | 59 | Idêntico. |
| `claude/tasks/lessons.md` | 65 | 8 lições reais de 2026-07-07 como EXEMPLO do ciclo capturar→promover (`[PROMOVIDA → destino]`). |

---

## (b) Trilha `codex/` EM DETALHE — o contrato executável

### PLANO-SWARM.md — a visão
Documento histórico (auto-marcado não-canônico, e um TESTE garante essa marcação — `test_historical_plan_doc_is_marked_non_canonical`, `tests/test_agent_contract.py:209`). Conteúdo decisivo para o framework portátil:
1. **Decisão de runtime** (D1, L554-575): NÃO usar Agents SDK/API key como base — o orquestrador é o próprio runtime nativo (`AGENTS.md` + repo skills + custom agents + prompts), porque o requisito era operar dentro da assinatura (ChatGPT Pro), sem token. Opção C escolhida: Codex-native agora, SDK só para automação externa futura.
2. **Taxonomia** (L103-107): `Skill = processo | Agent = executor especializado | AGENTS.md = constituição | Prompt = gatilho da rodada`. É a taxonomia certa para o framework unificado, pois mapeia 1:1 no Claude Code (SKILL.md / .claude/agents / CLAUDE.md / prompt).
3. **Limites de fan-out** (L348-356): `max_threads=4`, `max_depth=1` com justificativa (fan-out recursivo).
4. O plano original continha versões FRACAS dos loops ("execute quando o review ficar SATISFEITO") que foram endurecidas depois; um teste NEGATIVO garante que os exemplos fracos não voltam (`assertNotIn("execute quando o review ficar SATISFEITO", ...)`, `tests/test_agent_contract.py:217`).

### schemas/*.schema.json — contratos de máquina dos sentinels
Os sentinels Markdown são a interface humana; os schemas são o espelho parseável (opt-in). Regra explícita: **o JSON não substitui o Markdown** (garantido por teste, `test_structured_schema_mirror_does_not_replace_markdown_sentinels`, L200-207).

1. **`plan-review-result.schema.json`** (50 L): `plan_adversarial_verification ∈ {SATISFEITO, REPLANEJAR, BLOQUEADO}`, `gaps_criticos ≥ 0`, `decisao_escolhida`, `proxima_acao ∈ {executar, replanejar, pedir decisao}`, e `replan_request[]` com itens `{gap, evidencia, alteracao_obrigatoria}` (todos minLength 1). **Condicional load-bearing** (L38-49): `if status==REPLANEJAR then replan_request required com minItems 1` — impossível declarar replanejamento sem entregar o pedido acionável.
2. **`execution-review-result.schema.json`** (47 L): mesmo desenho para `adversarial_verification ∈ {SATISFEITO, CORRIGIR, BLOQUEADO}` + `fix_request[]`; `if CORRIGIR then fix_request minItems 1` (L35-46).
3. **`ledger-event.schema.json`** (20 L): evento de auditoria do loop — `ts` (sufixo Z), `run_id` (`^[A-Za-z0-9_.-]+$`), `loop ∈ {planning, execution}`, `round ≥ 1`, `event ∈ {review, replan-request, replan-consumed, fix-request, fix-consumed, validation, final}`, `status`, `payload` (objeto livre). `additionalProperties:false` nos 3.

**Para que servem:** dão forma tipada exatamente à informação que trafega entre reviewer e orquestrador. O par request/consumed é o mecanismo anti-"gate fantasma": o reviewer é obrigado a especificar a mudança mínima; o orquestrador é obrigado a registrar o consumo antes da próxima rodada.

### scripts/*.py — como se encaixam num pipeline
Pipeline em camadas, com um único ponto de entrada e proibição explícita de virar "segundo orquestrador" (`AGENTS.md:18-21`):

```
validate_contract.py  (entrada única)
 ├─ json.loads em schemas/*.json + verification/*.json     (sanidade sintática)
 ├─ validate_skills.py                                     (metadata das skills/agents)
 ├─ verify_witness.py                                      (marcadores load-bearing)
 ├─ python -m unittest discover tests/                     (16 testes de regressão do contrato)
 └─ git diff --check                                       (whitespace)
render_prompt.py       (lado do humano: gera prompt ARGS válido)
agent_swarm_ledger.py  (lado do runtime: registra evidência das rodadas)
```

- **`validate_contract.py`** (46 L): orquestra as 5 etapas acima; `--skip-git-check` para rodar fora de árvore limpa. Substituiu GitHub Actions deliberadamente (commit `316231c`; teste `test_contract_validation_is_local_not_github_actions` verifica que `.github/workflows` está VAZIO e que README/AGENTS dizem isso, L267-278).
- **`validate_skills.py`** (78 L): parser de frontmatter próprio (sem PyYAML — zero dependência externa), valida `name`==pasta e `description` não-vazia nas 3 skills obrigatórias (L36-44); valida `openai.yaml` por marcadores (L47-52); parseia TODOS os TOML de `.codex/` com `tomllib` stdlib e exige `name/description/sandbox_mode/developer_instructions` (L55-61).
- **`verify_witness.py`** (85 L): lê `verification/witness-fixes.json` (schema `agent-swarm-witness/v1`), e para cada "fix" confere que o `marker` (string literal ≥10 chars) ainda existe no `file` apontado; reporta `markerVerified` + `fileSha256` por item, `--json` para saída máquina, exit 1 se qualquer marcador sumiu (L32-64). É um **anti-regressão de PROSA**: garante que uma edição de documentação não apaga silenciosamente uma regra que sustenta o contrato.
- **`agent_swarm_ledger.py`** (112 L): CLI `append`/`summary`. `append` grava JSONL em `.agent-swarm/runs/<run-id>/loop.jsonl` (gitignored) com `ts` UTC, loop, round, event (choices = enum do schema), status e payload JSON (aceita stdin, L24-32); valida `run_id` por regex (L35-38). `summary` agrega contagens `loop:event` + último status por loop (L58-70). Responde à pergunta de auditoria: **"a mensagem trafegou entre reviewer e Council?"** (`codex/README.md:318`).
- **`render_prompt.py`** (60 L): gera o bloco `Use $learnhouse-delivery-council. ARGS: ...` já validado — rejeita `PLAN_REVIEW_MAX>2`, `EXECUTION_REVIEW_MAX>3`, e `PLAN_REVIEW` sem `--plan-source` (L31-36); aplica o default condicional de `AUTO_EXECUTE_AFTER_PLAN` (true só em PLAN_REVIEW, L38-40). Reduz erro humano na interface textual.

### tests/test_agent_contract.py — teste de regressão de CONTRATO EM PROSA (a ideia mais original do repo)
16 testes que tratam README/SKILL/TOML/AGENTS como artefatos testáveis:
- `assert_payload_block` (L23-32): regex com escopo — os campos `gap:/evidencia:/alteracao-obrigatoria:` precisam estar DENTRO do bloco bullet sob o marcador (`REPLAN-REQUEST:`), não espalhados pelo arquivo; e há um teste do próprio helper com texto sintético que DEVE falhar (L159-174). Witness `TEST-PAYLOAD-SCOPE-001` protege esse helper.
- Handoffs presentes em TODOS os arquivos do contrato (README, council SKILL, reviewer TOML, adversarial SKILL, AGENTS) — L69-131.
- Gates de rodada final: par inválido `PLAN-ADVERSARIAL-LOOP: 2/2 PENDENTE` + execução, e `ADVERSARIAL-LOOP: 3/3 PENDENTE` + `SATISFEITO` — bloqueados em prosa e testados (L133-145).
- Mermaid do README testado nó a nó (loops reais `i=i+1`/`j=j+1`, L46-67).
- Schemas testados (enums + condicionais `then`, L187-198).
- Witness testado positivo (todos os markers existem, L232-239) e **negativo** (witness sintético com marker inexistente deve falhar com "marker missing", L241-265) — aplicação direta da lição "guard novo só conta depois de teste NEGATIVO" (`claude/tasks/lessons.md:38`).
- Subprocess-tests dos CLIs: render_prompt rejeita args inválidos (L280-311); ledger grava e sumariza JSONL de verdade (L313-360).

### verification/witness-fixes.json
9 marcadores: ordem do pipeline (ORDER-001), os 4 handoffs (PLAN/EXEC × REQUEST/CONSUMED), os 2 gates finais na SKILL do council (`execucao NAO pode comecar`, `nao declare 'ADVERSARIAL-VERIFICATION: SATISFEITO'`), o helper de teste (TEST-PAYLOAD-SCOPE-001) e a política local-not-CI (LOCAL-CONTRACT-001). Cada um com `id`, `desc`, `file`, `marker`.

---

## (c) Trilha `claude/` vs harness vivo do learnhouse — o FORK que o plano precisa reconciliar

### O que é idêntico (extração fiel, diffs rodados nesta sessão)
`docs-wiki-lint.py`, `ref-integrity.py`, `design-system-wiki-lint.py`, `docs/SCHEMA.md`, `loop.md`, `lessons-inject.sh`, `pre-commit`, e as skills `learnhouse-delivery-council` (variante .claude), `repo-wiki-curator`, `ref-integrity` são **byte-idênticos** entre `agent-swarm/claude/`, `/home/augusto/code/learnhouse` e `/home/augusto/code/harness-wiki/sources/` (diff = 0 nos 3 pares; `wc -l` 165/341 confirmado nos 3). Sanitizações pontuais: descrição da adversarial-review (remove "QQ Academy") e allowlist (anonimiza o PDF do cliente). Ou seja: **não há drift de versão nos scripts** — a fonte única se manteve.

### O que DIVERGIU — e em DIREÇÕES OPOSTAS (achado central)
O council existe em 2 linhagens que evoluíram features diferentes depois do fork de 2026-07-07:

| Feature | agent-swarm `codex/` | learnhouse vivo (`.agents`+`.codex`+`.claude`) = harness-wiki sources |
|---|---|---|
| Handoff `REPLAN-REQUEST`/`REPLAN-CONSUMED` | **SIM** (SKILL L125-152; reviewer TOML L43-51) | **NÃO** (removido/nunca portado — diff de 122 linhas no council) |
| Handoff `FIX-REQUEST`/`FIX-CONSUMED` | **SIM** (SKILL L199-227; reviewer TOML L27-35) | **NÃO** |
| Gates anti-"pendente formal" de rodada final | **SIM** (SKILL L152, L164-169; TOML L54-56) | Parcial (só limites de rodada; sem a regra "edit pós-review = novo replan") |
| Integração ledger (`agent_swarm_ledger.py`) | **SIM** (SKILL L80, L145-149, L223-227) | **NÃO** |
| Espelho JSON dos schemas | **SIM** (TOML L58; adversarial §7 L269-272) | **NÃO** |
| Review SEMPRE em subagent (nunca inline) + linha `REVISORES:` | **NÃO** ("Rode $adversarial-review OU use learnhouse-adversarial-reviewer") | **SIM** (council L116/L153 "DISPARE um subagent... NUNCA roda inline"; `REVISORES:` L142; adversarial "Modo de execucao — self-review inline proibido" L10-13) — promovida da lição de 2026-07-07 (`lessons.md:58-65`) |
| Continuação do MESMO subagent na rodada N+1 (SendMessage) | **NÃO** | **SIM** |
| Understand Anything guards nos 4 TOMLs | **NÃO** | **SIM** (guards de `git diff --relative=apps` nos 4 agents) |
| Naming pós-migração nos paths citados (`sad.md` vs `SAD.md`) | **NÃO** (paths antigos CAPS) | **SIM** |

Detalhe curioso: dentro do PRÓPRIO agent-swarm, `claude/skills/learnhouse-delivery-council` (variante learnhouse .claude, COM subagent obrigatório, SEM handoffs) e `codex/.agents/skills/learnhouse-delivery-council` (COM handoffs, SEM subagent obrigatório) **coexistem divergentes** — o repo publica as duas linhagens sem reconciliá-las.

### harness-wiki vs agent-swarm
- `harness-wiki/sources/.claude/skills/*` == learnhouse vivo (diff 0) → a wiki herda as mesmas ausências.
- `harness-wiki/chapters/14-repos-publicos.md` documenta o agent-swarm APENAS no nível do README e declara textualmente: "Conteúdo de arquivos internos não listados aqui não foi lido" (L81) e que nenhum dos repos é citado por nome dentro do learnhouse (L83). Toda a camada executável codex (schemas/ledger/witness/testes) é **invisível** para a wiki hoje.
- `harness-wiki/verify.py` é um lint próprio (links de capítulos resolvem, citações inline espelhadas em `sources/`, manifest/llms.txt sincronizados) — propósito diferente do witness (que protege marcadores de contrato), mas a MECÂNICA é parente: ambos são "verificadores determinísticos de prosa". No framework unificado podem compartilhar infra.

---

## (d) GAPS vs harness-wiki local — funcionalidade presente no agent-swarm e AUSENTE em `/home/augusto/code/harness-wiki`

| # | Funcionalidade (path no agent-swarm) | Existe no harness-wiki? | Vale absorver no framework unificado? |
|---|---|---|---|
| G1 | **Schemas JSON dos reviews** (`codex/schemas/plan-review-result.schema.json`, `execution-review-result.schema.json`) | Não (nem em learnhouse vivo) | **SIM, alta prioridade.** É o contrato de máquina que falta ao council vivo: o condicional `REPLANEJAR→replan_request obrigatório` transforma sentinel de prosa em dado validável. Custo ~100 linhas JSON já prontas; genérico (nada de learnhouse no schema). Base ideal para um futuro Stop-hook validar o output do reviewer. |
| G2 | **Ledger JSONL por run** (`codex/scripts/agent_swarm_ledger.py` + `ledger-event.schema.json` + `.gitignore` de `.agent-swarm/runs/`) | Não. O harness tem `task-journal.log` e RUN.md da marathon, mas nenhum registro estruturado por rodada de loop adversarial | **SIM.** Resolve auditoria real ("a mensagem trafegou entre reviewer e Council?") que hoje depende de ler transcript — exatamente o problema da lição `lessons.md:58-65` (usuário concluiu que subagents não rodaram). 112 linhas stdlib, portável as-is; só parametrizar o diretório de runs via config central. |
| G3 | **Witness de marcadores load-bearing** (`codex/verification/witness-fixes.json` + `scripts/verify_witness.py`) | Não. `verify.py` do harness-wiki checa links/espelhamento/manifest, mas NÃO protege frases de contrato contra edição regressiva | **SIM, é a peça mais reutilizável do repo.** Framework portátil = muita prosa normativa (CLAUDE.md, SKILLs, AGENTS.md); witness é o único guard que impede curadoria/edição de apagar regra crítica silenciosamente. Genérico por construção (`file` + `marker`). Absorver junto com a regra cultural "guard novo só conta com teste negativo". |
| G4 | **Ponto único de validação** (`codex/scripts/validate_contract.py`) | Não (harness-wiki roda `verify.py` isolado; learnhouse tem N gates dispersos em hooks) | **SIM.** O padrão "1 entrada → sanidade JSON → metadata → witness → unittest → git diff --check" é o esqueleto natural do `framework doctor`/`selftest` do produto unificado. |
| G5 | **Validador de metadata de skills/agents sem dependências** (`codex/scripts/validate_skills.py`) | Não | **SIM, generalizando.** Hoje hardcoda as 3 skills e paths `.agents/`/`.codex/`; no framework, a lista de skills obrigatórias e os diretórios por runtime (claude/codex) vêm do arquivo de config central. O parser frontmatter/tomllib stdlib é portável as-is. |
| G6 | **Testes de regressão de contrato em prosa** (`codex/tests/test_agent_contract.py`, 16 testes, helper `assert_payload_block` com escopo + testes negativos) | Não — o harness-wiki não tem NENHUM teste; learnhouse não testa suas skills | **SIM (o padrão, adaptando os alvos).** A técnica "prosa normativa é artefato testável" é o que garante que o framework sobreviva às próprias edições. Absorver o helper e a disciplina (positivo+negativo); reescrever os asserts para os arquivos do framework. |
| G7 | **Handoffs `REPLAN-REQUEST/CONSUMED` + `FIX-REQUEST/CONSUMED`** (council SKILL codex L125-227; reviewer TOML L27-56) | Não (nem no learnhouse vivo — só na linhagem codex) | **SIM — é o merge obrigatório.** O framework unificado deve fundir as DUAS linhagens do council: handoffs+gates+ledger (codex) × subagent-obrigatório+`REVISORES:`+continuação de subagent (learnhouse vivo). Nenhuma das duas sozinha é o estado da arte do próprio Augusto. |
| G8 | **Prompt generator** (`codex/scripts/render_prompt.py`) | Não | **SIM, baixo custo.** Vira o `framework prompt` do CLI unificado; validação de limites (2/2, 3/3) deixa de ser confiança em prosa. |
| G9 | **`AGENTS.md` como constituição de manutenção com regras de sincronização** (`codex/AGENTS.md`: lista dos arquivos-espelho a manter em sync, "scripts nunca viram segundo orquestrador", validação pré-commit) | Não (harness-wiki tem SCHEMA.md editorial, sem regra de sync de contrato) | **SIM.** O framework terá o mesmo problema (N arquivos espelhando o mesmo contrato em 2 runtimes); a solução do agent-swarm é: regra em prosa + witness + teste. |
| G10 | **Metadata de interface de skill** (`openai.yaml` com display_name/default_prompt) | Não | **Parcial.** Absorver como campo opcional do manifest de skill no config central (equivalente Codex); não é crítico. |
| G11 | **Marcação não-canônica TESTADA de doc histórico** (banner em `PLANO-SWARM.md:1-8` + teste L209-217 que inclui `assertNotIn` de contratos antigos) | Não (harness-wiki tem status no SCHEMA, mas nada testa que doc histórico não ressuscite contrato velho) | **SIM.** Fecha o buraco entre wiki temporal (status declarado) e enforcement (teste que o exemplo perigoso não volta). |
| G12 | **Trilhas multi-runtime separadas** (`claude/` vs `codex/` no mesmo repo, com README-mapa por trilha) | Parcial — harness-wiki documenta só Claude Code; espelha `.codex/agents` em sources mas não as `.agents/skills` Codex | **SIM como INSPIRAÇÃO de layout, NÃO como layout final.** O fork provou o custo de manter 2 trilhas paralelas (divergiram em 4 meses). O framework deve ter núcleo runtime-agnóstico + adaptadores gerados/validados, não duas cópias irmãs. |

**Não absorver:** `PLANO-SWARM.md` como contrato (é histórico, e o próprio repo o marca assim); a duplicação council `.claude` vs `.agents` sem reconciliação (é o anti-exemplo); GitHub Actions para o contrato (decisão explícita e testada do agent-swarm é validação local — para o framework, manter local-first com CI opcional como a trilha claude faz para docs).

---

## Recomendações para o plano do framework portátil

1. **Merge das duas linhagens do council é pré-requisito, não melhoria.** Antes de portar, produzir a versão única: pipeline ordenado + handoffs REQUEST/CONSUMED + gates de rodada final (codex) + review sempre-em-subagent com `REVISORES:` e continuação do mesmo subagent (learnhouse vivo). O texto-fonte de ambos já existe; o merge é editorial e depois protegido por witness+testes (G3/G6).
2. **Adotar a pilha de enforcement em 4 camadas do codex como espinha do framework:** schemas (forma) → witness (prosa load-bearing) → unittest de contrato (regressão, com teste negativo obrigatório) → `validate_contract.py` (entrada única). Tudo stdlib Python, zero deps — perfeito para bootstrap "auto-configurável em qualquer projeto".
3. **Parametrizar, não reescrever:** os 5 scripts codex usam `ROOT = Path(__file__).resolve().parents[1]` e paths fixos (`.agents/skills`, `.codex/agents`, `.agent-swarm/runs`); a mudança para o framework é ler esses paths + lista de skills obrigatórias + limites de loop (2/2, 3/3) do arquivo de config central. As assinaturas dos CLIs (`append/summary`, `--witness`, `--start-at`) já estão certas.
4. **Ledger como evidência universal de loop:** integrar `agent_swarm_ledger.py` também no lado Claude (hoje só a SKILL codex o cita) e ligá-lo aos Stop-hooks existentes do learnhouse (completion-gate poderia exigir ledger da rodada final quando um loop adversarial foi declarado).
5. **Witness como guard da própria migração dos 3 repos:** o primeiro `witness-fixes.json` do framework deve listar os marcadores que NÃO podem se perder na unificação (handoffs, gates, regra subagent-obrigatório, sentinels) — usa a ferramenta para proteger a própria fusão.
6. **Registrar a decisão de runtime (PLANO-SWARM D1) como ADR do framework:** orquestração = runtime nativo de cada agente (skills/agents/constituição/prompt), sem SDK/API key no MVP; SDKs só como camada externa opcional. Vale idêntico para Claude Code.
7. **Atualizar o harness-wiki (capítulo 14 ou novo capítulo)** com a camada executável do agent-swarm — hoje a wiki declara não ter lido os internals; esta investigação fecha esse gap e o conteúdo de (b) pode ser a fonte.
8. **Sanitização comprovada como processo:** a trilha claude mostra o procedimento de extração público-seguro (remover índices privados, anonimizar cliente, curar CLAUDE.md). O framework portátil, que nascerá público/multi-projeto, deve incorporar esse checklist de publicação (o `AGENTS.md:24-25` já tem a regra "não copie CLAUDE.md privado/credenciais/dumps").
